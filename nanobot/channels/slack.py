"""Slack channel implementation using slack-sdk."""

import asyncio
import json
import re
import threading
from queue import Queue

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import SlackConfig


def _markdown_to_slack_mrkdwn(text: str) -> str:
    """
    Convert markdown to Slack-compatible mrkdwn format.
    """
    if not text:
        return ""

    # Extract and protect code blocks
    code_blocks: list[str] = []
    def save_code_block(m):
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m):
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # Links [text](url) -> <url|text>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)

    # Bold **text** -> *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # Italic _text_ -> _text_
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'_\1_', text)

    # Strikethrough ~~text~~ -> ~text~
    text = re.sub(r'~~(.+?)~~', r'~\1~', text)

    # Bullet lists
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # Restore inline code with Slack code format
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00IC{i}\x00", f"`{code}`")

    # Restore code blocks with Slack code block format
    for i, code in enumerate(code_blocks):
        text = text.replace(f"\x00CB{i}\x00", f"```\n{code}\n```")

    return text


class SlackChannel(BaseChannel):
    """
    Slack channel using Socket Mode (no public server needed).

    Supports:
    - App mentions in channels (@nanobot)
    - Direct messages
    - Message editing
    """

    name = "slack"

    def __init__(self, config: SlackConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: SlackConfig = config
        self._socket_mode_client = None
        self._web_client = None
        self._user_ids: dict[str, str] = {}
        self._bot_user_id: str | None = None
        self._event_queue: Queue | None = None
        self._client_thread: threading.Thread | None = None

    async def start(self) -> None:
        """Start the Slack bot with Socket Mode."""
        if not self.config.bot_token:
            logger.error("Slack bot token not configured")
            return

        if not self.config.app_level_token:
            logger.error("Slack app level token not configured")
            return

        self._running = True
        self._event_queue = Queue()

        try:
            from slack_sdk.web.client import WebClient
            from slack_sdk.socket_mode import SocketModeClient
        except ImportError:
            logger.error("slack-sdk not installed. Install with: pip install slack-sdk")
            return

        # Initialize web client (sync)
        self._web_client = WebClient(token=self.config.bot_token)

        # Get bot info
        try:
            auth_response = self._web_client.auth_test()
            self._bot_user_id = auth_response["user_id"]
            logger.info(f"Slack bot connected as @{auth_response['user']} (ID: {self._bot_user_id})")
        except Exception as e:
            logger.error(f"Failed to authenticate with Slack: {e}")
            return

        # Define the message handler (receives raw string messages)
        def on_message(message: str):
            logger.info(f"Raw Slack message: {message[:200]}")
            try:
                data = json.loads(message)
                envelope_id = data.get("envelope_id")
                payload = data.get("payload", {})
                payload_type = payload.get("type")
                event = payload.get("event", {})
                event_type = event.get("type")

                logger.info(f"Parsed: type={data.get('type')}, payload_type={payload_type}, event_type={event_type}")

                # Queue the event for async processing
                if self._event_queue:
                    self._event_queue.put({
                        "type": event_type,
                        "event": event,
                        "team_id": payload.get("team_id"),
                        "envelope_id": envelope_id,
                    })

                # Acknowledge the event
                if self._socket_mode_client:
                    try:
                        self._socket_mode_client.send_socket_mode_response(
                            {"envelope_id": envelope_id, "payload": {"type": payload_type, "ack": True}}
                        )
                    except Exception as e:
                        logger.error(f"Error sending ack: {e}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message JSON: {e}")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

        # Define error handler
        def on_error(error: Exception):
            logger.error(f"Socket Mode error: {error}")

        # Initialize Socket Mode client with listeners
        self._socket_mode_client = SocketModeClient(
            app_token=self.config.app_level_token,
            web_client=self._web_client,
            on_message_listeners=[on_message],
            on_error_listeners=[on_error],
        )

        logger.info("Socket Mode client initialized, starting connection...")

        # Start the client in a separate thread
        self._client_thread = threading.Thread(
            target=self._run_socket_mode_client,
            daemon=True,
        )
        self._client_thread.start()

        # Process events from the queue
        while self._running:
            try:
                event = await asyncio.to_thread(self._event_queue.get, timeout=0.5)
                if event:
                    await self._process_event(event)
            except Exception:
                continue

    def _run_socket_mode_client(self) -> None:
        """Run the Socket Mode client in a separate thread."""
        try:
            logger.info("Connecting to Slack Socket Mode...")
            self._socket_mode_client.connect()
            logger.info("Socket Mode connected, starting to process messages...")
            # This blocks and processes messages until disconnected
            self._socket_mode_client.process_messages()
        except Exception as e:
            logger.error(f"Socket Mode client error: {e}", exc_info=True)

    async def stop(self) -> None:
        """Stop the Slack bot."""
        self._running = False

        if self._socket_mode_client:
            logger.info("Stopping Slack bot...")
            self._socket_mode_client.disconnect()
            self._socket_mode_client = None

        if self._client_thread:
            self._client_thread.join(timeout=5)
            self._client_thread = None

    async def _process_event(self, event_data: dict) -> None:
        """Process an event from the queue."""
        event_type = event_data["type"]
        event = event_data["event"]
        team_id = event_data["team_id"]

        logger.info(f"Processing event: type={event_type}")

        if event_type == "app_mention":
            await self._on_app_mention(event, team_id)
        elif event_type == "message":
            await self._on_message(event, team_id)
        else:
            logger.info(f"Unhandled event type: {event_type}")

    async def send(self, msg: OutboundMessage) -> str | None:
        """Send a message through Slack."""
        if not self._web_client:
            logger.warning("Slack client not running")
            return None

        try:
            # Convert markdown to Slack mrkdwn
            mrkdwn = _markdown_to_slack_mrkdwn(msg.content)

            # Determine if we need to post to a channel thread or as new message
            kwargs = {
                "channel": msg.chat_id,
                "text": mrkdwn,
            }

            # If thread_ts is in metadata, reply in thread
            if msg.metadata and msg.metadata.get("thread_ts"):
                kwargs["thread_ts"] = msg.metadata["thread_ts"]

            # Run in thread pool since WebClient is sync
            response = await asyncio.to_thread(
                self._web_client.chat_postMessage,
                **kwargs
            )

            if msg.track_message_id:
                return response.get("ts")
            return None

        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")
            return None

    async def edit(self, msg: OutboundMessage) -> bool:
        """Edit an existing message in Slack."""
        if not self._web_client:
            logger.warning("Slack client not running")
            return False

        if not msg.edit_message_id:
            logger.warning("edit_message_id not set for edit operation")
            return False

        try:
            mrkdwn = _markdown_to_slack_mrkdwn(msg.content)

            await asyncio.to_thread(
                self._web_client.chat_update,
                channel=msg.chat_id,
                ts=msg.edit_message_id,
                text=mrkdwn,
            )
            logger.debug(f"Edited Slack message {msg.edit_message_id} in {msg.chat_id}")
            return True

        except Exception as e:
            logger.warning(f"Edit failed, sending as new message: {e}")
            await self.send(msg)
            return False

    async def _on_app_mention(self, event: dict, team_id: str | None) -> None:
        """Handle app mentions (@nanobot) in channels."""
        user_id = event.get("user")
        channel_id = event.get("channel")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")
        ts = event.get("ts")

        logger.info(f"app_mention: user_id={user_id}, channel_id={channel_id}, text={text[:100]}")

        if not user_id or not channel_id:
            logger.warning("Missing user_id or channel_id in app_mention")
            return

        # Remove bot mention from text
        clean_text = self._remove_bot_mention(text)
        logger.info(f"Clean text after removing mention: '{clean_text}'")

        if not clean_text.strip():
            logger.info("Empty text after removing mention, ignoring")
            return

        # Cache user info
        await self._cache_user_info(user_id)

        # Get user identifier for allowlist
        sender_id = self._get_sender_id(user_id)

        logger.info(f"Forwarding to message bus: sender_id={sender_id}")

        # Forward to message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=clean_text,
            media=None,
            metadata={
                "team_id": team_id,
                "thread_ts": thread_ts or ts,
                "message_type": "app_mention",
            }
        )

    async def _on_message(self, event: dict, team_id: str | None) -> None:
        """Handle direct messages."""
        user_id = event.get("user")
        channel_id = event.get("channel")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")
        ts = event.get("ts")
        subtype = event.get("subtype")

        logger.info(f"message event: user_id={user_id}, channel_id={channel_id}, subtype={subtype}, text={text[:100] if text else 'none'}")

        # Skip messages without text
        # Skip bot messages
        if subtype or not user_id or not channel_id:
            logger.info(f"Skipping message: subtype={subtype}, user_id={user_id}, channel_id={channel_id}")
            return

        # Only process DMs (channels starting with D)
        if not channel_id.startswith("D"):
            logger.info(f"Skipping non-DM channel: {channel_id}")
            return

        # Cache user info
        await self._cache_user_info(user_id)

        # Get user identifier for allowlist
        sender_id = self._get_sender_id(user_id)

        logger.info(f"Slack DM from {sender_id}: {text[:50]}...")

        # Forward to message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=text,
            media=None,
            metadata={
                "team_id": team_id,
                "thread_ts": thread_ts or ts,
                "message_type": "dm",
            }
        )

    def _remove_bot_mention(self, text: str) -> str:
        """Remove bot mention from message text."""
        if not self._bot_user_id:
            return text

        # Remove <@U123456> mentions of our bot
        pattern = rf"<@{re.escape(self._bot_user_id)}>\s*"
        return re.sub(pattern, "", text)

    async def _cache_user_info(self, user_id: str) -> None:
        """Cache user information for allowlist lookups."""
        if user_id in self._user_ids:
            return

        try:
            response = await asyncio.to_thread(
                self._web_client.users_info,
                user=user_id
            )
            user = response.get("user", {})
            name = user.get("name", "")
            if name:
                self._user_ids[user_id] = name
        except Exception as e:
            logger.debug(f"Failed to get user info for {user_id}: {e}")

    def _get_sender_id(self, user_id: str) -> str:
        """Get sender identifier (user_id|username format if available)."""
        if user_id in self._user_ids:
            return f"{user_id}|{self._user_ids[user_id]}"
        return user_id

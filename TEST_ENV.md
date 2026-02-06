# Test Environment Setup

## Quick Start

```bash
# 1. Create your test config
cp config-test.json.example config-test.json
# Edit config-test.json with your Slack tokens and API keys

# 2. Start the test environment
docker compose up -d

# 3. View logs
docker compose logs -f

# 4. Restart (when needed)
docker compose restart

# 5. Stop
docker compose down
```

## Ports

| Service | Host Port | Container Port |
|---------|-----------|----------------|
| Test Environment | 18791 | 18790 |

## File Structure

```
.
├── docker-compose.yml          # Test environment definition
├── config-test.json            # Your test config (create from example)
├── workspace-test/             # Persistent workspace data (auto-created)
└── nanobot/skills/             # Mounted read-only for live updates
```

## Tips

1. **Live reload skills**: Changes to `nanobot/skills/` don't require rebuild - just restart
2. **Config changes**: Edit `config-test.json` and restart
3. **Full rebuild**: `docker compose up -d --build`

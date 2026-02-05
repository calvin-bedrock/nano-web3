# nanobot Skills

This directory contains built-in skills that extend nanobot's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

### Core Skills

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `weather` | Get weather info using wttr.in and Open-Meteo |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `skill-creator` | Create new skills |
| `cron` | Manage scheduled tasks |

### Web3 Skills

| Skill | Description | Requirements |
|-------|-------------|--------------|
| `web3-core` | Core Web3 knowledge (wallets, tokens, APIs) - Always loaded | None |
| `wallet-tracker` | Track and analyze Ethereum wallets | `ETHERSCAN_API_KEY` |
| `token-analyzer` | Analyze ERC20 tokens (price, liquidity, risks) | None |
| `whale-monitor` | Monitor whale movements and smart money | None |
| `defi-analyzer` | Analyze DeFi protocols, TVL, and yields | None |

### Meta Skills

| Skill | Description | Requirements |
|-------|-------------|--------------|
| `skill-researcher` | Auto-research and propose new skills when facing unknown tasks - Always loaded | `BRAVE_API_KEY` for web search |

## Web3 Knowledge Base

Located in `workspace/web3-knowledge/`:
- `wallets.json` - Known wallet addresses (KOLs, exchanges, VCs, whales)
- `tokens.json` - Token contracts by chain
- `protocols.json` - DeFi protocol contracts and info

## Adding New Skills

1. Create a new directory under `skills/`
2. Add a `SKILL.md` file with proper frontmatter
3. Document usage patterns and examples

Example frontmatter:
```yaml
---
name: my-skill
description: "Brief description of what this skill does"
metadata: {"nanobot":{"emoji":"🔧","requires":{"env":["API_KEY"],"bins":["curl"]}}}
---
```

## Skill Metadata

The `metadata` field supports:
- `emoji` - Display emoji for the skill
- `always` - If true, skill is always loaded
- `requires.env` - Required environment variables
- `requires.bins` - Required command-line tools

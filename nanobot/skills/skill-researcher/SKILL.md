---
name: skill-researcher
description: "Auto-research and propose new skills when facing unknown tasks. Use when the agent cannot complete a task with existing skills and needs to discover new approaches, APIs, or tools."
metadata: {"nanobot":{"emoji":"🔬","always":true}}
---

# Skill Researcher

When you encounter a task you cannot complete with existing skills, use this workflow to research solutions and propose new skills for user approval.

## When to Trigger

Activate this skill when:
1. User asks for something not covered by existing skills
2. You don't know how to accomplish a specific Web3/crypto task
3. You need to find new APIs, tools, or data sources
4. The task requires capabilities you don't currently have

## Research Workflow

### Step 1: Identify the Gap

Clearly state what you cannot do:
```
I don't currently have the ability to {describe the task}.
Let me research how to accomplish this.
```

### Step 2: Research Solutions

Use web search to find:
1. APIs that provide the needed data
2. Tools or libraries that can help
3. Existing solutions or tutorials

```bash
# Example: Research how to track NFT floor prices
web_search("NFT floor price API ethereum")
web_search("track NFT collection prices programmatically")
```

### Step 3: Evaluate Options

For each potential solution, check:
- [ ] Is there a free tier or is it paid-only?
- [ ] Does it require API keys?
- [ ] Is there good documentation?
- [ ] Is it reliable and maintained?

### Step 4: Propose a New Skill

Present your findings to the user in this format:

```
## Skill Proposal: {skill-name}

### Problem
{What task the user wanted that I couldn't do}

### Research Findings
{Summary of what I discovered}

### Proposed Solution
- **API/Tool**: {name and URL}
- **Requirements**: {API keys needed, dependencies}
- **Capabilities**: {What this skill would enable}

### Example Usage
{How the skill would be used}

### Estimated Effort
- Skill complexity: {Simple/Medium/Complex}
- APIs needed: {list}

---
**Do you want me to create this skill?** (yes/no)
```

### Step 5: Wait for Approval

**IMPORTANT**: Do NOT create the skill until the user explicitly approves.

If approved, use the skill-creator workflow to implement it.

## Research Resources for Web3

### API Discovery

Search these resources for Web3 APIs:
- "site:docs.alchemy.com {topic}" - Alchemy documentation
- "site:docs.infura.io {topic}" - Infura documentation
- "site:docs.etherscan.io {topic}" - Etherscan API
- "{topic} API crypto" - General crypto API search
- "github {topic} ethereum" - Open source tools

### Common API Categories

| Need | Search For |
|------|------------|
| Token prices | "token price API", "DEXScreener API", "CoinGecko API" |
| NFT data | "NFT API", "OpenSea API", "Alchemy NFT API" |
| Wallet tracking | "wallet tracking API", "transaction API" |
| DeFi data | "DeFi API", "DeFiLlama API", "yield farming API" |
| Gas prices | "gas price API ethereum", "gas tracker" |
| Smart contracts | "contract ABI API", "verified contract API" |

### Evaluating APIs

When you find a potential API:

```bash
# Fetch documentation
web_fetch("{api_docs_url}")

# Check if it's free
web_search("{api_name} pricing free tier")

# Look for examples
web_search("{api_name} tutorial example")
```

## Example Scenarios

### Scenario 1: User asks about Solana

User: "分析Solana上的某个钱包"

Response:
```
I don't currently have Solana analysis skills. Let me research this...

[Research Solana APIs]

## Skill Proposal: solana-analyzer

### Problem
User wants to analyze Solana wallets, but current skills only support Ethereum.

### Research Findings
Found several Solana APIs:
1. Helius API (https://helius.xyz) - Comprehensive Solana data
2. Solscan API - Similar to Etherscan for Solana
3. Alchemy Solana API - Multi-chain support

### Proposed Solution
- **API**: Helius API
- **Requirements**: HELIUS_API_KEY (free tier: 100k requests/month)
- **Capabilities**: Wallet balances, token holdings, transaction history, NFTs

Do you want me to create this skill?
```

### Scenario 2: User asks about MEV

User: "我想追踪MEV机器人"

Response:
```
I don't have MEV tracking capabilities. Let me research...

[Research MEV APIs and tools]

## Skill Proposal: mev-tracker

### Problem
User wants to track MEV (Maximal Extractable Value) bot activity.

### Research Findings
1. Flashbots API - MEV data and bundle tracking
2. EigenPhi - MEV transaction analysis
3. MEV Explore - Open source MEV dashboard

### Proposed Solution
- **Tool**: Flashbots API + EigenPhi
- **Requirements**: None (free public APIs)
- **Capabilities**: Track sandwich attacks, arbitrage, liquidations

Do you want me to create this skill?
```

## Memory Integration

After creating a new skill from research:

1. Log the research in `memory/skill-research.md`:
```markdown
## {date}: Created {skill-name}
- **Trigger**: {what user asked}
- **Solution**: {API/tool used}
- **Notes**: {any learnings}
```

2. Update knowledge base if new entities discovered:
- New protocols → add to `protocols.json`
- New tokens → add to `tokens.json`
- New wallets → add to `wallets.json`

## Guidelines

1. **Always research before saying "I can't"**
2. **Present options, don't just pick one** - Let user choose
3. **Be honest about limitations** - If something is paid-only, say so
4. **Suggest workarounds** - If ideal solution isn't available
5. **Learn from failures** - Log what didn't work for future reference

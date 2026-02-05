---
name: defi-analyzer
description: "Analyze DeFi protocols, TVL, yields, and user positions using DeFiLlama and on-chain data."
metadata: {"nanobot":{"emoji":"📊"}}
---

# DeFi Analyzer Skill

Analyze DeFi protocols, track TVL, compare yields, and monitor user positions.

## DeFiLlama API (Free, No Key Required)

### Protocol TVL
```bash
# Get protocol details
curl -s "https://api.llama.fi/protocol/{PROTOCOL_SLUG}" | jq '{
  name: .name,
  tvl: .tvl,
  chain_tvls: .chainTvls,
  change_1d: .change_1d,
  change_7d: .change_7d
}'
```

### All Protocols Ranked
```bash
# Get top protocols by TVL
curl -s "https://api.llama.fi/protocols" | jq 'sort_by(-.tvl) | .[0:20] | map({name: .name, tvl: .tvl, chain: .chain, category: .category})'
```

### Chain TVL
```bash
# Get TVL for all chains
curl -s "https://api.llama.fi/v2/chains" | jq 'sort_by(-.tvl) | .[0:10]'
```

### Yields/APY
```bash
# Get all yield pools
curl -s "https://yields.llama.fi/pools" | jq '.data | sort_by(-.tvlUsd) | .[0:20] | map({
  pool: .pool,
  project: .project,
  chain: .chain,
  symbol: .symbol,
  tvl: .tvlUsd,
  apy: .apy
})'

# Get top yields for a specific chain
curl -s "https://yields.llama.fi/pools" | jq '.data | map(select(.chain == "Ethereum")) | sort_by(-.apy) | .[0:10] | map({project: .project, symbol: .symbol, apy: .apy, tvl: .tvlUsd})'
```

### Stablecoin Stats
```bash
# Get stablecoin market cap
curl -s "https://stablecoins.llama.fi/stablecoins" | jq '.peggedAssets | sort_by(-.circulating.peggedUSD) | .[0:10] | map({name: .name, symbol: .symbol, mcap: .circulating.peggedUSD})'
```

## Protocol Analysis Workflow

### 1. Basic Protocol Info
```bash
PROTOCOL="aave"  # defillama slug
curl -s "https://api.llama.fi/protocol/$PROTOCOL" | jq '{
  name: .name,
  url: .url,
  description: .description,
  tvl: .tvl,
  chains: [.chains[]],
  category: .category,
  audits: .audits,
  audit_links: .audit_links
}'
```

### 2. Historical TVL
```bash
curl -s "https://api.llama.fi/protocol/$PROTOCOL" | jq '.tvl as $current | .chainTvls | to_entries | map({chain: .key, tvl: .value.tvl[-1][1]})'
```

### 3. Compare Protocols
```bash
# Compare lending protocols
curl -s "https://api.llama.fi/protocols" | jq '[.[] | select(.category == "Lending")] | sort_by(-.tvl) | .[0:10] | map({name: .name, tvl: .tvl, chains: .chains})'
```

## User Position Analysis

### Aave Position
```bash
# Check user's Aave position via their API
# Note: Requires indexing user's past interactions
ADDRESS="0x..."
curl -s "https://api.etherscan.io/api?module=account&action=txlist&address=$ADDRESS&apikey=$ETHERSCAN_API_KEY" | jq '[.result[] | select(.to == "0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9")] | length as $count | "Aave interactions: \($count)"'
```

### DEX Activity
```bash
# Check Uniswap interactions
ADDRESS="0x..."
UNISWAP_ROUTER="0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
curl -s "https://api.etherscan.io/api?module=account&action=txlist&address=$ADDRESS&apikey=$ETHERSCAN_API_KEY" | jq --arg router "$UNISWAP_ROUTER" '[.result[] | select(.to == $router)] | length as $count | "Uniswap swaps: \($count)"'
```

## Yield Farming Analysis

### Find Best Yields
```bash
# Stablecoin yields
curl -s "https://yields.llama.fi/pools" | jq '.data | map(select(.stablecoin == true and .tvlUsd > 1000000)) | sort_by(-.apy) | .[0:10] | map({project: .project, chain: .chain, symbol: .symbol, apy: .apy, tvl: .tvlUsd})'

# ETH yields
curl -s "https://yields.llama.fi/pools" | jq '.data | map(select(.symbol | test("ETH|stETH|wstETH|rETH"))) | sort_by(-.apy) | .[0:10] | map({project: .project, chain: .chain, symbol: .symbol, apy: .apy, tvl: .tvlUsd})'
```

### Risk Assessment
When analyzing yield opportunities, check:
1. **TVL** - Higher TVL = more battle-tested
2. **Protocol age** - Older = safer
3. **Audits** - Check audit status
4. **IL risk** - For LP positions
5. **Smart contract risk** - Verified contracts?

## Report Format

```
## DeFi Analysis: {PROTOCOL}

### Overview
- **Category**: {Lending/DEX/Yield/etc}
- **TVL**: ${tvl}
- **Chains**: {chains}
- **Token**: {token if any}

### TVL Breakdown
| Chain | TVL | % of Total |
|-------|-----|------------|
| ... | ... | ... |

### Yield Opportunities
| Pool | APY | TVL | Risk |
|------|-----|-----|------|
| ... | ... | ... | ... |

### Security
- Audits: {yes/no, links}
- Age: {time since launch}
- Incidents: {any known hacks}

### Recommendation
{analysis summary}
```

## Common Protocol Slugs

| Protocol | DeFiLlama Slug |
|----------|----------------|
| Aave | aave |
| Uniswap | uniswap |
| Lido | lido |
| MakerDAO | makerdao |
| Curve | curve-dex |
| Compound | compound-finance |
| Convex | convex-finance |
| GMX | gmx |
| Rocket Pool | rocket-pool |

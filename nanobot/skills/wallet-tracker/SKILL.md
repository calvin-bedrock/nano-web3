---
name: wallet-tracker
description: "Track and analyze Ethereum wallet activity including token holdings, transactions, and net worth estimation."
metadata: {"nanobot":{"emoji":"👛","requires":{"env":["ETHERSCAN_API_KEY"]}}}
---

# Wallet Tracker Skill

Analyze Ethereum wallets to understand holdings, activity patterns, and net worth.

## Analysis Components

### 1. ETH Balance
```bash
curl -s "https://api.etherscan.io/api?module=account&action=balance&address={ADDRESS}&apikey=$ETHERSCAN_API_KEY" | jq -r '.result' | awk '{printf "%.4f ETH\n", $1/1e18}'
```

### 2. Token Holdings (ERC20)
```bash
# Get token transfer history
curl -s "https://api.etherscan.io/api?module=account&action=tokentx&address={ADDRESS}&page=1&offset=100&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '.result'
```

### 3. Recent Transactions
```bash
# Get last 20 transactions
curl -s "https://api.etherscan.io/api?module=account&action=txlist&address={ADDRESS}&page=1&offset=20&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '.result[] | {hash: .hash, from: .from, to: .to, value: (.value | tonumber / 1e18), timestamp: (.timeStamp | tonumber | strftime("%Y-%m-%d %H:%M"))}'
```

### 4. NFT Holdings (ERC721)
```bash
curl -s "https://api.etherscan.io/api?module=account&action=tokennfttx&address={ADDRESS}&page=1&offset=50&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '.result'
```

### 5. Internal Transactions
```bash
curl -s "https://api.etherscan.io/api?module=account&action=txlistinternal&address={ADDRESS}&page=1&offset=20&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '.result'
```

## Analysis Report Format

When presenting wallet analysis, use this format:

```
## Wallet Analysis: {ADDRESS}
**Alias**: {if known}

### Summary
- ETH Balance: X.XX ETH (~$X,XXX)
- Token Holdings: X unique tokens
- Recent Activity: X transactions in last 7 days

### Top Token Holdings
| Token | Balance | Value (USD) |
|-------|---------|-------------|
| ... | ... | ... |

### Recent Transactions
| Time | Type | Amount | To/From |
|------|------|--------|---------|
| ... | ... | ... | ... |

### Activity Pattern
- Most active: {day/time}
- Frequent interactions: {protocols/addresses}
```

## Price Lookup

Get current token prices using DeFiLlama:
```bash
# Get ETH price
curl -s "https://coins.llama.fi/prices/current/coingecko:ethereum" | jq '.coins["coingecko:ethereum"].price'

# Get token price by contract
curl -s "https://coins.llama.fi/prices/current/ethereum:{TOKEN_ADDRESS}" | jq '.coins'
```

## Multi-chain Support

For other chains, use chain-specific APIs:
- **Polygon**: `https://api.polygonscan.com/api` (requires POLYGONSCAN_API_KEY)
- **BSC**: `https://api.bscscan.com/api` (requires BSCSCAN_API_KEY)
- **Arbitrum**: `https://api.arbiscan.io/api` (requires ARBISCAN_API_KEY)

The API structure is identical to Etherscan.

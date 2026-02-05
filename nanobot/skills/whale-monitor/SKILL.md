---
name: whale-monitor
description: "Monitor whale wallet movements, large transactions, and smart money flows on Ethereum."
metadata: {"nanobot":{"emoji":"🐋"}}
---

# Whale Monitor Skill

Track large wallet movements, smart money flows, and significant on-chain activity.

## Known Whale Wallets

### Exchanges
| Name | Address | Type |
|------|---------|------|
| Binance | 0x28C6c06298d514Db089934071355E5743bf21d60 | CEX |
| Coinbase | 0x71660c4005BA85c37ccec55d0C4493E66Fe775d3 | CEX |
| Kraken | 0x2910543Af39abA0Cd09dBb2D50200b3E800A63D2 | CEX |

### Market Makers
| Name | Address | Type |
|------|---------|------|
| Wintermute | 0x0000006daea1723962647b7e189d311d757Fb793 | MM |
| Jump Trading | 0x9507c04B10486547584C37bCBd931B2a4FeE9A41 | MM |
| Alameda (defunct) | 0x84D34f4f83a87596Cd3FB6887cFf8F17Bf5A7B83 | MM |

### VCs & Funds
| Name | Address | Type |
|------|---------|------|
| a16z | 0x05E793cE0C6027323Ac150F6d45C2344d28B6019 | VC |
| Paradigm | 0xD2a79301B97DA836634a7FC5f5B1F8E3af3C9892 | VC |
| Three Arrows (defunct) | 0x3BA21b6477F48273f41d241AA3722FFb9E07E247 | VC |

### Notable Individuals
| Name | Address | Notes |
|------|---------|-------|
| 麻吉 / Machi | 0x020ca66c30bec2c4fe3861a94e4db4a498a35872 | NFT Whale |
| Justin Sun | 0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296 | Tron Founder |
| Vitalik | 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 | ETH Co-founder |

## Monitoring Techniques

### 1. Recent Large Transactions
```bash
# Get recent transactions for a whale
curl -s "https://api.etherscan.io/api?module=account&action=txlist&address={WHALE_ADDRESS}&page=1&offset=50&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '[.result[] | select((.value | tonumber) > 1000000000000000000)] | map({
  hash: .hash,
  to: .to,
  value_eth: ((.value | tonumber) / 1e18),
  time: (.timeStamp | tonumber | strftime("%Y-%m-%d %H:%M"))
})'
```

### 2. Token Movement Alerts
```bash
# Check for large token transfers
curl -s "https://api.etherscan.io/api?module=account&action=tokentx&address={WHALE_ADDRESS}&page=1&offset=50&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '.result[:20] | map({
  token: .tokenSymbol,
  from: .from,
  to: .to,
  amount: ((.value | tonumber) / pow(10; (.tokenDecimal | tonumber))),
  time: (.timeStamp | tonumber | strftime("%Y-%m-%d %H:%M"))
})'
```

### 3. Exchange Flow Detection
```bash
# Detect deposits to exchanges (potential sell signal)
EXCHANGES="0x28C6c06298d514Db089934071355E5743bf21d60|0x71660c4005BA85c37ccec55d0C4493E66Fe775d3"
curl -s "https://api.etherscan.io/api?module=account&action=txlist&address={WHALE_ADDRESS}&page=1&offset=100&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq --arg ex "$EXCHANGES" '[.result[] | select(.to | test($ex; "i"))] | map({to: .to, value_eth: ((.value | tonumber) / 1e18), time: (.timeStamp | tonumber | strftime("%Y-%m-%d %H:%M"))})'
```

### 4. DeFi Protocol Interactions
```bash
# Check interactions with known DeFi contracts
# Uniswap Router: 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D
# Aave: 0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9
curl -s "https://api.etherscan.io/api?module=account&action=txlist&address={WHALE_ADDRESS}&page=1&offset=100&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '[.result[] | select(.to == "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D" or .to == "0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9")]'
```

## Smart Money Tracking

### Copy Trade Analysis
```bash
# Get tokens a whale recently bought
curl -s "https://api.etherscan.io/api?module=account&action=tokentx&address={WHALE_ADDRESS}&page=1&offset=100&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '[.result[] | select(.to == "{WHALE_ADDRESS}")] | group_by(.tokenSymbol) | map({token: .[0].tokenSymbol, contract: .[0].contractAddress, buys: length}) | sort_by(-.buys)[:10]'
```

### Profit/Loss Tracking
For each token:
1. Get all buy transactions (token in)
2. Get all sell transactions (token out)
3. Calculate average buy/sell price
4. Compare with current price

## Alert Thresholds

| Activity | Threshold | Significance |
|----------|-----------|--------------|
| ETH transfer | >100 ETH | Notable |
| ETH transfer | >1000 ETH | Major |
| Token transfer | >$100K | Notable |
| Token transfer | >$1M | Major |
| Exchange deposit | Any | Potential sell |
| Exchange withdrawal | Any | Accumulation |

## Report Format

```
## Whale Activity Report: {NAME}
**Address**: {address}

### 24h Summary
- Total ETH moved: {amount}
- Tokens transferred: {count}
- DEX trades: {count}
- Exchange interactions: {count}

### Notable Transactions
| Time | Type | Asset | Amount | Destination |
|------|------|-------|--------|-------------|
| ... | ... | ... | ... | ... |

### Token Movements
| Token | Action | Amount | Value |
|-------|--------|--------|-------|
| ... | ... | ... | ... |

### Interpretation
{What this activity might indicate}
```

## Continuous Monitoring

To set up continuous whale monitoring:
1. Create a heartbeat task in HEARTBEAT.md
2. Check specified wallets every 30 minutes
3. Alert on significant movements

Example heartbeat task:
```
- [ ] Check whale wallets (Machi, Justin Sun) for large movements >$100K
```

---
name: token-analyzer
description: "Analyze ERC20 tokens including price, liquidity, holders, and trading activity using DEXScreener and Etherscan."
metadata: {"nanobot":{"emoji":"🪙"}}
---

# Token Analyzer Skill

Comprehensive ERC20 token analysis including price action, liquidity, holders, and risk assessment.

## Quick Token Lookup

### DEXScreener (Best for trading data)
```bash
# Get token info by address
curl -s "https://api.dexscreener.com/latest/dex/tokens/{TOKEN_ADDRESS}" | jq '.pairs[0] | {
  name: .baseToken.name,
  symbol: .baseToken.symbol,
  price: .priceUsd,
  priceChange24h: .priceChange.h24,
  volume24h: .volume.h24,
  liquidity: .liquidity.usd,
  fdv: .fdv,
  pairAddress: .pairAddress,
  dex: .dexId
}'
```

### CoinGecko (Best for market cap data)
```bash
# Get token by contract address
curl -s "https://api.coingecko.com/api/v3/coins/ethereum/contract/{TOKEN_ADDRESS}" | jq '{
  name: .name,
  symbol: .symbol,
  price: .market_data.current_price.usd,
  market_cap: .market_data.market_cap.usd,
  volume_24h: .market_data.total_volume.usd,
  price_change_24h: .market_data.price_change_percentage_24h
}'
```

## Detailed Analysis

### 1. Token Contract Info
```bash
# Get contract source (if verified)
curl -s "https://api.etherscan.io/api?module=contract&action=getsourcecode&address={TOKEN_ADDRESS}&apikey=$ETHERSCAN_API_KEY" | jq '.result[0] | {name: .ContractName, compiler: .CompilerVersion, verified: (.ABI != "Contract source code not verified")}'
```

### 2. Holder Distribution
```bash
# This requires Etherscan Pro or alternative APIs
# Use DEXScreener's holder data when available
curl -s "https://api.dexscreener.com/latest/dex/tokens/{TOKEN_ADDRESS}" | jq '.pairs[0].info'
```

### 3. Trading Pairs
```bash
# Get all trading pairs for a token
curl -s "https://api.dexscreener.com/latest/dex/tokens/{TOKEN_ADDRESS}" | jq '.pairs | map({dex: .dexId, pair: .pairAddress, quote: .quoteToken.symbol, liquidity: .liquidity.usd, volume24h: .volume.h24}) | sort_by(-.liquidity)'
```

### 4. Recent Trades
```bash
# Get recent token transfers
curl -s "https://api.etherscan.io/api?module=account&action=tokentx&contractaddress={TOKEN_ADDRESS}&page=1&offset=50&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '.result[:10] | map({from: .from, to: .to, value: (.value | tonumber / pow(10; .tokenDecimal | tonumber)), time: (.timeStamp | tonumber | strftime("%Y-%m-%d %H:%M"))})'
```

## Risk Assessment

When analyzing a token, check for:

### Red Flags
1. **Honeypot**: Can't sell after buying
2. **High tax**: >10% buy/sell tax
3. **Renounced ownership**: Check if owner is 0x0
4. **Low liquidity**: <$50K liquidity
5. **New contract**: <7 days old

### Safety Check Commands
```bash
# Check contract age
curl -s "https://api.etherscan.io/api?module=account&action=txlist&address={TOKEN_ADDRESS}&page=1&offset=1&sort=asc&apikey=$ETHERSCAN_API_KEY" | jq '.result[0].timeStamp | tonumber | strftime("Created: %Y-%m-%d")'

# Check if contract is verified
curl -s "https://api.etherscan.io/api?module=contract&action=getabi&address={TOKEN_ADDRESS}&apikey=$ETHERSCAN_API_KEY" | jq 'if .status == "1" then "Contract Verified ✓" else "Contract NOT Verified ⚠️" end'
```

## Analysis Report Format

```
## Token Analysis: {SYMBOL}

### Basic Info
- **Name**: {name}
- **Contract**: {address}
- **Chain**: Ethereum

### Market Data
- **Price**: ${price}
- **24h Change**: {change}%
- **Market Cap**: ${market_cap}
- **24h Volume**: ${volume}
- **Liquidity**: ${liquidity}

### Trading Pairs
| DEX | Pair | Liquidity | 24h Volume |
|-----|------|-----------|------------|
| ... | ... | ... | ... |

### Risk Assessment
- Contract Age: {age}
- Verified: {yes/no}
- Liquidity: {adequate/low}
- Holder Concentration: {info}

### Recommendation
{analysis summary}
```

## Common Tokens Quick Reference

| Token | Address | Type |
|-------|---------|------|
| PEPE | 0x6982508145454Ce325dDbE47a25d4ec3d2311933 | Meme |
| SHIB | 0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE | Meme |
| UNI | 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 | DeFi |
| LINK | 0x514910771AF9Ca656af840dff83E8264EcF986CA | Oracle |
| AAVE | 0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9 | DeFi |

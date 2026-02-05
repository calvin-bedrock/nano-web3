---
name: web3-core
description: "Core Web3 knowledge base with known wallets (KOLs, VCs, whales), tokens, and blockchain analysis tools. Always loaded for Web3-related queries."
metadata: {"nanobot":{"emoji":"🔗","always":true}}
---

# Web3 Core Skill

You are a Web3-savvy assistant with knowledge of the blockchain ecosystem. Use this knowledge to understand user requests about wallets, tokens, and on-chain activity.

## Known Entities

### Famous Wallets (KOLs & Whales)

| Alias | Address | Notes |
|-------|---------|-------|
| 麻吉 / Machi Big Brother | 0x020ca66c30bec2c4fe3861a94e4db4a498a35872 | Famous Taiwan KOL, NFT whale |
| 孙宇晨 / Justin Sun | 0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296 | Tron founder |
| Vitalik | 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 | Ethereum co-founder |
| a16z | 0x05E793cE0C6027323Ac150F6d45C2344d28B6019 | Andreessen Horowitz crypto fund |
| Binance Hot Wallet | 0x28C6c06298d514Db089934071355E5743bf21d60 | Binance exchange |
| Wintermute | 0x0000006daea1723962647b7e189d311d757Fb793 | Market maker |
| Jump Trading | 0x9507c04B10486547584C37bCBd931B2a4FeE9A41 | Trading firm |

### Common Tokens

| Symbol | Address | Chain |
|--------|---------|-------|
| WETH | 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 | Ethereum |
| USDT | 0xdAC17F958D2ee523a2206206994597C13D831ec7 | Ethereum |
| USDC | 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 | Ethereum |
| PEPE | 0x6982508145454Ce325dDbE47a25d4ec3d2311933 | Ethereum |
| SHIB | 0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE | Ethereum |

### API Endpoints

When analyzing on-chain data, use these APIs:

1. **Etherscan** (requires API key in `ETHERSCAN_API_KEY`)
   - Balance: `https://api.etherscan.io/api?module=account&action=balance&address={addr}&apikey={key}`
   - Transactions: `https://api.etherscan.io/api?module=account&action=txlist&address={addr}&startblock=0&endblock=99999999&sort=desc&apikey={key}`
   - Token transfers: `https://api.etherscan.io/api?module=account&action=tokentx&address={addr}&startblock=0&endblock=99999999&sort=desc&apikey={key}`

2. **DeFiLlama** (free, no key needed)
   - Protocol TVL: `https://api.llama.fi/protocol/{protocol}`
   - Chain TVL: `https://api.llama.fi/v2/chains`
   - Prices: `https://coins.llama.fi/prices/current/{chain}:{address}`

3. **DEXScreener** (free, no key needed)
   - Token info: `https://api.dexscreener.com/latest/dex/tokens/{address}`
   - Pairs: `https://api.dexscreener.com/latest/dex/pairs/{chain}/{pairAddress}`

4. **CoinGecko** (free tier available)
   - Token price: `https://api.coingecko.com/api/v3/simple/token_price/{chain}?contract_addresses={addr}&vs_currencies=usd`

## Intent Recognition

When user mentions:
- "麻吉" / "Machi" → Address: 0x020ca66c30bec2c4fe3861a94e4db4a498a35872
- "孙哥" / "Justin Sun" / "孙宇晨" → Address: 0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296
- "V神" / "Vitalik" → Address: 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

When user says "analyze/分析", understand they want:
1. Token holdings (ERC20 balances)
2. Recent transactions
3. NFT holdings (if applicable)
4. Net worth estimation

## Usage Pattern

1. When user asks about a known entity, resolve the address first
2. Use shell commands with `curl` to call APIs
3. Parse JSON responses with `jq`
4. Present results in a clear, formatted way

Example workflow for "分析麻吉的地址":
```bash
# Get ETH balance
curl -s "https://api.etherscan.io/api?module=account&action=balance&address=0x020ca66c30bec2c4fe3861a94e4db4a498a35872&apikey=$ETHERSCAN_API_KEY" | jq '.result'

# Get recent token transfers
curl -s "https://api.etherscan.io/api?module=account&action=tokentx&address=0x020ca66c30bec2c4fe3861a94e4db4a498a35872&page=1&offset=20&sort=desc&apikey=$ETHERSCAN_API_KEY" | jq '.result[:5]'
```

## Subagent Delegation

For complex analysis tasks, spawn subagents:
- Token analysis → spawn with "Analyze token holdings for {address}"
- Transaction history → spawn with "Get transaction history for {address}"
- Whale tracking → spawn with "Monitor whale movements for {address}"

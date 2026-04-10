# chain-trace

A CLI tool for forensic tracing of Bitcoin and Ethereum transactions. Designed for multi-address, multi-year investigations — with an AI agent co-pilot in mind.

## Features

- **BTC and ETH** — Bitcoin via mempool.space, Ethereum (native + ERC-20) via Etherscan
- **Smart classification** — transactions are classified as TRANSFER, RECEIVE, SWAP, WRAP/UNWRAP, LIQUIDITY, or CONTRACT, not raw event dumps
- **DEX swap detection** — recognises Uniswap, Sushiswap, Curve, 1inch, Balancer, CoW and more; shows net asset flows and multi-hop routes
- **Address labels** — name addresses locally; ~130 known addresses (exchanges, DEX routers, bridges, tokens, mixers) bundled
- **Traceability scoring** — every counterparty is scored: PERSONAL, CEX, DEX, BRIDGE, CONTRACT, HIGH_TRAFFIC, or UNKNOWN — so you know whether a trail is worth following
- **Investigation sessions** — group addresses into named sessions, mark dead ends (e.g. CEX hot wallets), view a unified cross-address timeline
- **Aggressive caching** — all historical API responses cached indefinitely in SQLite; subsequent queries are instant and offline
- **AI agent friendly** — every command has a `--json` flag with a consistent envelope format
- **USD values** — optional `--usd` flag fetches historical prices via CoinGecko

## Installation

```bash
git clone <repo>
cd chain-trace
pip install -e .
```

Requires Python 3.11+.

## Setup

### Etherscan API key (required for ETH)

Get a free key at [etherscan.io/register](https://etherscan.io/register), then:

```bash
trace config set etherscan_key YOUR_KEY
```

Bitcoin tracing works without any key.

### Chainbase API key (optional — enriches address labels)

Get a free key at [chainbase.com](https://chainbase.com), then:

```bash
trace config set chainbase_key YOUR_KEY
```

When set, any Ethereum address without a local or catalog label is automatically
looked up via the Chainbase Web3 Data API. Results are cached locally so
subsequent lookups are instant and offline. Labels are stored with
`source=chainbase` and are visible in `trace label list --source chainbase`.

## Usage

### Trace an address

Chain is auto-detected from the address format.

```bash
trace trace 0xABCD...                          # ETH
trace trace bc1q...                            # BTC
trace trace 0xABCD... --from 2021-01-01        # date filter
trace trace 0xABCD... --from 2020-01-01 --to 2023-12-31 --limit 200
trace trace 0xABCD... --usd                    # show USD value at time of tx
trace trace 0xABCD... --json                   # machine-readable output
trace trace 0xABCD... --token 0xA0b8...        # filter to one ERC-20 token
```

### Inspect a single transaction

Useful for multi-hop swaps or complex contract calls — shows all individual transfers.

```bash
trace tx 0xHASH...
trace tx 0xHASH... --json
```

### Label addresses

```bash
trace label add 0xABCD... "My cold wallet" --chain eth
trace label add 1BTC...   "Exchange deposit" --chain btc
trace label list
trace label list --chain eth --category exchange
trace label list --source chainbase           # labels fetched from Chainbase
trace label remove 0xABCD... --chain eth

# On-demand Chainbase lookup (requires chainbase_key to be configured)
trace label lookup 0xABCD...                  # check local DB then Chainbase
trace label lookup 0xABCD... --save           # persist result locally
trace label lookup 0xABCD... --json           # machine-readable
```

### Investigation sessions

Sessions let you group addresses, track which ones are dead ends, and view a unified timeline across all of them.

```bash
# Create a session
trace session new my-case --notes "Following funds from exploit"

# Add addresses
trace session add my-case 0xABCD... --chain eth
trace session add my-case bc1q...   --chain btc

# Mark a CEX as a dead end (suppressed from follow suggestions)
trace session dead-end my-case 0xBinance... --chain eth --reason "Binance hot wallet"

# Show session state
trace session show my-case

# Unified timeline across all active addresses
trace session timeline my-case --from 2021-01-01 --to 2023-12-31

# Export
trace session export my-case --format csv --output my-case.csv
trace session export my-case --format json --output my-case.json

# List all sessions
trace session list
```

### Configuration

```bash
trace config set etherscan_key YOUR_KEY
trace config set high_traffic_threshold 10000   # tx count above which = HIGH_TRAFFIC
trace config set dust_threshold_eth 0.0001      # min ETH amount shown
trace config set dust_threshold_btc 0.00001     # min BTC amount shown
trace config list
```

### Multiple investigations

Use `--db` to keep separate investigations in separate database files:

```bash
trace --db ~/cases/case-a.db session new case-a
trace --db ~/cases/case-a.db trace 0xABCD...
trace --db ~/cases/case-b.db session new case-b
```

## Output format

### Table (default)

```
Address  0x1234...abcd  (My Wallet)       Chain  ETH
Period   2020-01-01 → 2024-06-01          Showing 47 transactions

 TIMESTAMP            TYPE       DETAILS                               COUNTERPARTY          TX
 ──────────────────────────────────────────────────────────────────────────────────────────────
 2024-01-15 14:32    SWAP       1.000 ETH → 2,847.3 USDC             Uniswap V3            0x1a2b…
                                 hops: ETH → WETH → USDC
 2024-01-14 09:11    TRANSFER   out  500.0 USDC                       0xde0b… Binance 14    0x3c4d…
                                                                       [CEX — dead end]
 2024-01-12 18:05    RECEIVE    in   2.5 ETH                          0xabc1… Coinbase 1    0x5e6f…
 2024-01-10 22:15    WRAP       0.5 ETH → 0.5 WETH                                         0x7f80…
 2024-01-08 14:30    LIQUIDITY  add: 0.5 ETH + 1,200 USDC            Uniswap V2 Pool       0x91a2…
```

### JSON (`--json`)

All commands output a consistent envelope:

```json
{
  "meta": {
    "command": "trace",
    "address": "0x...",
    "chain": "eth",
    "filters": { "from": "2020-01-01", "to": null },
    "generated_at": "2026-04-10T12:00:00Z",
    "count": 47
  },
  "data": [
    {
      "tx_hash": "0x...",
      "timestamp": "2024-01-15T14:32:01Z",
      "kind": "SWAP",
      "net_flows": { "ETH": "-1.0", "USDC": "2847.3" },
      "dex_name": "Uniswap V3",
      "hops": ["ETH", "WETH", "USDC"],
      "counterparty": null,
      "counterparty_score": null
    }
  ]
}
```

## Transaction types

| Type | Description |
|------|-------------|
| `RECEIVE` | Inbound transfer of ETH or tokens |
| `TRANSFER` | Outbound single-asset transfer |
| `SWAP` | DEX exchange — shows net in/out and DEX name |
| `WRAP` | ETH → WETH |
| `UNWRAP` | WETH → ETH |
| `LIQUIDITY` | LP add or remove |
| `CONTRACT` | Unclassified multi-transfer — shows net flows |
| `SEND` | BTC outbound |

## Traceability scores

Every counterparty address is scored when displayed:

| Score | Meaning |
|-------|---------|
| `PERSONAL` | Low tx count — worth following |
| `CONTRACT` | Smart contract (not a DEX) |
| `DEX` | Known DEX router or pool |
| `BRIDGE` | Cross-chain bridge |
| `CEX` | Centralised exchange — trail ends here |
| `HIGH_TRAFFIC` | Unknown but very busy — likely a CEX |
| `UNKNOWN` | Insufficient data |

## Data and privacy

All data is stored locally in `~/.chain-trace/data.db` (SQLite). Nothing is sent anywhere except the blockchain APIs (Etherscan, mempool.space, CoinGecko). The database is your investigation artifact — back it up.

## APIs used

| Purpose | API | Key required |
|---------|-----|-------------|
| Bitcoin data | [mempool.space](https://mempool.space/docs/api) | No |
| Ethereum data | [Etherscan V2](https://docs.etherscan.io) | Yes (free) |
| Historical prices | [CoinGecko](https://www.coingecko.com/en/api) | No |
| Address labels | [Chainbase](https://docs.chainbase.com) | Yes (free) |

# 🚀 StockPilot

**AI-powered quantitative investment platform** — unified data, analysis, LLM agents, news monitoring, backtesting & auto-trading.

StockPilot combines the best of multiple open-source trading projects into a single cohesive platform.

## Features

| Module | Capability |
|--------|-----------|
| 📊 **Data Layer** | Unified access to AKShare (A-share), yfinance (US/HK), EastMoney, Alpha Vantage, Tushare |
| 📈 **Technical Analysis** | 30+ indicators (MACD, KDJ, RSI, BOLL…) + 61 K-line pattern recognition |
| 🤖 **LLM Agents** | Multi-agent system with analyst agents, bull/bear debate, and 12 investor personas (Buffett, Munger, Wood…) |
| 🧠 **ML Models** | Qlib integration for SOTA quantitative models |
| 📰 **News & Trends** | Real-time aggregation from 10+ platforms (Weibo, Douyin, Reddit, HN…) |
| 💰 **Trading Engine** | Event-driven trading with paper and live execution |
| 📉 **Backtesting** | Historical strategy backtesting with Sharpe, drawdown, win rate metrics |
| 🔔 **Notifications** | Telegram, DingTalk, Feishu, WeChat, Email alerts |
| 🔌 **MCP Server** | AI-native integration via Model Context Protocol |
| 🌐 **Web Dashboard** | FastAPI backend + interactive frontend |

## Quick Start

```bash
# Clone and install
cd stockpilot
pip install poetry
poetry install

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run the API server
poetry run stockpilot-api

# Run the CLI
poetry run stockpilot --help

# Run the MCP server (for AI integration)
poetry run stockpilot-mcp
```

## Architecture

```
Data Sources          Analysis            AI Agents            Output
─────────────        ──────────          ──────────          ──────────
AKShare    ─┐        TA Indicators       Fundamentals ─┐     Trading
yfinance   ─┤        K-line Patterns     Technicals   ─┤     Backtesting
EastMoney  ─┼─→ DataManager ─→ Analysis ─→ Sentiment  ─┼─→  Dashboard
AlphaVantage┤        ML Models           News Analyst ─┤     MCP Server
Tushare    ─┘        Signal Gen          Personas     ─┤     Notifications
                                         Debate       ─┤
News Platforms                           Risk Mgr     ─┤
─────────────                            Portfolio    ─┘
Weibo, Douyin
Reddit, HN, Zhihu
```

## Project Structure

```
stockpilot/
├── config/settings.yaml     # Master configuration
├── src/stockpilot/
│   ├── data/                # Data adapters + cache + models
│   ├── analysis/            # Technical indicators + patterns
│   ├── models/              # ML/Qlib integration
│   ├── agents/              # LLM agent system
│   │   ├── graph/           # LangGraph orchestration
│   │   ├── core/            # Analyst agents
│   │   └── personas/        # Investor personas
│   ├── news/                # News aggregation
│   ├── trading/             # Trade execution engine
│   ├── backtesting/         # Backtesting framework
│   ├── notifications/       # Alert channels
│   ├── mcp/                 # MCP server
│   └── api/                 # FastAPI web backend
└── tests/
```

## Origins

StockPilot unifies capabilities from:
- **[AKShare](https://github.com/akfamily/akshare)** — Financial data APIs
- **[Qlib](https://github.com/microsoft/qlib)** — ML quant platform
- **[TradingAgents](https://github.com/TradingAgents)** — Multi-agent trading
- **[AI Hedge Fund](https://github.com/virattt/ai-hedge-fund)** — Investor personas
- **[TrendRadar](https://github.com/TrendRadar)** — News monitoring

## License

MIT

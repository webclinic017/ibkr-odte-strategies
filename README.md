# ODTE IBKR Trading System

Automated trading system for executing 0DTE options and earnings straddle strategies using Interactive Brokers API.

## Overview

This system includes two main trading bots:

1. **ODTE Breakout Bot** - Trades 0-Day-To-Expiration (0DTE) options based on breakout signals
2. **Earnings Straddle Bot** - Executes straddle positions around company earnings announcements

Both bots are designed to work with smaller accounts (optimized for $5K) and include risk management capabilities.

## Features

- Fully automated connection to IBKR TWS or Gateway
- Configurable risk parameters (2-3% per trade)
- Support for both options and futures contracts
- Comprehensive market data handling with fallbacks
- Position management with automated stop-loss and take-profit
- ETF-focused for better liquidity and lower costs
- Support for micro contracts to enable smaller account sizes

## Requirements

- Python 3.8+
- Interactive Brokers account with TWS or IB Gateway
- TWS/Gateway API enabled
- ib_insync library
- yfinance library (for earnings data)

## Setup

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Configure settings in `config/odte_breakout_config.json` and `config/earnings_straddle_config.json`
4. Launch TWS or IB Gateway and ensure API connections are enabled

## Running the Bots

### ODTE Breakout Bot

```bash
python odte_ibkr_full_auto.py --paper-trading
```

### Earnings Straddle Bot

```bash
python straddle_earnings_bot.py --paper-trading
```

## Configuration

### ODTE Breakout Config

Key parameters:
- `tickers`: List of high-volatility stocks from S&P 500 and tech sector
- `max_capital`: Total capital to deploy (set to $5000)
- `risk_per_trade`: Amount to risk per trade (2-3% of account, $150)
- `max_daily_trades`: Maximum trades per day (default: 1)
- `use_fractional_shares`: Whether to use fractional shares for expensive stocks

### Earnings Straddle Config

Key parameters:
- `tickers_whitelist`: High-volatility stocks with active options chains
- `max_capital_per_trade`: Maximum capital per straddle (3% of account, $150)
- `min_iv_rank`: Minimum IV rank to consider (35%)
- `max_days_to_expiry`: Maximum days to expiration (5 days)
- `max_daily_trades`: Maximum trades per day (default: 1)
- `use_micro_options`: Use fractional position sizing for expensive options

## Risk Management

The system implements several risk-management features:
- Per-trade capital limits (2-3% of account)
- Daily trade limits
- Automated stop-loss and take-profit
- Position time limits
- Pre-market and after-hours handling
- Market data verification

## Original Framework

This project is built on a modular framework for developing, testing, and executing 0DTE trading strategies using Interactive Brokers API. The framework includes:

- **Modular architecture**: Extensible framework for multiple strategies
- **Concurrent execution**: Ability to run multiple strategies simultaneously
- **IBKR connection**: Simplified interface with Interactive Brokers API
- **Backtesting**: Strategy validation with historical data
- **Performance analysis**: Detailed metrics and visualizations

## Estructura del Proyecto

```
odte-ibkr-strats/
├── config/                   # Configuration files
├── src/
│   ├── backtesting/          # Backtesting engine
│   ├── core/                 # Core components
│   ├── strategies/           # Implemented strategies
│   └── utils/                # General utilities
├── odte_ibkr_full_auto.py    # ODTE Breakout standalone bot
├── straddle_earnings_bot.py  # Earnings Straddle standalone bot 
├── run_strategy.py           # Main script to run strategies
```

## License

This code is for educational and personal use only.

## Disclaimer

Trading involves significant risk of loss. This software is provided "as is" without warranty of any kind. The authors accept no responsibility for losses incurred through the use of this software.
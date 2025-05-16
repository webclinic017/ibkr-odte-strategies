# ODTE IBKR Trading System

Modular trading system for executing automated options strategies using Interactive Brokers API.

## Overview

This system implements multiple trading strategies through a unified framework:

1. **ODTE Breakout Strategy** - Trades 0-Day-To-Expiration (0DTE) options based on breakout signals
2. **Earnings Straddle Strategy** - Executes straddle positions around company earnings announcements

Both strategies are designed to work with smaller accounts and include comprehensive risk management capabilities.

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
2. Run the setup script (creates virtual environment and config files):
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```
   Or manually:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Configure your settings:
   - Edit `config/odte_breakout_config.json` for ODTE strategy
   - Edit `config/earnings_straddle_config.json` for earnings strategy
   - Add your API keys and adjust trading parameters
4. Launch TWS or IB Gateway and ensure API connections are enabled

## Running the Strategies

### Initialize Configuration

```bash
python run_strategy.py init
```

### Run a Single Strategy

```bash
# For ODTE Breakout
python run_strategy.py run odte_breakout

# For Earnings Straddle
python run_strategy.py run earnings_straddle
```

### Run All Strategies

```bash
python run_strategy.py run all
```

### Additional Commands

```bash
# Run backtesting
python run_strategy.py backtest odte_breakout -s 2024-01-01 -e 2024-12-31

# List active strategies
python run_strategy.py list

# Close positions
python run_strategy.py close all
python run_strategy.py close odte_breakout
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

## Architecture

The system follows a modular architecture that separates concerns:

- **Strategy Framework**: Base classes and interfaces for strategy implementation
- **Core Components**: Shared utilities for IBKR connection, market data, and options handling
- **Strategy Implementations**: Individual strategy logic separated from infrastructure
- **Unified Runner**: Single entry point for all strategies with common configuration

### Key Features

- **Concurrent Execution**: Run multiple strategies simultaneously
- **IBKR Integration**: Robust connection management with automatic reconnection
- **Risk Management**: Built-in position sizing and stop-loss management
- **Backtesting**: Historical data analysis for strategy validation
- **Flexible Configuration**: JSON-based configuration for easy parameter tuning

## Project Structure

```
odte-ibkr-strats/
├── config/                   # Strategy configuration files
├── data/                     # Trading data and logs
├── logs/                     # System logs
├── src/
│   ├── backtesting/          # Backtesting engine
│   ├── core/                 # Core infrastructure
│   │   ├── ibkr_connection.py   # IBKR API wrapper
│   │   ├── market_data.py       # Market data utilities
│   │   ├── options_utils.py     # Options calculations
│   │   └── strategy_base.py     # Base strategy class
│   ├── strategies/           # Strategy implementations
│   │   ├── odte_breakout.py     # ODTE breakout strategy
│   │   └── earnings_straddle.py # Earnings straddle strategy
│   └── utils/                # General utilities
├── run_strategy.py           # Main entry point
├── requirements.txt          # Python dependencies
└── setup.sh                  # Setup script
```

### Deprecated Files

The following standalone scripts are deprecated in favor of the modular architecture:
- `odte_ibkr_full_auto.py` - Use `run_strategy.py run odte_breakout` instead
- `straddle_earnings_bot.py` - Use `run_strategy.py run earnings_straddle` instead

## License

This code is for educational and personal use only.

## Disclaimer

Trading involves significant risk of loss. This software is provided "as is" without warranty of any kind. The authors accept no responsibility for losses incurred through the use of this software.
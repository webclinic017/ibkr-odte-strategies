#!/bin/bash

# ODTE IBKR Trading System Setup Script
echo "Setting up ODTE IBKR Trading System..."

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create directories if they don't exist
mkdir -p config
mkdir -p data/earnings/straddles
mkdir -p logs
mkdir -p cache

# Create config files if they don't exist
if [ ! -f "config/odte_breakout_config.json" ]; then
    cat > config/odte_breakout_config.json << EOL
{
  "tickers": [
    "SPY",
    "QQQ",
    "IWM",
    "XLF",
    "EEM",
    "XLE",
    "SQQQ",
    "TQQQ"
  ],
  "max_capital": 5000,
  "risk_per_trade": 150,
  "min_volume": 100,
  "min_open_interest": 250,
  "polygon_api_key": "",
  "ibkr_host": "127.0.0.1",
  "ibkr_port": 7497,
  "ibkr_client_id": 1,
  "orders_file": "data/odte_breakout_orders.json",
  "log_file": "data/odte_breakout_trades.csv",
  "scan_interval": 30,
  "volume_multiplier": 0.7,
  "tp_multiplier": 1.5,
  "sl_multiplier": 0.7,
  "max_daily_trades": 3,
  "min_score": 40,
  "use_micros": true
}
EOL
    echo "Created default ODTE breakout config"
fi

if [ ! -f "config/earnings_straddle_config.json" ]; then
    cat > config/earnings_straddle_config.json << EOL
{
  "tickers_whitelist": [
    "SPY",
    "QQQ",
    "IWM",
    "XLF",
    "EEM",
    "XLE"
  ],
  "max_capital_per_trade": 150,
  "polygon_api_key": "",
  "ibkr_host": "127.0.0.1",
  "ibkr_port": 7497,
  "ibkr_client_id": 2,
  "data_dir": "data/earnings",
  "scan_interval": 1800,
  "auto_close_time": "14:35",
  "entry_days_before": 1,
  "exit_days_after": 1,
  "min_iv_rank": 30,
  "max_days_to_expiry": 5,
  "use_simulation": true,
  "max_daily_trades": 2,
  "same_day_entry": true,
  "extended_hours": true,
  "use_micro_options": true,
  "min_price": 10,
  "max_price": 500
}
EOL
    echo "Created default earnings straddle config"
fi

echo "Setup complete! Make sure to:"
echo "1. Add your API keys to the config files"
echo "2. Verify that TWS or IB Gateway is running with API enabled"
echo "3. Run strategies with one of these commands:"
echo "   - python run_strategy.py init            # Initialize config files"
echo "   - python run_strategy.py run odte_breakout    # Run ODTE strategy"
echo "   - python run_strategy.py run earnings_straddle # Run earnings strategy"
echo "   - python run_strategy.py run all         # Run all strategies"
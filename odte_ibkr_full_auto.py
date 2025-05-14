#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ODTE IBKR Full Auto Trading Bot
-------------------------------
Automated trading system that identifies and executes 0DTE options trades
using Interactive Brokers API.

This script automatically:
1. Connects to IBKR TWS or IB Gateway
2. Loads configuration from config files
3. Monitors market for trading opportunities
4. Executes trades based on configured parameters
5. Manages positions including stops and take profits
6. Logs all activities for analysis

Requirements:
- Interactive Brokers account with TWS or IB Gateway running
- ib_insync library
- Account permissions for options trading
"""

import os
import sys
import json
import time
import logging
import datetime
import argparse
import pytz
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
from functools import lru_cache

# Try to import ib_insync, provide helpful error if not installed
try:
    from ib_insync import IB, Contract, Stock, Future, Option
    from ib_insync import MarketOrder, LimitOrder, StopOrder
    from ib_insync import util
except ImportError:
    print("Error: ib_insync package not found. Install with: pip install ib_insync")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("odte_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ODTE-BOT")

# Default configuration path
DEFAULT_CONFIG_PATH = os.path.join("config", "odte_breakout_config.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7496  # TWS live trading port (use 7497 for TWS paper, 4001 for Gateway live, 4002 for Gateway paper)
DEFAULT_CLIENT_ID = 1

class ODTEBreakoutTrader:
    """Main class for the 0DTE breakout trading strategy."""
    
    def __init__(self, config_path: str, host: str, port: int, client_id: int):
        self.config_path = config_path
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self.config = {}
        self.open_positions = {}
        self.account_info = {}
        self.market_data = {}
        self.last_trade_time = {}
        self.tickers_without_0dte = set()  # Keep track of tickers without 0DTE options
        self.tickers_checked_today = set()  # Keep track of tickers already checked today
        self.earnings_checked_date = None  # Last date we checked earnings calendar
        self.eastern_tz = pytz.timezone('US/Eastern')
        self.allow_non_0dte = False  # Default to strict 0DTE only
        self.skip_notification = False  # Whether to skip notifications
        
    def send_notification(self, title, message):
        """Send a Mac OS notification."""
        try:
            if sys.platform != 'darwin' or self.skip_notification:
                return
                
            # Use osascript to send notification on Mac
            cmd = ['osascript', '-e', f'display notification "{message}" with title "{title}"']
            subprocess.run(cmd, capture_output=True)
            logger.info(f"Notification sent: {title} - {message}")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
        
        # Load configuration
        self.load_config()
        
    def load_config(self):
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            sys.exit(1)
            
        # Validate required configuration parameters
        required_params = [
            "tickers", "max_capital", "risk_per_trade", "min_volume",
            "min_open_interest", "max_daily_trades"
        ]
        
        for param in required_params:
            if param not in self.config:
                logger.error(f"Missing required configuration parameter: {param}")
                sys.exit(1)
                
        logger.info("Configuration validation successful")
    
    def connect(self):
        """Connect to Interactive Brokers TWS/Gateway."""
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            logger.info(f"Connected to IB on {self.host}:{self.port} with client ID {self.client_id}")
            
            # Verify connection is established
            if not self.ib.isConnected():
                logger.error("Failed to connect to TWS/IB Gateway")
                sys.exit(1)
                
            # Get account information
            self.account_info = self.ib.accountSummary()
            logger.info(f"Connected to account: {self.ib.client.getClient().accountName()}")
            
            # Subscribe to account updates
            self.ib.accountUpdateEvent += self.on_account_update
            
        except Exception as e:
            logger.error(f"Error connecting to IB: {e}")
            sys.exit(1)
    
    def on_account_update(self, account, tag, value, currency):
        """Handle account update events."""
        logger.debug(f"Account update: {account} - {tag}: {value} {currency}")
        # Update account information as needed
    
    @lru_cache(maxsize=32)
    def get_option_chains(self, ticker: str) -> List[Option]:
        """Get option chains for a ticker with 0 days to expiration.
        
        This method is cached to reduce API calls to IBKR.
        """
        try:
            # Create cache directory if it doesn't exist
            cache_dir = "cache"
            os.makedirs(cache_dir, exist_ok=True)
            
            # Check for cached option chain data
            cache_file = os.path.join(cache_dir, f"{ticker}_options_cache.json")
            cache_max_age_hours = 1  # Only cache for 1 hour for 0DTE options
            
            use_cache = False
            if os.path.exists(cache_file):
                # Check if cache is still valid (not too old)
                file_mtime = os.path.getmtime(cache_file)
                cache_age = datetime.datetime.now() - datetime.datetime.fromtimestamp(file_mtime)
                
                if cache_age.total_seconds() < cache_max_age_hours * 3600:
                    try:
                        with open(cache_file, 'r') as f:
                            cached_data = json.load(f)
                        
                        if cached_data and 'expiration' in cached_data:
                            # Only use cache if it's still valid for today
                            today = datetime.datetime.now(self.eastern_tz).strftime("%Y%m%d")
                            if today == cached_data['expiration']:
                                logger.info(f"Using cached option chain data for {ticker}")
                                return cached_data['chains']
                    except Exception as e:
                        logger.warning(f"Error reading cache file for {ticker}: {e}")
            
            # If we get here, we need fresh data
            logger.info(f"Fetching fresh option chain data for {ticker}")
            
            # Create stock contract
            stock = Stock(ticker, 'SMART', 'USD')
            qualified_contracts = self.ib.qualifyContracts(stock)
            
            if not qualified_contracts:
                logger.error(f"Could not qualify contract for {ticker}")
                return []
                
            # Get today's date in YYYYMMDD format for 0DTE options
            today = datetime.datetime.now(self.eastern_tz).strftime("%Y%m%d")
            
            # Get option chains
            try:
                chains = self.ib.reqSecDefOptParams(
                    qualified_contracts[0].symbol,
                    '',  # exchange
                    qualified_contracts[0].secType,
                    qualified_contracts[0].conId
                )
                # Print available expirations for debugging
                all_expirations = set()
                for chain in chains:
                    all_expirations.update(chain.expirations)
                sorted_expirations = sorted(list(all_expirations))
                logger.info(f"Available expirations for {ticker}: {', '.join(sorted_expirations[:5])}{'...' if len(sorted_expirations) > 5 else ''}")
            except Exception as e:
                logger.error(f"Error requesting option chains for {ticker}: {e}")
                return []
            
            if not chains:
                logger.error(f"No option chains found for {ticker}")
                return []
                
            # Find expirations for today (0DTE)
            valid_chains = [c for c in chains if today in c.expirations]
            
            if not valid_chains:
                logger.warning(f"No 0DTE options available for {ticker} on {today}")
                
                # Add this ticker to our list of tickers without 0DTE
                self.tickers_without_0dte.add(ticker)
                
                # Try to find closest expiration instead
                try:
                    # Get all available expirations across all chains
                    all_expirations = set()
                    for chain in chains:
                        all_expirations.update(chain.expirations)
                    
                    # Convert to dates for comparison
                    today_date = datetime.datetime.strptime(today, "%Y%m%d").date()
                    exp_dates = {}
                    for exp in all_expirations:
                        exp_date = datetime.datetime.strptime(exp, "%Y%m%d").date()
                        exp_dates[exp] = (exp_date - today_date).days
                    
                    # Find closest future expiration (smallest positive number of days)
                    future_exps = {exp: days for exp, days in exp_dates.items() if days > 0}
                    if future_exps:
                        closest_exp = min(future_exps.items(), key=lambda x: x[1])[0]
                        # Only use non-0DTE if allowed
                        if self.allow_non_0dte:
                            logger.info(f"Using closest expiration {closest_exp} for {ticker} ({future_exps[closest_exp]} days out)")
                            
                            # Get chains for this expiration
                            valid_chains = [c for c in chains if closest_exp in c.expirations]
                            if valid_chains:
                                logger.info(f"Found {len(valid_chains)} chains with expiration {closest_exp} for {ticker}")
                                return valid_chains
                        else:
                            logger.warning(f"Skipping {ticker} - closest expiration is {closest_exp} but non-0DTE trading is disabled (use --allow-non-0dte flag to enable)")
                            return []
                except Exception as e:
                    logger.error(f"Error finding alternative expiration for {ticker}: {e}")
                
                # If we got here, we couldn't find any valid alternative
                logger.warning(f"No suitable options available for {ticker}")
                return []
                
            # Save to cache
            try:
                # Convert chains to a serializable format
                serializable_chains = []
                for chain in valid_chains:
                    chain_data = {
                        'exchange': chain.exchange,
                        'tradingClass': chain.tradingClass,
                        'strikes': list(chain.strikes),
                        'expirations': list(chain.expirations)
                    }
                    serializable_chains.append(chain_data)
                    
                cache_data = {
                    'ticker': ticker,
                    'expiration': today,
                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'chains': serializable_chains
                }
                
                with open(cache_file, 'w') as f:
                    json.dump(cache_data, f, indent=2)
                    
            except Exception as cache_err:
                logger.warning(f"Error caching option chains for {ticker}: {cache_err}")
                
            return valid_chains
            
        except Exception as e:
            logger.error(f"Error getting option chains for {ticker}: {e}")
            return []
    
    @lru_cache(maxsize=32)
    def get_market_data(self, ticker: str) -> Dict:
        """Get real-time market data for a ticker.
        
        This method is cached to reduce API calls to IBKR.
        """
        try:
            # Create cache directory if it doesn't exist
            cache_dir = "cache"
            os.makedirs(cache_dir, exist_ok=True)
            
            # Check for cached market data
            cache_file = os.path.join(cache_dir, f"{ticker}_market_data_cache.json")
            cache_max_age_minutes = 15  # Cache for up to 15 minutes for market data
            
            # Check if cache exists and is fresh
            if os.path.exists(cache_file):
                # Check if cache is still valid (not too old)
                file_mtime = os.path.getmtime(cache_file)
                cache_age = datetime.datetime.now() - datetime.datetime.fromtimestamp(file_mtime)
                
                # Cache is fresh, try to use it
                if cache_age.total_seconds() < cache_max_age_minutes * 60:
                    try:
                        with open(cache_file, 'r') as f:
                            cached_data = json.load(f)
                        
                        logger.info(f"Using cached market data for {ticker} from {cached_data.get('timestamp', 'unknown time')}")
                        return cached_data
                    except Exception as e:
                        logger.warning(f"Error reading market data cache for {ticker}: {e}")
            
            # If we get here, we need fresh market data
            logger.info(f"Fetching fresh market data for {ticker}")
            
            stock = Stock(ticker, 'SMART', 'USD')
            qualified_contracts = self.ib.qualifyContracts(stock)
            
            if not qualified_contracts:
                logger.error(f"Could not qualify contract for {ticker}")
                return {}
            
            # First try real-time data
            try:    
                # Request real-time market data
                self.ib.reqMktData(qualified_contracts[0])
                self.ib.sleep(1)  # Allow time for data to arrive
                
                # Get the ticker snapshot
                ticker_data = self.ib.ticker(qualified_contracts[0])
                
                # Check if we have valid data
                has_data = (ticker_data.last is not None or ticker_data.bid is not None or 
                           ticker_data.ask is not None or ticker_data.close is not None)
                
                if not has_data:
                    logger.warning(f"No real-time data available for {ticker}, trying delayed data")
                    raise Exception("No real-time data available")
                    
                # Prepare market data dictionary
                data = {
                    'last': ticker_data.last,
                    'bid': ticker_data.bid,
                    'ask': ticker_data.ask,
                    'volume': ticker_data.volume,
                    'high': ticker_data.high,
                    'low': ticker_data.low,
                    'close': ticker_data.close,
                    'halted': ticker_data.halted,
                    'delayed': False,
                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # Store in market data cache
                self.market_data[ticker] = data
                
                # Save data to cache file
                try:
                    with open(cache_file, 'w') as f:
                        json.dump(data, f, indent=2)
                    logger.debug(f"Saved market data for {ticker} to cache")
                except Exception as cache_err:
                    logger.warning(f"Error caching market data for {ticker}: {cache_err}")
                
                logger.info(f"Retrieved real-time data for {ticker}")
                return data
                
            except Exception as rt_error:
                logger.warning(f"Error getting real-time data for {ticker}: {rt_error}")
                
                # Cancel previous request
                try:
                    self.ib.cancelMktData(qualified_contracts[0])
                    self.ib.sleep(0.5)
                except:
                    pass
                
                # Try with delayed data
                try:
                    logger.info(f"Requesting delayed data for {ticker}")
                    # Request delayed market data (regulatorySnapshot=True)
                    self.ib.reqMktData(qualified_contracts[0], snapshot=True, regulatorySnapshot=True)
                    self.ib.sleep(2)  # Wait longer for delayed data
                    
                    # Get the delayed ticker snapshot
                    delayed_data = self.ib.ticker(qualified_contracts[0])
                    
                    # Prepare delayed data dictionary
                    data = {
                        'last': delayed_data.last,
                        'bid': delayed_data.bid,
                        'ask': delayed_data.ask,
                        'volume': delayed_data.volume,
                        'high': delayed_data.high,
                        'low': delayed_data.low,
                        'close': delayed_data.close,
                        'halted': delayed_data.halted,
                        'delayed': True,
                        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    # If we have no last price but have bid/ask, use midpoint
                    if data['last'] is None and data['bid'] is not None and data['ask'] is not None:
                        data['last'] = (data['bid'] + data['ask']) / 2
                        
                    # If we still have no last price but have close, use that
                    if data['last'] is None and data['close'] is not None:
                        data['last'] = data['close']
                    
                    # Store in market data cache
                    self.market_data[ticker] = data
                    
                    # Save data to cache file
                    try:
                        with open(cache_file, 'w') as f:
                            json.dump(data, f, indent=2)
                        logger.debug(f"Saved delayed market data for {ticker} to cache")
                    except Exception as cache_err:
                        logger.warning(f"Error caching delayed market data for {ticker}: {cache_err}")
                    
                    logger.info(f"Retrieved delayed data for {ticker}")
                    return data
                    
                except Exception as delayed_error:
                    logger.error(f"Error getting delayed data for {ticker}: {delayed_error}")
                    return {}
            
            
        except Exception as e:
            logger.error(f"Error getting market data for {ticker}: {e}")
            return {}
    
    def get_future_quote(self, symbol: str, use_delayed: bool = True) -> Dict:
        """Get real-time quote for futures contracts."""
        try:
            # Mapping of recommended exchanges for different futures
            exchange_map = {
                "MYM": "CBOT",  # Micro Dow Jones
                "YM": "CBOT",   # E-mini Dow Jones
                "ES": "CME",    # E-mini S&P 500
                "MES": "CME",   # Micro E-mini S&P 500
                "NQ": "CME",    # E-mini NASDAQ 100
                "MNQ": "CME",   # Micro E-mini NASDAQ 100
                "RTY": "CME",   # E-mini Russell 2000
                "M2K": "CME",   # Micro E-mini Russell 2000
                "GC": "COMEX",  # Gold
                "MGC": "COMEX", # Micro Gold
                "SI": "COMEX",  # Silver
                "CL": "NYMEX",  # Crude Oil
                "QM": "NYMEX",  # E-mini Crude Oil
                "NG": "NYMEX",  # Natural Gas
                "ZB": "CBOT",   # U.S. Treasury Bond
                "ZN": "CBOT",   # 10-Year U.S. Treasury Note
                "ZF": "CBOT",   # Five-Year U.S. Treasury Note
                "ZT": "CBOT",   # Two-Year U.S. Treasury Note
                "6E": "CME",    # Euro FX
                "6J": "CME",    # Japanese Yen
                "6B": "CME",    # British Pound
                "6C": "CME",    # Canadian Dollar
                "6A": "CME",    # Australian Dollar
                "ZC": "CBOT",   # Corn
                "ZS": "CBOT",   # Soybeans
                "ZW": "CBOT",   # Wheat
            }
            
            # Get exchange for the symbol
            exchange = exchange_map.get(symbol, "GLOBEX")
            
            # Create contract with proper exchange
            contract = Future(symbol, exchange=exchange)
            
            # Try to qualify the contract
            try:
                contracts = self.ib.qualifyContracts(contract)
                if contracts:
                    contract = contracts[0]
                else:
                    logger.warning(f"Could not qualify future contract {symbol}. Trying alternative exchanges...")
                    # Try alternative exchanges if qualification fails
                    for alt_exchange in ["GLOBEX", "CME", "CBOT", "NYMEX", "COMEX"]:
                        if alt_exchange != exchange:
                            alt_contract = Future(symbol, exchange=alt_exchange)
                            alt_contracts = self.ib.qualifyContracts(alt_contract)
                            if alt_contracts:
                                contract = alt_contracts[0]
                                logger.info(f"Successfully qualified {symbol} with exchange {alt_exchange}")
                                break
            except Exception as e:
                logger.error(f"Error qualifying future contract {symbol}: {e}")
                # If qualification fails, try a more generic approach
                contract = Future(symbol, exchange=exchange)
                
            # Request market data (try real-time first, then delayed if needed)
            try:
                self.ib.reqMktData(contract, snapshot=True)
                self.ib.sleep(1)  # Allow time for data to arrive
                ticker_data = self.ib.ticker(contract)
                
                # If no real-time data and delayed is allowed, try delayed data
                if (ticker_data.last is None or ticker_data.bid is None or ticker_data.ask is None) and use_delayed:
                    logger.info(f"No real-time data for {symbol}, requesting delayed data")
                    self.ib.reqMktData(contract, snapshot=True, regulatorySnapshot=True)
                    self.ib.sleep(1)
                    ticker_data = self.ib.ticker(contract)
            except Exception as e:
                logger.error(f"Error requesting market data for {symbol}: {e}")
                return {}
                
            # Prepare data dictionary
            data = {
                'last': ticker_data.last,
                'bid': ticker_data.bid,
                'ask': ticker_data.ask,
                'volume': ticker_data.volume,
                'high': ticker_data.high,
                'low': ticker_data.low,
                'close': ticker_data.close,
                'halted': ticker_data.halted
            }
            
            # Special handling for when real-time data isn't available
            # If no last price but we have bid/ask, use midpoint
            if data['last'] is None and data['bid'] is not None and data['ask'] is not None:
                data['last'] = (data['bid'] + data['ask']) / 2
                
            # If still no last price but we have close, use that
            if data['last'] is None and data['close'] is not None:
                data['last'] = data['close']
                
            return data
            
        except Exception as e:
            logger.error(f"Error getting future quote for {symbol}: {e}")
            return {}
    
    def find_trading_opportunities(self) -> List[Dict]:
        """
        Scan the market for 0DTE option trading opportunities.
        Returns a list of potential trade setups.
        """
        opportunities = []
        
        # Filter out tickers we already know don't have 0DTE options
        active_tickers = [t for t in self.config["tickers"] if t not in self.tickers_without_0dte]
        if len(active_tickers) < len(self.config["tickers"]):
            skipped = list(set(self.config["tickers"]) - set(active_tickers))
            logger.info(f"Skipping {len(skipped)} tickers without 0DTE options: {', '.join(skipped)}")
            
        # If all tickers are known to not have 0DTE, but allow_non_0dte is False, warn
        if not active_tickers and not self.allow_non_0dte:
            logger.warning("All configured tickers lack 0DTE options. Use --allow-non-0dte to enable trading with future expirations.")
            return []
        
        # Check if using individual stocks
        stock_tickers = [t for t in self.config["tickers"] if t not in ["SPY", "QQQ", "IWM", "XLF", "EEM", "XLE", "SQQQ", "TQQQ"]]
        futures_tickers = [t for t in self.config["tickers"] if t in ["ES", "NQ", "YM", "RTY", "GC", "MES", "MNQ", "MYM", "M2K", "MGC"]]
        
        if stock_tickers:
            logger.info(f"Trading individual stocks: {', '.join(stock_tickers)}")
            # Check for fractional shares capability
            use_fractional = self.config.get("use_fractional_shares", True)
            logger.info(f"{'Using' if use_fractional else 'Not using'} fractional shares for stock positions")
            
            # Check for price limits
            max_price = self.config.get("max_price_per_share", 500)
            logger.info(f"Maximum price per share set to ${max_price}")
            
        # Enforce use of micro futures if configured
        if futures_tickers:
            use_micros = self.config.get("use_micros", True)
            logger.info(f"Trading with {'micro' if use_micros else 'standard'} futures contracts")
            
            # If using micros, filter out non-micro futures contracts
            if use_micros:
                # Map standard futures to their micro equivalents
                standard_to_micro = {
                    "ES": "MES",  # E-mini S&P 500 -> Micro E-mini S&P 500
                    "NQ": "MNQ",  # E-mini Nasdaq -> Micro E-mini Nasdaq
                    "YM": "MYM",  # E-mini Dow -> Micro E-mini Dow
                    "RTY": "M2K", # E-mini Russell -> Micro E-mini Russell
                    "GC": "MGC"   # Gold -> Micro Gold
                }
                
                # Ensure we're only using micro contracts where available
                for i, ticker in enumerate(self.config["tickers"]):
                    if ticker in standard_to_micro:
                        logger.warning(f"Converting standard future {ticker} to micro future {standard_to_micro[ticker]}")
                        self.config["tickers"][i] = standard_to_micro[ticker]
        
        for ticker in active_tickers:
            try:
                # Check if we already traded this ticker today
                if ticker in self.last_trade_time:
                    last_trade = self.last_trade_time[ticker]
                    now = datetime.datetime.now(self.eastern_tz)
                    if last_trade.date() == now.date():
                        logger.info(f"Already traded {ticker} today, skipping")
                        continue
                
                # Get market data
                market_data = self.get_market_data(ticker)
                if not market_data or 'last' not in market_data or market_data['last'] is None:
                    logger.warning(f"Insufficient market data for {ticker}, skipping")
                    continue
                    
                # Get option chains
                chains = self.get_option_chains(ticker)
                if not chains:
                    logger.warning(f"No option chains found for {ticker}, skipping")
                    continue
                    
                # Implement strategy-specific logic here to find opportunities
                # ...
                
                # Example: Simple breakout detection (replace with actual strategy)
                current_price = market_data['last']
                if market_data.get('high') and current_price >= market_data['high'] * 1.01:
                    # Potential breakout to the upside - look for call options
                    logger.info(f"Potential upside breakout detected for {ticker}")
                    # Find suitable call option contract
                    # ...
                    
                elif market_data.get('low') and current_price <= market_data['low'] * 0.99:
                    # Potential breakdown - look for put options
                    logger.info(f"Potential downside breakdown detected for {ticker}")
                    # Find suitable put option contract
                    # ...
                
                # Add valid opportunities to the list
                # opportunities.append(...)
                
            except Exception as e:
                logger.error(f"Error finding trading opportunities for {ticker}: {e}")
                
        return opportunities
    
    def execute_trade(self, trade_setup: Dict) -> bool:
        """Execute a trade based on the provided trade setup."""
        try:
            ticker = trade_setup.get('ticker')
            direction = trade_setup.get('direction')
            contract = trade_setup.get('contract')
            price = trade_setup.get('price')
            quantity = trade_setup.get('quantity')
            
            if not all([ticker, direction, contract, price, quantity]):
                logger.error(f"Invalid trade setup: {trade_setup}")
                return False
                
            # Check if we have enough trading capital
            risk_amount = price * quantity * 100  # For options, multiply by 100
            if risk_amount > self.config["risk_per_trade"]:
                quantity = max(1, int(self.config["risk_per_trade"] / (price * 100)))
                logger.info(f"Reduced quantity to {quantity} to respect risk per trade limit")
                
            # Create the order
            if direction == 'BUY':
                order = MarketOrder('BUY', quantity)
            else:
                order = MarketOrder('SELL', quantity)
                
            # Submit the order
            trade = self.ib.placeOrder(contract, order)
            self.ib.sleep(1)
            
            # Verify order status
            if trade.orderStatus.status in ['Filled', 'Submitted', 'PreSubmitted']:
                logger.info(f"Trade executed: {direction} {quantity} {ticker} at {price}")
                
                # Record trade time
                self.last_trade_time[ticker] = datetime.datetime.now(self.eastern_tz)
                
                # Add to open positions
                position_key = f"{ticker}_{contract.conId}"
                self.open_positions[position_key] = {
                    'ticker': ticker,
                    'contract': contract,
                    'direction': direction,
                    'quantity': quantity,
                    'entry_price': price,
                    'entry_time': datetime.datetime.now(self.eastern_tz),
                    'trade_id': trade.order.orderId
                }
                
                return True
            else:
                logger.error(f"Trade failed: {trade.orderStatus.status} - {trade.orderStatus.message}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False
    
    def close_position(self, position_key: str, reason: str = "Manual") -> bool:
        """Close an open position."""
        try:
            if position_key not in self.open_positions:
                logger.error(f"Position {position_key} not found in open positions")
                return False
                
            position = self.open_positions[position_key]
            contract = position['contract']
            current_direction = position['direction']
            quantity = position['quantity']
            
            # Create opposing order
            close_direction = 'SELL' if current_direction == 'BUY' else 'BUY'
            
            # Handle special case for futures
            if isinstance(contract, Future):
                from ib_insync import MarketOrder
                order = MarketOrder(close_direction, quantity)
            else:
                order = MarketOrder(close_direction, quantity)
                
            # Submit the order
            trade = self.ib.placeOrder(contract, order)
            self.ib.sleep(1)
            
            # Verify order status
            if trade.orderStatus.status in ['Filled', 'Submitted', 'PreSubmitted']:
                logger.info(f"Position closed: {close_direction} {quantity} {position['ticker']} - Reason: {reason}")
                
                # Remove from open positions
                del self.open_positions[position_key]
                return True
            else:
                logger.error(f"Failed to close position: {trade.orderStatus.status} - {trade.orderStatus.message}")
                return False
                
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return False
    
    def manage_positions(self):
        """Manage open positions (apply stop loss, take profit, etc.)"""
        for position_key, position in list(self.open_positions.items()):
            try:
                # Skip position management if position was just opened
                time_delta = datetime.datetime.now(self.eastern_tz) - position['entry_time']
                if time_delta.total_seconds() < 60:  # Give at least 60 seconds before managing
                    continue
                    
                # Get current price data
                ticker = position['ticker']
                contract = position['contract']
                direction = position['direction']
                entry_price = position['entry_price']
                
                # Get current market price
                self.ib.reqMktData(contract)
                self.ib.sleep(1)
                ticker_data = self.ib.ticker(contract)
                current_price = ticker_data.last
                
                if current_price is None:
                    if ticker_data.bid is not None and ticker_data.ask is not None:
                        current_price = (ticker_data.bid + ticker_data.ask) / 2
                    else:
                        logger.warning(f"Unable to get current price for {ticker}")
                        continue
                
                # Calculate P&L
                if direction == 'BUY':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                
                # Check stop loss (default 50% loss)
                stop_loss_pct = self.config.get("stop_loss_pct", 50)
                if pnl_pct <= -stop_loss_pct:
                    logger.info(f"Stop loss triggered for {ticker}: {pnl_pct:.2f}%")
                    self.close_position(position_key, reason="Stop Loss")
                    continue
                    
                # Check take profit (default 100% gain)
                take_profit_pct = self.config.get("take_profit_pct", 100)
                if pnl_pct >= take_profit_pct:
                    logger.info(f"Take profit triggered for {ticker}: {pnl_pct:.2f}%")
                    self.close_position(position_key, reason="Take Profit")
                    continue
                    
                # Check time-based exit (close positions near end of day)
                now = datetime.datetime.now(self.eastern_tz)
                market_close = datetime.datetime(
                    now.year, now.month, now.day, 15, 55, 0,  # 3:55 PM Eastern
                    tzinfo=self.eastern_tz
                )
                
                if now >= market_close and now.hour < 16:
                    logger.info(f"End of day exit for {ticker}")
                    self.close_position(position_key, reason="End of Day")
                    continue
                    
            except Exception as e:
                logger.error(f"Error managing position {position_key}: {e}")
    
    def run(self):
        """Main trading loop."""
        try:
            # Connect to IB
            self.connect()
            
            logger.info("Starting main trading loop")
            
            # Send notification on startup
            self.send_notification("ODTE Bot Started", f"Running with {len(self.config.get('tickers', []))} tickers")
            
            # Track number of trades today
            trades_today = 0
            trade_date = datetime.datetime.now(self.eastern_tz).date()
            
            while True:
                # Check if we're in trading hours (9:30 AM - 4:00 PM Eastern, weekdays)
                now = datetime.datetime.now(self.eastern_tz)
                
                # Reset trades counter and clear tickers_without_0dte on a new day
                if now.date() != trade_date:
                    trades_today = 0
                    trade_date = now.date()
                    # Clear the list of tickers without 0DTE at the start of a new day, since new expiries might be available
                    self.tickers_without_0dte.clear()
                    logger.info("New trading day - reset 0DTE availability tracking")
                    
                # Trading hours check
                is_trading_hours = (
                    now.weekday() < 5 and  # Monday to Friday
                    ((now.hour == 9 and now.minute >= 30) or now.hour > 9) and  # After 9:30 AM
                    now.hour < 16  # Before 4:00 PM
                )
                
                if not is_trading_hours:
                    logger.info("Outside of trading hours, waiting...")
                    # Close any open positions if it's after market hours
                    if now.hour >= 16:
                        for position_key in list(self.open_positions.keys()):
                            self.close_position(position_key, reason="After Hours")
                    
                    # Wait 15 minutes before checking again
                    self.ib.sleep(900)
                    continue
                
                # Check for and maintain IB connection
                if not self.ib.isConnected():
                    logger.warning("IB connection lost, attempting to reconnect...")
                    self.connect()
                
                # Manage existing positions
                self.manage_positions()
                
                # Check if we've reached the maximum number of trades for today
                if trades_today >= self.config["max_daily_trades"]:
                    logger.info(f"Reached maximum daily trades ({trades_today}), waiting for tomorrow")
                    self.ib.sleep(300)  # Wait 5 minutes before checking again
                    continue
                
                # Find trading opportunities
                opportunities = self.find_trading_opportunities()
                
                # Execute trades for valid opportunities
                for opportunity in opportunities:
                    if trades_today >= self.config["max_daily_trades"]:
                        break
                        
                    # Send notification about trade opportunity
                    ticker = opportunity.get('ticker', 'Unknown')
                    direction = opportunity.get('direction', 'Unknown')
                    price = opportunity.get('price', 0)
                    self.send_notification(
                        "Trade Opportunity", 
                        f"{direction} {ticker} at ${price:.2f}"
                    )
                        
                    if self.execute_trade(opportunity):
                        trades_today += 1
                        
                        # Send notification about executed trade
                        self.send_notification(
                            "Trade Executed", 
                            f"{direction} {ticker} at ${price:.2f}"
                        )
                
                # Wait before next iteration
                self.ib.sleep(60)  # 1 minute
                
        except KeyboardInterrupt:
            logger.info("Trading bot stopped by user")
            # Close all positions on exit
            for position_key in list(self.open_positions.keys()):
                self.close_position(position_key, reason="User Exit")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
        finally:
            # Disconnect from IB
            if self.ib.isConnected():
                self.ib.disconnect()
                logger.info("Disconnected from IB")

def main():
    """Main entry point for the trading bot."""
    parser = argparse.ArgumentParser(description="0DTE Options Trading Bot for Interactive Brokers")
    
    parser.add_argument(
        "--config", 
        type=str, 
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to configuration file (default: {DEFAULT_CONFIG_PATH})"
    )
    
    parser.add_argument(
        "--host", 
        type=str, 
        default=DEFAULT_HOST,
        help=f"TWS/IB Gateway host (default: {DEFAULT_HOST})"
    )
    
    parser.add_argument(
        "--port", 
        type=int, 
        default=DEFAULT_PORT,
        help=f"TWS/IB Gateway port (default: {DEFAULT_PORT})"
    )
    
    parser.add_argument(
        "--client-id", 
        type=int, 
        default=DEFAULT_CLIENT_ID,
        help=f"Client ID for IB connection (default: {DEFAULT_CLIENT_ID})"
    )
    
    parser.add_argument(
        "--paper-trading",
        action="store_true",
        help="Use paper trading account"
    )
    
    parser.add_argument(
        "--allow-non-0dte",
        action="store_true",
        help="Allow trading options that expire in the near future (not just today)"
    )
    
    args = parser.parse_args()
    
    # Adjust port for paper trading if specified
    if args.paper_trading and args.port == 7496:
        args.port = 7497
        logger.info("Paper trading enabled, using port 7497")
    else:
        logger.info("LIVE TRADING ENABLED - Using port 7496")
        logger.warning("CAUTION: Trading with real money. Max 1 trade per day configured.")
        
    # Check if non-0DTE options are allowed
    if args.allow_non_0dte:
        logger.info("Allowing options that expire beyond today (non-0DTE)")
        logger.warning("This is a modification of the standard 0DTE strategy")
    
    # Create and run the trading bot
    trader = ODTEBreakoutTrader(
        config_path=args.config,
        host=args.host,
        port=args.port,
        client_id=args.client_id
    )
    
    # Set flag for allowing non-0DTE options if specified
    if args.allow_non_0dte:
        trader.allow_non_0dte = True
    
    trader.run()

if __name__ == "__main__":
    main()
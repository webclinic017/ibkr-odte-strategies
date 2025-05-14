#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Straddle Earnings Bot
---------------------
Interactive Brokers trading bot that identifies and executes options straddle
strategies around company earnings announcements.

This script automatically:
1. Connects to IBKR TWS or IB Gateway
2. Loads configuration from config files
3. Identifies upcoming earnings announcements
4. Evaluates candidates based on IV, liquidity, and cost
5. Executes straddle positions (buy both call and put)
6. Manages positions with configurable exit strategies
7. Logs all activities for analysis

Requirements:
- Interactive Brokers account with TWS or IB Gateway running
- ib_insync library
- yfinance library for earnings data
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

# Try to import required libraries, provide helpful error if not installed
try:
    from ib_insync import IB, Contract, Stock, Option
    from ib_insync import MarketOrder, LimitOrder, StopOrder
    from ib_insync import util
except ImportError:
    print("Error: ib_insync package not found. Install with: pip install ib_insync")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance package not found. Install with: pip install yfinance")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("straddle_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("STRADDLE-BOT")

# Default configuration path
DEFAULT_CONFIG_PATH = os.path.join("config", "earnings_straddle_config.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7496  # TWS live trading port (use 7497 for TWS paper, 4001 for Gateway live, 4002 for Gateway paper)
DEFAULT_CLIENT_ID = 2

class StraddleEarningsTrader:
    """Main class for the earnings announcement straddle trading strategy."""
    
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
        self.eastern_tz = pytz.timezone('US/Eastern')
        self.positions_file = "data/earnings_straddle_positions.json"
        self.earnings_checked_date = None  # Last date we checked earnings calendar
        self.tickers_checked_today = set()  # Tickers we've already checked today
        self.skip_notification = False  # Whether to skip notifications
        
        # Create data directory if it doesn't exist
        os.makedirs("data", exist_ok=True)
        
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
        
        # Load open positions from file
        self.load_positions()
        
    def load_config(self):
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
            logger.info(f"Configuration loaded from {self.config_path}")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            sys.exit(1)
            
    def load_positions(self):
        """Load open positions from JSON file."""
        if os.path.exists(self.positions_file):
            try:
                with open(self.positions_file, 'r') as f:
                    positions_data = json.load(f)
                    
                if positions_data and isinstance(positions_data, dict):
                    # Need to recreate contract objects as they're not serializable
                    for pos_id, pos in positions_data.items():
                        # Check if the position has the required fields
                        if all(k in pos for k in ['ticker', 'expiry_date', 'earnings_date']):
                            try:
                                # Convert string dates back to date objects
                                if isinstance(pos['expiry_date'], str):
                                    pos['expiry_date'] = datetime.datetime.strptime(pos['expiry_date'], '%Y-%m-%d').date()
                                if isinstance(pos['earnings_date'], str):
                                    pos['earnings_date'] = datetime.datetime.strptime(pos['earnings_date'], '%Y-%m-%d').date()
                                if 'entry_time' in pos and isinstance(pos['entry_time'], str):
                                    pos['entry_time'] = datetime.datetime.strptime(pos['entry_time'], '%Y-%m-%d %H:%M:%S')
                                    if 'tzinfo' in dir(self.eastern_tz):
                                        pos['entry_time'] = self.eastern_tz.localize(pos['entry_time'])
                                
                                # We need to recreate contracts which are missing
                                # This only happens here during initialization
                                ticker = pos['ticker']
                                strike = pos.get('strike')
                                expiration = pos.get('expiration')
                                
                                # Only add positions that are recent and need management
                                today = datetime.datetime.now(self.eastern_tz).date()
                                if pos['expiry_date'] >= today:
                                    self.open_positions[pos_id] = pos
                                    logger.info(f"Loaded active position for {ticker} from saved state")
                            except Exception as pos_err:
                                logger.error(f"Error processing saved position {pos_id}: {pos_err}")
                                continue
                    
                    logger.info(f"Loaded {len(self.open_positions)} active positions from {self.positions_file}")
            except Exception as e:
                logger.error(f"Error loading positions file: {e}")
        else:
            logger.info(f"No positions file found at {self.positions_file}")
            
    def save_positions(self):
        """Save open positions to JSON file."""
        try:
            # Make a serializable copy of positions dictionary
            serializable_positions = {}
            
            for pos_id, pos in self.open_positions.items():
                # Create a copy that can be safely modified
                serialized_pos = {}
                
                # Copy basic fields
                for key, val in pos.items():
                    # Skip contract objects which can't be serialized
                    if key in ['call_contract', 'put_contract']:
                        continue
                        
                    # Convert dates to strings
                    if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
                        serialized_pos[key] = val.strftime('%Y-%m-%d')
                    elif isinstance(val, datetime.datetime):
                        serialized_pos[key] = val.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        serialized_pos[key] = val
                
                serializable_positions[pos_id] = serialized_pos
                
            # Write to file
            with open(self.positions_file, 'w') as f:
                json.dump(serializable_positions, f, indent=2)
                
            logger.info(f"Saved {len(self.open_positions)} positions to {self.positions_file}")
        except Exception as e:
            logger.error(f"Error saving positions: {e}")
            
        # Validate required configuration parameters
        required_params = [
            "tickers_whitelist", "max_capital_per_trade", "min_iv_rank",
            "min_volume", "min_open_interest", "max_days_to_expiry",
            "max_daily_trades"
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
    
    def get_upcoming_earnings(self) -> List[Dict]:
        """
        Get a list of upcoming earnings announcements.
        Returns list of dicts with ticker, date, and time information.
        Uses a cache file to reduce API calls.
        """
        try:
            # Define cache file path
            cache_dir = "cache"
            os.makedirs(cache_dir, exist_ok=True)
            cache_file = os.path.join(cache_dir, "earnings_cache.json")
            
            # Define date range to look for earnings (today through next 7 days)
            today = datetime.datetime.now(self.eastern_tz).date()
            max_days = self.config.get("max_days_to_look_ahead", 7)
            end_date = today + datetime.timedelta(days=max_days)
            
            # Check if we've already checked today (avoid redundant API calls)
            if self.earnings_checked_date == today:
                logger.info(f"Already checked earnings calendar today ({today}), using in-memory data")
                return self.earnings_list_cache
                
            # Check if we have a valid cache
            use_cache = False
            cache_max_age_hours = 12  # Refresh cache every 12 hours
            
            if os.path.exists(cache_file):
                try:
                    # Check cache age
                    file_mtime = os.path.getmtime(cache_file)
                    cache_age = datetime.datetime.now() - datetime.datetime.fromtimestamp(file_mtime)
                    
                    if cache_age.total_seconds() < cache_max_age_hours * 3600:
                        # Cache is fresh enough - load it
                        with open(cache_file, 'r') as f:
                            cache_data = json.load(f)
                            
                        # Verify cache format and date range
                        if isinstance(cache_data, dict) and 'last_update' in cache_data and 'earnings' in cache_data:
                            # Convert cached dates back to date objects
                            earnings_list = []
                            for e in cache_data['earnings']:
                                if 'date' in e:
                                    try:
                                        # Convert string date back to date object
                                        e['date'] = datetime.datetime.strptime(e['date'], '%Y-%m-%d').date()
                                        earnings_list.append(e)
                                    except:
                                        pass
                                        
                            if earnings_list:
                                logger.info(f"Using cached earnings data ({len(earnings_list)} entries) from {cache_data.get('last_update')}")
                                return earnings_list
                except Exception as cache_err:
                    logger.error(f"Error reading cache file: {cache_err}")
            
            # If we get here, we need to fetch fresh data
            logger.info("Fetching fresh earnings data from API")
            
            # Fetch earnings data from Yahoo Finance
            earnings_list = []
            
            # If we have a whitelist, use it
            tickers = self.config["tickers_whitelist"]
            if not tickers:
                logger.error("No tickers in whitelist")
                return []
                
            # Save the date we're checking to avoid redundant calls
            self.earnings_checked_date = today
            self.earnings_list_cache = []  # Initialize cache
            
            # Fetch earnings calendar for each ticker
            for ticker in tickers:
                try:
                    stock = yf.Ticker(ticker)
                    calendar = stock.calendar
                    
                    if calendar is not None and hasattr(calendar, 'loc') and 'Earnings Date' in calendar.columns:
                        earnings_date = calendar.loc[0, 'Earnings Date']
                        
                        # Skip if earnings date is None or outside our range
                        if earnings_date is None:
                            continue
                            
                        earnings_date = earnings_date.date()
                        if earnings_date < today or earnings_date > end_date:
                            continue
                            
                        # Determine if earnings is before market, after market, or during market
                        time_str = "Unknown"
                        if 'Earnings Time' in calendar.columns:
                            time_str = calendar.loc[0, 'Earnings Time']
                            
                        earnings_list.append({
                            'ticker': ticker,
                            'date': earnings_date,
                            'time': time_str
                        })
                        logger.info(f"Found upcoming earnings for {ticker} on {earnings_date} ({time_str})")
                        
                except Exception as e:
                    logger.error(f"Error fetching earnings data for {ticker}: {e}")
                    continue
            
            # Save to cache
            try:
                # Need to convert date objects to strings for JSON serialization
                cache_data = {
                    'last_update': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'earnings': []
                }
                
                for e in earnings_list:
                    cache_entry = e.copy()
                    cache_entry['date'] = e['date'].strftime('%Y-%m-%d')
                    cache_data['earnings'].append(cache_entry)
                    
                with open(cache_file, 'w') as f:
                    json.dump(cache_data, f, indent=2)
                    
                logger.info(f"Saved {len(earnings_list)} earnings entries to cache")
                    
            except Exception as save_err:
                logger.error(f"Error saving earnings cache: {save_err}")
            
            # Update our in-memory cache with the results
            self.earnings_list_cache = earnings_list
            return earnings_list
            
        except Exception as e:
            logger.error(f"Error getting upcoming earnings: {e}")
            return []
    
    @lru_cache(maxsize=32)
    def get_option_chains(self, ticker: str, max_days_to_expiry: int) -> List[Option]:
        """Get option chains for a ticker with expiry within the specified days.
        
        This method is cached to reduce API calls to IBKR.
        """
        try:
            # Create cache directory if it doesn't exist
            cache_dir = "cache"
            os.makedirs(cache_dir, exist_ok=True)
            
            # Check for cached option chain data
            cache_file = os.path.join(cache_dir, f"{ticker}_options_{max_days_to_expiry}_days_cache.json")
            cache_max_age_hours = 4  # Cache for up to 4 hours
            
            use_cache = False
            if os.path.exists(cache_file):
                # Check if cache is still valid (not too old)
                file_mtime = os.path.getmtime(cache_file)
                cache_age = datetime.datetime.now() - datetime.datetime.fromtimestamp(file_mtime)
                
                if cache_age.total_seconds() < cache_max_age_hours * 3600:
                    try:
                        with open(cache_file, 'r') as f:
                            cached_data = json.load(f)
                        
                        if cached_data and 'chains' in cached_data:
                            # We need to convert the tuple-like structures back to tuples
                            valid_chains = []
                            for chain_data in cached_data['chains']:
                                chain = type('ChainObj', (), {})
                                chain.exchange = chain_data[0]['exchange']
                                chain.tradingClass = chain_data[0]['tradingClass']  
                                chain.strikes = chain_data[0]['strikes']
                                chain.expirations = chain_data[0]['expirations']
                                expiration = chain_data[1]
                                valid_chains.append((chain, expiration))
                                
                            logger.info(f"Using cached option chain data for {ticker} ({len(valid_chains)} expirations)")
                            return valid_chains
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
                
            # Get today's date
            today = datetime.datetime.now(self.eastern_tz).date()
            max_date = today + datetime.timedelta(days=max_days_to_expiry)
            
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
                
                if not chains:
                    logger.error(f"No option chains found for {ticker}")
                    return []
            except Exception as e:
                logger.error(f"Error requesting option chains for {ticker}: {e}")
                return []
                
            # Filter chains to include only expirations within our range
            valid_chains = []
            for chain in chains:
                for expiration in chain.expirations:
                    expiry_date = datetime.datetime.strptime(expiration, "%Y%m%d").date()
                    if today <= expiry_date <= max_date:
                        valid_chains.append((chain, expiration))
            
            # Sort chains by expiration date (closest first)
            valid_chains.sort(key=lambda x: datetime.datetime.strptime(x[1], "%Y%m%d").date())
            
            # Log available expirations that match our criteria
            if valid_chains:
                exps = [x[1] for x in valid_chains[:5]]  # Show at most 5 expirations
                logger.info(f"Found {len(valid_chains)} valid option chains for {ticker} with expirations: {', '.join(exps)}{' and more' if len(valid_chains) > 5 else ''}")
            else:
                logger.warning(f"No options within {max_days_to_expiry} days for {ticker}")
                return []
                
            # Save to cache
            try:
                # Convert chains to a serializable format
                serializable_chains = []
                for chain, expiration in valid_chains:
                    chain_data = {
                        'exchange': chain.exchange,
                        'tradingClass': chain.tradingClass,
                        'strikes': list(chain.strikes),
                        'expirations': list(chain.expirations)
                    }
                    serializable_chains.append([chain_data, expiration])
                    
                cache_data = {
                    'ticker': ticker,
                    'max_days': max_days_to_expiry,
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
            
            # Check if we need a specific exchange
            exchange = 'SMART'
            
            # Create stock contract
            stock = Stock(ticker, exchange, 'USD')
            qualified_contracts = self.ib.qualifyContracts(stock)
            
            if not qualified_contracts:
                logger.error(f"Could not qualify contract for {ticker}")
                return {}
                
            # First try with real-time data
            try:
                # Request market data
                logger.info(f"Requesting real-time data for {ticker}")
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
                    # Request delayed market data
                    self.ib.reqMktData(qualified_contracts[0], snapshot=True, regulatorySnapshot=True)
                    self.ib.sleep(2)  # Wait longer for delayed data
                    
                    # Get the delayed ticker snapshot
                    ticker_data = self.ib.ticker(qualified_contracts[0])
                    logger.info(f"Retrieved delayed data for {ticker}")
                except Exception as delayed_error:
                    logger.error(f"Error getting delayed data for {ticker}: {delayed_error}")
                    return {}
            
            # Try to get IV data if available
            implied_volatility = None
            option_tickers = []
            
            # If we have no last price but have bid/ask, use midpoint
            last_price = ticker_data.last
            if last_price is None and ticker_data.bid is not None and ticker_data.ask is not None:
                last_price = (ticker_data.bid + ticker_data.ask) / 2
                
            # If still no last price, try close
            if last_price is None:
                last_price = ticker_data.close
                
            # Calculate IV rank if possible
            iv_rank = None
            if ticker_data.impliedVolatility is not None:
                implied_volatility = ticker_data.impliedVolatility
                
                # Fetch historical volatility data (simulated example - replace with actual logic)
                # In a real implementation, you would fetch historical IV data from a source
                iv_52_week_low = implied_volatility * 0.5  # Simulated
                iv_52_week_high = implied_volatility * 1.5  # Simulated
                
                # Calculate IV rank (0-100)
                iv_range = iv_52_week_high - iv_52_week_low
                if iv_range > 0:
                    iv_rank = (implied_volatility - iv_52_week_low) / iv_range * 100
            
            # Prepare market data dictionary
            data = {
                'last': last_price,
                'bid': ticker_data.bid,
                'ask': ticker_data.ask,
                'volume': ticker_data.volume,
                'high': ticker_data.high,
                'low': ticker_data.low,
                'close': ticker_data.close,
                'halted': ticker_data.halted,
                'implied_volatility': implied_volatility,
                'iv_rank': iv_rank,
                'delayed': getattr(ticker_data, 'delayed', False),
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # Store in market data cache
            self.market_data[ticker] = data
            
            # Save data to cache file
            try:
                cache_file = os.path.join("cache", f"{ticker}_market_data_cache.json")
                with open(cache_file, 'w') as f:
                    json.dump(data, f, indent=2)
                logger.debug(f"Saved market data for {ticker} to cache")
            except Exception as cache_err:
                logger.warning(f"Error caching market data for {ticker}: {cache_err}")
            
            if data.get('delayed', False):
                logger.info(f"Using delayed data for {ticker}")
            else:
                logger.info(f"Using real-time data for {ticker}")
                
            return data
            
        except Exception as e:
            logger.error(f"Error getting market data for {ticker}: {e}")
            return {}
    
    def calculate_option_price(self, option_contract: Option) -> float:
        """Get the price of an option contract."""
        try:
            # Request market data for the option
            self.ib.reqMktData(option_contract)
            self.ib.sleep(1)  # Allow time for data to arrive
            
            # Get the ticker snapshot
            ticker_data = self.ib.ticker(option_contract)
            
            # Use last price if available
            if ticker_data.last is not None:
                return ticker_data.last
                
            # Otherwise use midpoint of bid/ask
            if ticker_data.bid is not None and ticker_data.ask is not None:
                return (ticker_data.bid + ticker_data.ask) / 2
                
            # If neither is available, return 0
            logger.warning(f"Could not get price for option {option_contract.symbol} {option_contract.strike} {option_contract.right}")
            return 0
            
        except Exception as e:
            logger.error(f"Error calculating option price: {e}")
            return 0
    
    def find_straddle_opportunities(self) -> List[Dict]:
        """
        Find suitable earnings straddle opportunities.
        Returns a list of potential trade setups.
        """
        opportunities = []
        
        # Check if we're trading individual stocks
        stock_tickers = [t for t in self.config["tickers_whitelist"] if t not in ["SPY", "QQQ", "IWM", "XLF", "EEM", "XLE", "SQQQ", "TQQQ"]]
        etf_tickers = [t for t in self.config["tickers_whitelist"] if t in ["SPY", "QQQ", "IWM", "XLF", "EEM", "XLE", "SQQQ", "TQQQ"]]
        
        if stock_tickers:
            logger.info(f"Trading earnings straddles on individual stocks: {', '.join(stock_tickers)}")
            # Check price limits for individual stocks
            min_price = self.config.get("min_price", 50)
            max_price = self.config.get("max_price", 500)
            logger.info(f"Stock price range: ${min_price} - ${max_price}")
        
        if etf_tickers:
            logger.info(f"Trading earnings straddles on ETFs: {', '.join(etf_tickers)}")
        
        # Enforce use of micro options where possible
        use_micro_options = self.config.get("use_micro_options", True)
        logger.info(f"Trading with {'micro-sized' if use_micro_options else 'standard'} option positions")
        
        if not use_micro_options:
            logger.warning("WARNING: Using standard option contracts may require increased margin!")
        
        try:
            # Get upcoming earnings announcements
            earnings = self.get_upcoming_earnings()
            
            for earning in earnings:
                try:
                    ticker = earning['ticker']
                    earning_date = earning['date']
                    earning_time = earning['time']
                    
                    # Check if we already traded this ticker recently
                    if ticker in self.last_trade_time:
                        last_trade = self.last_trade_time[ticker]
                        now = datetime.datetime.now(self.eastern_tz)
                        # Skip if we traded this ticker within the last 24 hours
                        if (now - last_trade).total_seconds() < 86400:
                            logger.info(f"Already traded {ticker} recently, skipping")
                            continue
                    
                    # Get market data and calculate IV rank
                    market_data = self.get_market_data(ticker)
                    
                    if not market_data or 'last' not in market_data or market_data['last'] is None:
                        logger.warning(f"Insufficient market data for {ticker}, skipping")
                        continue
                        
                    # Check price limits
                    current_price = market_data['last']
                    min_price = self.config.get('min_price', 50)
                    max_price = self.config.get('max_price', 500)
                    
                    # Different handling for stocks vs ETFs
                    is_etf = ticker in ["SPY", "QQQ", "IWM", "XLF", "EEM", "XLE", "SQQQ", "TQQQ"]
                    
                    if current_price < min_price or current_price > max_price:
                        if is_etf:
                            logger.info(f"ETF {ticker} price (${current_price}) is outside limits (${min_price}-${max_price}), skipping")
                        else:
                            logger.info(f"Stock {ticker} price (${current_price}) is outside limits (${min_price}-${max_price}), skipping")
                        continue
                    else:
                        logger.info(f"Price of {ticker} (${current_price}) is within acceptable range")
                        if current_price > 200 and not is_etf:
                            logger.warning(f"Stock {ticker} is high-priced (${current_price}). Using fractional position sizing.")
                        
                        if ticker in ["AMZN", "GOOGL", "GOOG"] and current_price > 1000:
                            logger.warning(f"Ultra high-priced stock {ticker} detected. Extra caution with position sizing.")
                            max_capital = self.config.get('max_capital_per_trade', 150) * 0.5  # Only use half allocation for ultra-expensive stocks
                            logger.info(f"Reducing allocation for {ticker} to ${max_capital} due to high share price")
                    
                    # Check IV rank requirement if we have it
                    iv_rank = market_data.get('iv_rank')
                    min_iv_rank = self.config.get('min_iv_rank', 30)
                    
                    if iv_rank is not None and iv_rank < min_iv_rank:
                        logger.info(f"IV rank for {ticker} ({iv_rank:.1f}) is below minimum ({min_iv_rank}), skipping")
                        continue
                        
                    # Get option chains
                    max_days = self.config.get('max_days_to_expiry', 5)
                    chains = self.get_option_chains(ticker, max_days)
                    
                    if not chains:
                        logger.warning(f"No suitable option chains found for {ticker}, skipping")
                        continue
                        
                    # Find the best expiration date (closest after earnings)
                    best_expiry = None
                    best_chain = None
                    min_days_diff = float('inf')
                    
                    for chain, expiration in chains:
                        expiry_date = datetime.datetime.strptime(expiration, "%Y%m%d").date()
                        days_diff = (expiry_date - earning_date).days
                        
                        # Skip expirations before earnings
                        if days_diff < 0:
                            continue
                            
                        if days_diff < min_days_diff:
                            min_days_diff = days_diff
                            best_expiry = expiration
                            best_chain = chain
                    
                    if best_expiry is None:
                        logger.warning(f"No suitable expiration found for {ticker} earnings on {earning_date}")
                        continue
                        
                    # Find ATM strike for the straddle
                    strikes = sorted(best_chain.strikes)
                    current_price = market_data['last']
                    
                    # Find strike closest to current price
                    atm_strike = min(strikes, key=lambda x: abs(x - current_price))
                    
                    # Create option contracts for the straddle
                    call_contract = Option(
                        ticker, best_expiry, atm_strike, 'C', 'SMART',
                        tradingClass=best_chain.tradingClass
                    )
                    
                    put_contract = Option(
                        ticker, best_expiry, atm_strike, 'P', 'SMART',
                        tradingClass=best_chain.tradingClass
                    )
                    
                    # Qualify contracts
                    qualified_contracts = self.ib.qualifyContracts(call_contract, put_contract)
                    
                    if len(qualified_contracts) < 2:
                        logger.error(f"Could not qualify option contracts for {ticker} straddle")
                        continue
                        
                    call_contract, put_contract = qualified_contracts
                    
                    # Get option prices
                    call_price = self.calculate_option_price(call_contract)
                    put_price = self.calculate_option_price(put_contract)
                    
                    if call_price == 0 or put_price == 0:
                        logger.warning(f"Could not get valid prices for {ticker} options, skipping")
                        continue
                        
                    # Calculate total straddle cost
                    total_cost = (call_price + put_price) * 100  # Convert to dollars (100 shares per contract)
                    
                    # Check if within budget
                    max_capital = self.config.get('max_capital_per_trade', 150)
                    
                    if total_cost > max_capital:
                        logger.info(f"Straddle for {ticker} costs ${total_cost:.2f}, exceeds max capital ${max_capital}")
                        # Check if we can use micro contracts instead
                        if self.config.get('use_micro_options', True):
                            # Calculate fractional quantity to stay within budget
                            # For example, if budget is $150 and contract costs $300, use 0.5 contracts (micro)
                            contract_multiplier = min(1.0, max_capital / total_cost)
                            if contract_multiplier >= 0.1:  # Minimum 1/10th contract equivalent
                                adjusted_cost = total_cost * contract_multiplier
                                logger.info(f"Using {contract_multiplier:.2f} contract units for {ticker}, cost: ${adjusted_cost:.2f}")
                            else:
                                logger.info(f"Even with micro options, {ticker} straddle is too expensive, skipping")
                                continue
                        else:
                            logger.warning(f"Straddle for {ticker} costs ${total_cost:.2f}, exceeds budget. Skipping to avoid margin usage.")
                            continue
                    
                    # Add this opportunity to our list
                    opportunities.append({
                        'ticker': ticker,
                        'earning_date': earning_date,
                        'earning_time': earning_time,
                        'expiry_date': datetime.datetime.strptime(best_expiry, "%Y%m%d").date(),
                        'strike': atm_strike,
                        'call_contract': call_contract,
                        'put_contract': put_contract,
                        'call_price': call_price,
                        'put_price': put_price,
                        'total_cost': total_cost,
                        'current_price': current_price,
                        'iv_rank': iv_rank
                    })
                    
                    logger.info(f"Found straddle opportunity for {ticker} - Total cost: ${total_cost:.2f}")
                    
                except Exception as e:
                    logger.error(f"Error processing earnings opportunity for {ticker}: {e}")
                    continue
            
            # Sort opportunities by IV rank (highest first)
            opportunities.sort(key=lambda x: x.get('iv_rank', 0) or 0, reverse=True)
            
        except Exception as e:
            logger.error(f"Error finding straddle opportunities: {e}")
            
        return opportunities
    
    def execute_straddle(self, opportunity: Dict) -> bool:
        """Execute a straddle trade based on the provided opportunity."""
        try:
            ticker = opportunity['ticker']
            call_contract = opportunity['call_contract']
            put_contract = opportunity['put_contract']
            call_price = opportunity['call_price']
            put_price = opportunity['put_price']
            
            # Calculate how many contracts we can afford
            max_capital = self.config.get('max_capital_per_trade', 150)
            total_price_per_pair = (call_price + put_price) * 100
            
            # If using micro options, use fractional quantities to stay within budget
            if self.config.get('use_micro_options', True):
                # Always use fractional quantity - no more than 1 full contract
                quantity_fraction = min(1.0, max_capital / total_price_per_pair)
                quantity = max(0.1, round(quantity_fraction, 1))  # Round to nearest 0.1
                logger.info(f"Using {quantity:.1f} contract units for {ticker} straddle (micro-sized approach)")
                
                # The actual IBKR API requires whole numbers, so for simulated micro contracts:
                # We'll use 1 contract but mentally track the fraction
                quantity_for_order = 1
            else:
                # Standard approach with whole contracts
                quantity = max(1, int(max_capital / total_price_per_pair))
                if quantity > 1:
                    logger.warning(f"Using {quantity} FULL SIZE contracts for {ticker} straddle - consider switching to micro options")
                quantity_for_order = quantity
            
            # Execute call leg first
            call_order = MarketOrder('BUY', quantity_for_order)
            call_trade = self.ib.placeOrder(call_contract, call_order)
            self.ib.sleep(1)
            
            if call_trade.orderStatus.status not in ['Filled', 'Submitted', 'PreSubmitted']:
                logger.error(f"Call leg failed for {ticker}: {call_trade.orderStatus.status}")
                return False
                
            logger.info(f"Call leg executed for {ticker}: {quantity_for_order} contracts at ~${call_price:.2f} (effective size: {quantity:.1f})")
            
            # Now execute put leg
            put_order = MarketOrder('BUY', quantity_for_order)
            put_trade = self.ib.placeOrder(put_contract, put_order)
            self.ib.sleep(1)
            
            if put_trade.orderStatus.status not in ['Filled', 'Submitted', 'PreSubmitted']:
                logger.error(f"Put leg failed for {ticker}: {put_trade.orderStatus.status}")
                # Try to close the call leg as we don't want just one side
                self.ib.placeOrder(call_contract, MarketOrder('SELL', quantity_for_order))
                return False
                
            logger.info(f"Put leg executed for {ticker}: {quantity_for_order} contracts at ~${put_price:.2f} (effective size: {quantity:.1f})")
            logger.warning(f"Total capital used for {ticker} straddle: ${(call_price + put_price) * 100 * quantity:.2f}")
            if self.config.get('use_micro_options', True) and quantity < 1.0:
                logger.info(f"Using micro-sized position ({quantity:.1f} units) - reduced capital usage")
            else:
                logger.info(f"Using standard position sizing")
            
            # Record the trade
            trade_id = f"{ticker}_{datetime.datetime.now(self.eastern_tz).strftime('%Y%m%d_%H%M%S')}"
            
            # Create target exit date based on configuration
            exit_days_after = self.config.get('exit_days_after', 1)
            target_exit_date = opportunity['earning_date'] + datetime.timedelta(days=exit_days_after)
            
            # Track position
            self.open_positions[trade_id] = {
                'ticker': ticker,
                'call_contract': call_contract,
                'put_contract': put_contract,
                'quantity': quantity_for_order,  # Actual order quantity
                'effective_quantity': quantity,   # Effective position size (may be fractional)
                'entry_time': datetime.datetime.now(self.eastern_tz),
                'call_entry_price': call_price,
                'put_entry_price': put_price,
                'total_cost': total_price_per_pair * quantity,  # Effective cost based on fractional size
                'earnings_date': opportunity['earning_date'],
                'expiry_date': opportunity['expiry_date'],
                'target_exit_date': target_exit_date,  # When we plan to exit after earnings
                'is_micro': self.config.get('use_micro_options', True) and quantity < 1.0,
                'strike': opportunity['strike'],
                'expiration': opportunity['call_contract'].lastTradeDateOrContractMonth
            }
            
            # Save positions to file to maintain state across restarts
            self.save_positions()
            
            # Record last trade time
            self.last_trade_time[ticker] = datetime.datetime.now(self.eastern_tz)
            
            logger.info(f"Straddle position opened for {ticker} - Total cost: ${total_price_per_pair * quantity:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Error executing straddle for {ticker}: {e}")
            return False
    
    def close_position(self, position_id: str, reason: str = "Manual") -> bool:
        """Close an open straddle position."""
        try:
            if position_id not in self.open_positions:
                logger.error(f"Position {position_id} not found in open positions")
                return False
                
            position = self.open_positions[position_id]
            ticker = position['ticker']
            call_contract = position['call_contract']
            put_contract = position['put_contract']
            quantity = position['quantity']
            
            # Close call leg
            call_order = MarketOrder('SELL', quantity)
            call_trade = self.ib.placeOrder(call_contract, call_order)
            self.ib.sleep(1)
            
            call_success = call_trade.orderStatus.status in ['Filled', 'Submitted', 'PreSubmitted']
            if not call_success:
                logger.error(f"Failed to close call leg for {ticker}: {call_trade.orderStatus.status}")
            else:
                logger.info(f"Closed call leg for {ticker} - Reason: {reason}")
            
            # Close put leg
            put_order = MarketOrder('SELL', quantity)
            put_trade = self.ib.placeOrder(put_contract, put_order)
            self.ib.sleep(1)
            
            put_success = put_trade.orderStatus.status in ['Filled', 'Submitted', 'PreSubmitted']
            if not put_success:
                logger.error(f"Failed to close put leg for {ticker}: {put_trade.orderStatus.status}")
            else:
                logger.info(f"Closed put leg for {ticker} - Reason: {reason}")
            
            # If either leg was closed successfully, consider the position at least partially closed
            if call_success or put_success:
                # Remove from open positions
                del self.open_positions[position_id]
                logger.info(f"Position {position_id} closed - Reason: {reason}")
                
                # Save positions to file to maintain state across restarts
                self.save_positions()
                
                return True
            else:
                logger.error(f"Failed to close both legs of {ticker} straddle")
                return False
                
        except Exception as e:
            logger.error(f"Error closing position {position_id}: {e}")
            return False
    
    def manage_positions(self):
        """Manage open straddle positions (apply exit criteria)."""
        # First check if we have any positions to manage
        if not self.open_positions:
            return
            
        # Log all active positions
        logger.info(f"Managing {len(self.open_positions)} active positions")
        today = datetime.datetime.now(self.eastern_tz).date()
        
        for position_id, position in list(self.open_positions.items()):
            try:
                ticker = position['ticker']
                call_contract = position['call_contract']
                put_contract = position['put_contract']
                entry_time = position['entry_time']
                call_entry_price = position['call_entry_price']
                put_entry_price = position['put_entry_price']
                total_cost = position['total_cost']
                earnings_date = position['earnings_date']
                expiry_date = position['expiry_date']
                target_exit_date = position.get('target_exit_date')
                
                # Log the current position status
                logger.info(f"Position {position_id}: {ticker} straddle, earnings on {earnings_date}, expiry on {expiry_date}")
                
                # Check if it's time to exit based on target_exit_date (day after earnings)
                if target_exit_date and today >= target_exit_date:
                    logger.info(f"Target exit date reached for {ticker} (earnings was on {earnings_date}, planned exit on {target_exit_date})") 
                    self.close_position(position_id, reason="Planned Post-Earnings Exit")
                    continue
                
                # Get current prices
                current_call_price = self.calculate_option_price(call_contract)
                current_put_price = self.calculate_option_price(put_contract)
                
                # Calculate current value
                current_value = (current_call_price + current_put_price) * 100 * position['quantity']
                
                # Calculate P&L
                pnl = current_value - total_cost
                pnl_pct = (pnl / total_cost) * 100
                
                # Get current date
                now = datetime.datetime.now(self.eastern_tz)
                
                # Check exit criteria based on strategy rules
                
                # 1. Stop loss exit (default 50% loss)
                stop_loss_pct = self.config.get("stop_loss_pct", 50)
                if pnl_pct <= -stop_loss_pct:
                    logger.info(f"Stop loss triggered for {ticker} straddle: {pnl_pct:.2f}%")
                    self.close_position(position_id, reason="Stop Loss")
                    continue
                    
                # 2. Take profit exit (default 100% gain)
                take_profit_pct = self.config.get("take_profit_pct", 100)
                if pnl_pct >= take_profit_pct:
                    logger.info(f"Take profit triggered for {ticker} straddle: {pnl_pct:.2f}%")
                    self.close_position(position_id, reason="Take Profit")
                    continue
                
                # 3. Time-based exit: If earnings has passed and we're X days past
                if now.date() > earnings_date:
                    days_past_earnings = (now.date() - earnings_date).days
                    max_days_past = self.config.get("max_days_past_earnings", 2)
                    
                    if days_past_earnings >= max_days_past:
                        logger.info(f"{days_past_earnings} days past earnings for {ticker}, closing position")
                        self.close_position(position_id, reason="Post-Earnings Time Exit")
                        continue
                
                # 4. Close if approaching expiration (avoid gamma risk)
                days_to_expiry = (expiry_date - now.date()).days
                min_days_to_expiry = self.config.get("min_days_to_expiry", 1)
                
                if days_to_expiry <= min_days_to_expiry:
                    logger.info(f"Approaching expiration for {ticker} ({days_to_expiry} days left), closing position")
                    self.close_position(position_id, reason="Expiration Approaching")
                    continue
                    
            except Exception as e:
                logger.error(f"Error managing position {position_id}: {e}")
    
    def run(self):
        """Main trading loop."""
        try:
            # Connect to IB
            self.connect()
            
            logger.info("Starting main trading loop")
            
            # Send notification on startup
            self.send_notification("Earnings Straddle Bot Started", f"Running with {len(self.config.get('tickers_whitelist', []))} tickers")
            
            # Track number of trades today
            trades_today = 0
            trade_date = datetime.datetime.now(self.eastern_tz).date()
            
            while True:
                # Check if we're in trading hours (9:30 AM - 4:00 PM Eastern, weekdays)
                now = datetime.datetime.now(self.eastern_tz)
                
                # Reset trades counter on a new day
                if now.date() != trade_date:
                    trades_today = 0
                    trade_date = now.date()
                    
                # Trading hours check
                is_trading_hours = (
                    now.weekday() < 5 and  # Monday to Friday
                    ((now.hour == 9 and now.minute >= 30) or now.hour > 9) and  # After 9:30 AM
                    now.hour < 16  # Before 4:00 PM
                )
                
                if not is_trading_hours:
                    logger.info("Outside of trading hours, waiting...")
                    # Still manage positions during non-trading hours
                    self.manage_positions()
                    
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
                max_daily_trades = self.config.get("max_daily_trades", 2)
                if trades_today >= max_daily_trades:
                    logger.info(f"Reached maximum daily trades ({trades_today}), waiting for tomorrow")
                    self.ib.sleep(300)  # Wait 5 minutes before checking again
                    continue
                
                # Find trading opportunities
                opportunities = self.find_straddle_opportunities()
                
                # Execute trades for valid opportunities
                for opportunity in opportunities:
                    if trades_today >= max_daily_trades:
                        break
                        
                    # Make sure this opportunity is worth taking
                    ticker = opportunity.get('ticker')
                    iv_rank = opportunity.get('iv_rank', 0)
                    min_iv_rank = self.config.get('min_iv_rank', 30)
                    
                    if iv_rank < min_iv_rank:
                        continue
                        
                    # Send notification about straddle opportunity
                    earnings_date = opportunity.get('earning_date')
                    total_cost = opportunity.get('total_cost', 0)
                    self.send_notification(
                        "Straddle Opportunity", 
                        f"{ticker} earnings on {earnings_date}, cost: ${total_cost:.2f}"
                    )
                        
                    # Execute the straddle
                    if self.execute_straddle(opportunity):
                        trades_today += 1
                        logger.info(f"Executed straddle for {opportunity['ticker']} - {trades_today}/{max_daily_trades} trades today")
                        
                        # Send notification about executed straddle
                        self.send_notification(
                            "Straddle Executed", 
                            f"{ticker} straddle opened, earnings on {earnings_date}"
                        )
                
                # Wait before next iteration
                wait_time = self.config.get("scan_interval_seconds", 300)
                self.ib.sleep(wait_time)
                
        except KeyboardInterrupt:
            logger.info("Trading bot stopped by user")
            # Close all positions on exit
            for position_id in list(self.open_positions.keys()):
                self.close_position(position_id, reason="User Exit")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
        finally:
            # Save positions before exit
            if self.open_positions:
                self.save_positions()
                logger.info(f"Saved {len(self.open_positions)} active positions before exit")
                
            # Disconnect from IB
            if self.ib.isConnected():
                self.ib.disconnect()
                logger.info("Disconnected from IB")

def main():
    """Main entry point for the trading bot."""
    parser = argparse.ArgumentParser(description="Earnings Straddle Trading Bot for Interactive Brokers")
    
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
    
    args = parser.parse_args()
    
    # Adjust port for paper trading if specified
    if args.paper_trading and args.port == 7496:
        args.port = 7497
        logger.info("Paper trading enabled, using port 7497")
    else:
        logger.info("LIVE TRADING ENABLED - Using port 7496")
        logger.warning("CAUTION: Trading with real money. Max 1 trade per day configured.")
    
    # Create and run the trading bot
    trader = StraddleEarningsTrader(
        config_path=args.config,
        host=args.host,
        port=args.port,
        client_id=args.client_id
    )
    
    trader.run()

if __name__ == "__main__":
    main()
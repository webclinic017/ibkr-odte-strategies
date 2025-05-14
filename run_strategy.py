#!/usr/bin/env python3
"""
Script principal para ejecutar estrategias de trading con IBKR.
"""

import argparse
import logging
import os
import json
import signal
import sys
from datetime import datetime
from src.strategies.odte_breakout import ODTEBreakoutStrategy
from src.strategies.earnings_straddle import EarningsStraddleStrategy
from src.backtesting.backtest_engine import BacktestEngine

# Configurar logging global
def setup_logging():
    """Configura el logging global para la aplicación."""
    os.makedirs("logs", exist_ok=True)
    
    log_file = f"logs/strategy_runner_{datetime.now().strftime('%Y%m%d')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger('StrategyRunner')

# Cargar configuración
def load_config(config_path):
    """Carga la configuración desde un archivo JSON."""
    if not os.path.exists(config_path):
        return {}
        
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error al cargar configuración: {e}")
        return {}

# Manejador de señales para cierre ordenado
def signal_handler(signum, frame):
    """Maneja señales para un cierre ordenado de la aplicación."""
    logging.info("Señal de interrupción recibida. Cerrando estrategias...")
    
    if 'active_strategy' in globals() and active_strategy:
        active_strategy.stop()
        
    sys.exit(0)

# Comando principal para ejecutar estrategias
def run_strategy(args):
    """Ejecuta una estrategia de trading."""
    global active_strategy
    
    logger = logging.getLogger('run_strategy')
    logger.info(f"Iniciando estrategia: {args.strategy}")
    
    # Cargar configuración
    config_path = args.config or f"config/{args.strategy.lower()}_config.json"
    config = load_config(config_path)
    
    # Instanciar estrategia seleccionada
    if args.strategy == 'odte_breakout':
        strategy = ODTEBreakoutStrategy(config)
    elif args.strategy == 'earnings_straddle':
        strategy = EarningsStraddleStrategy(config)
    else:
        logger.error(f"Estrategia desconocida: {args.strategy}")
        return
    
    # Iniciar y ejecutar estrategia
    strategy.start()
    active_strategy = strategy
    
    try:
        strategy.run()
    except KeyboardInterrupt:
        logger.info("Interrupción manual recibida. Deteniendo estrategia...")
    except Exception as e:
        logger.error(f"Error al ejecutar estrategia: {e}")
    finally:
        strategy.stop()
        active_strategy = None

# Comando para backtesting
def run_backtest(args):
    """Ejecuta backtesting para una estrategia."""
    logger = logging.getLogger('run_backtest')
    logger.info(f"Iniciando backtesting para: {args.strategy}")
    
    # Cargar configuración
    config_path = args.config or f"config/{args.strategy.lower()}_config.json"
    config = load_config(config_path)
    
    # Validar fechas
    if not args.start_date:
        logger.error("Se requiere fecha de inicio para el backtesting")
        return
        
    # Crear motor de backtesting
    backtest = BacktestEngine(
        args.strategy,
        args.start_date,
        args.end_date,
        args.capital
    )
    
    # Ejecutar backtesting según estrategia
    if args.strategy == 'odte_breakout':
        metrics = backtest.backtest_odte_breakout(config)
    elif args.strategy == 'earnings_straddle':
        metrics = backtest.backtest_earnings_straddle(config)
    else:
        logger.error(f"Estrategia desconocida para backtesting: {args.strategy}")
        return
    
    if metrics:
        logger.info(f"Backtesting completado. Resultados guardados en {backtest.results_dir}")
    else:
        logger.error("Error al ejecutar backtesting")

# Comando para inicializar configuración
def init_config(args):
    """Inicializa archivos de configuración para estrategias."""
    logger = logging.getLogger('init_config')
    
    os.makedirs("config", exist_ok=True)
    
    # Configuración para ODTE Breakout
    odte_config = {
        "tickers": ["SPY", "QQQ", "TSLA", "NVDA", "META", "AMD", "AMZN", "AAPL"],
        "max_capital": 10000,
        "risk_per_trade": 100,
        "min_volume": 500,
        "min_open_interest": 1000,
        "polygon_api_key": "TU_API_KEY_AQUI",
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 7497,
        "ibkr_client_id": 1,
        "orders_file": "data/odte_breakout_orders.json",
        "log_file": "data/odte_breakout_trades.csv",
        "scan_interval": 60,
        "volume_multiplier": 1.2,
        "tp_multiplier": 1.2,
        "sl_multiplier": 0.6
    }
    
    # Configuración para Earnings Straddle
    straddle_config = {
        "tickers_whitelist": [
            "TSLA", "NFLX", "NVDA", "AMD", "META", "AMZN", 
            "BABA", "SHOP", "ROKU", "COIN", "MSFT", "AAPL"
        ],
        "max_capital_per_trade": 500,
        "polygon_api_key": "TU_API_KEY_AQUI",
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 7497,
        "ibkr_client_id": 2,
        "data_dir": "data/earnings",
        "scan_interval": 3600,
        "auto_close_time": "14:35",
        "entry_days_before": 1,
        "exit_days_after": 1
    }
    
    # Guardar configuraciones
    with open("config/odte_breakout_config.json", "w") as f:
        json.dump(odte_config, f, indent=2)
        
    with open("config/earnings_straddle_config.json", "w") as f:
        json.dump(straddle_config, f, indent=2)
        
    logger.info("Archivos de configuración inicializados en el directorio 'config'")
    logger.info("Recuerda editar los archivos para configurar tus API keys y parámetros de trading")

if __name__ == "__main__":
    # Configurar manejo de señales
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Variable global para la estrategia activa
    active_strategy = None
    
    # Configurar logging
    logger = setup_logging()
    
    # Configurar parser de argumentos
    parser = argparse.ArgumentParser(description='Ejecutor de Estrategias de Trading con IBKR')
    subparsers = parser.add_subparsers(dest='command', help='Comando a ejecutar')
    
    # Subcomando para ejecutar estrategia
    run_parser = subparsers.add_parser('run', help='Ejecutar una estrategia')
    run_parser.add_argument('strategy', choices=['odte_breakout', 'earnings_straddle'], 
                          help='Estrategia a ejecutar')
    run_parser.add_argument('-c', '--config', help='Ruta al archivo de configuración')
    
    # Subcomando para backtesting
    backtest_parser = subparsers.add_parser('backtest', help='Ejecutar backtesting')
    backtest_parser.add_argument('strategy', choices=['odte_breakout', 'earnings_straddle'], 
                               help='Estrategia para backtesting')
    backtest_parser.add_argument('-s', '--start-date', required=True, 
                               help='Fecha de inicio (YYYY-MM-DD)')
    backtest_parser.add_argument('-e', '--end-date', 
                               help='Fecha fin (YYYY-MM-DD, default=hoy)')
    backtest_parser.add_argument('-c', '--config', 
                               help='Ruta al archivo de configuración')
    backtest_parser.add_argument('--capital', type=float, default=10000,
                               help='Capital inicial para el backtesting')
    
    # Subcomando para inicializar configuración
    init_parser = subparsers.add_parser('init', help='Inicializar archivos de configuración')
    
    # Parsear argumentos
    args = parser.parse_args()
    
    # Ejecutar comando solicitado
    if args.command == 'run':
        run_strategy(args)
    elif args.command == 'backtest':
        run_backtest(args)
    elif args.command == 'init':
        init_config(args)
    else:
        parser.print_help()
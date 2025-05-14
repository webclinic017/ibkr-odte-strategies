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
import threading
import time
import asyncio
from datetime import datetime
from src.strategies.odte_breakout import ODTEBreakoutStrategy
from src.strategies.earnings_straddle import EarningsStraddleStrategy
from src.backtesting.backtest_engine import BacktestEngine
from src.core.ibkr_connection import IBKRConnection

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

# Variables globales para estrategias activas
active_strategies = {}

# Manejador de señales para cierre ordenado
def signal_handler(signum, frame):
    """Maneja señales para un cierre ordenado de la aplicación."""
    logging.info("Señal de interrupción recibida. Cerrando estrategias...")
    
    for name, strategy in active_strategies.items():
        logging.info(f"Deteniendo estrategia: {name}")
        strategy.stop()
    
    # Limpiar todas las conexiones IBKR
    IBKRConnection.cleanup_all()
    
    sys.exit(0)

# Función para ejecutar una estrategia en su propio hilo
def run_strategy_thread(strategy_name, config):
    """Ejecuta una estrategia en un hilo separado."""
    # Configurar el event loop para este hilo
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    logger = logging.getLogger(f'strategy_thread.{strategy_name}')
    logger.info(f"Iniciando hilo para estrategia: {strategy_name}")
    
    try:
        # Asegurar que client_id es un entero
        if 'ibkr_client_id' in config:
            config['ibkr_client_id'] = int(config['ibkr_client_id'])
        
        # Instanciar estrategia seleccionada
        if strategy_name == 'odte_breakout':
            strategy = ODTEBreakoutStrategy(config)
        elif strategy_name == 'earnings_straddle':
            strategy = EarningsStraddleStrategy(config)
        else:
            logger.error(f"Estrategia desconocida: {strategy_name}")
            return
        
        # Iniciar estrategia
        strategy.start()
        active_strategies[strategy_name] = strategy
        
        try:
            strategy.run()
        except Exception as e:
            logger.error(f"Error en estrategia {strategy_name}: {e}")
        finally:
            strategy.stop()
            if strategy_name in active_strategies:
                del active_strategies[strategy_name]
    except Exception as e:
        logger.error(f"Error al inicializar estrategia {strategy_name}: {e}")
    finally:
        loop.close()

# Comando principal para ejecutar estrategias
def run_strategies(args):
    """Ejecuta una o varias estrategias de trading."""
    logger = logging.getLogger('run_strategies')
    
    # Determinar qué estrategias ejecutar
    strategies_to_run = []
    
    if args.strategy == 'all':
        strategies_to_run = ['odte_breakout', 'earnings_straddle']
        logger.info(f"Iniciando todas las estrategias disponibles: {strategies_to_run}")
    else:
        strategies_to_run = [args.strategy]
        logger.info(f"Iniciando estrategia: {args.strategy}")
    
    # Crear hilos para cada estrategia
    threads = []
    
    for strategy_name in strategies_to_run:
        # Cargar configuración
        config_path = args.config or f"config/{strategy_name.lower()}_config.json"
        config = load_config(config_path)
        
        if not config:
            logger.error(f"No se pudo cargar la configuración para {strategy_name}. Saltando...")
            continue
            
        # Si es la estrategia earnings_straddle y se ejecuta junto con otra,
        # asegurar que use un client_id diferente
        if strategy_name == 'earnings_straddle' and len(strategies_to_run) > 1:
            if 'ibkr_client_id' in config:
                config['ibkr_client_id'] = 2  # Usar ID 2 para evitar conflictos
        
        # Crear y comenzar el hilo
        thread = threading.Thread(
            target=run_strategy_thread,
            args=(strategy_name, config),
            name=f"Thread-{strategy_name}"
        )
        thread.daemon = True  # Hilo daemon para que termine con el proceso principal
        thread.start()
        
        threads.append(thread)
        logger.info(f"Hilo iniciado para estrategia: {strategy_name}")
    
    # Mantener el proceso principal ejecutándose
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Interrupción manual recibida. Deteniendo estrategias...")
        signal_handler(signal.SIGINT, None)

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
        "tickers": ["SPY", "QQQ", "TSLA", "NVDA", "META", "AMD", "AMZN", "AAPL", "GOOGL", "COIN", "SQ"],
        "max_capital": 10000,
        "risk_per_trade": 100,
        "min_volume": 200,         # Reducido para mayor sensibilidad
        "min_open_interest": 500,  # Reducido para mayor sensibilidad
        "polygon_api_key": "TU_API_KEY_AQUI",
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 7497,
        "ibkr_client_id": 1,
        "orders_file": "data/odte_breakout_orders.json",
        "log_file": "data/odte_breakout_trades.csv",
        "scan_interval": 60,
        "volume_multiplier": 0.9,   # Reducido para mayor sensibilidad
        "tp_multiplier": 1.5,      # Aumentado para mejor rendimiento
        "sl_multiplier": 0.7,      # Ajustado para mejor gestión de riesgo
        "max_daily_trades": 3,     # Máximo número de trades por día
        "min_score": 50           # Umbral reducido para mayor sensibilidad
    }
    
    # Configuración para Earnings Straddle
    straddle_config = {
        "tickers_whitelist": [
            "TSLA", "NFLX", "NVDA", "AMD", "META", "AMZN", 
            "BABA", "SHOP", "ROKU", "COIN", "MSFT", "AAPL",
            "GOOGL", "ADBE", "CRM", "ZM", "PYPL", "SQ", "SNAP"
        ],
        "max_capital_per_trade": 500,
        "polygon_api_key": "TU_API_KEY_AQUI",
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 7497,
        "ibkr_client_id": 2,
        "data_dir": "data/earnings",
        "scan_interval": 1800,       # Reducido a 30 minutos
        "auto_close_time": "14:35",
        "entry_days_before": 1,      
        "exit_days_after": 1,
        "min_iv_rank": 35,           # Reducido para mayor sensibilidad
        "max_days_to_expiry": 7,     # Expiración máxima extendida
        "use_simulation": True,      # Usar datos simulados
        "max_daily_trades": 3,       # Máximo número de straddles por día
        "same_day_entry": True,      # Permitir entrar el mismo día
        "extended_hours": True       # Incluir horas extendidas para más oportunidades
    }
    
    # Guardar configuraciones
    with open("config/odte_breakout_config.json", "w") as f:
        json.dump(odte_config, f, indent=2)
        
    with open("config/earnings_straddle_config.json", "w") as f:
        json.dump(straddle_config, f, indent=2)
        
    logger.info("Archivos de configuración inicializados en el directorio 'config'")
    logger.info("Recuerda editar los archivos para configurar tus API keys y parámetros de trading")

# Comando para listar estrategias activas
def list_strategies(args):
    """Lista las estrategias activas y su estado."""
    logger = logging.getLogger('list_strategies')
    
    if not active_strategies:
        logger.info("No hay estrategias activas en este momento")
        return
    
    logger.info("Estrategias activas:")
    for name, strategy in active_strategies.items():
        status = "Activa" if strategy.active else "Inactiva"
        client_id = "?" 
        try:
            if hasattr(strategy, 'ibkr') and hasattr(strategy.ibkr, 'client_id'):
                client_id = strategy.ibkr.client_id
        except:
            pass
        logger.info(f"- {name}: {status} (IBKR client_id: {client_id})")

if __name__ == "__main__":
    # Configurar manejo de señales
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Configurar logging
    logger = setup_logging()
    
    # Configurar parser de argumentos
    parser = argparse.ArgumentParser(description='Ejecutor de Estrategias de Trading con IBKR')
    subparsers = parser.add_subparsers(dest='command', help='Comando a ejecutar')
    
    # Subcomando para ejecutar estrategia
    run_parser = subparsers.add_parser('run', help='Ejecutar una estrategia')
    run_parser.add_argument('strategy', choices=['odte_breakout', 'earnings_straddle', 'all'], 
                          help='Estrategia a ejecutar (usar "all" para todas)')
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
    
    # Subcomando para listar estrategias activas
    list_parser = subparsers.add_parser('list', help='Listar estrategias activas')
    
    # Parsear argumentos
    args = parser.parse_args()
    
    # Ejecutar comando solicitado
    if args.command == 'run':
        run_strategies(args)
    elif args.command == 'backtest':
        run_backtest(args)
    elif args.command == 'init':
        init_config(args)
    elif args.command == 'list':
        list_strategies(args)
    else:
        parser.print_help()
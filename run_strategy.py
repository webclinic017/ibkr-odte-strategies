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
import colorama
from datetime import datetime
from src.strategies.odte_breakout import ODTEBreakoutStrategy
from src.strategies.earnings_straddle import EarningsStraddleStrategy
from src.backtesting.backtest_engine import BacktestEngine
from src.core.ibkr_connection import IBKRConnection

# Inicializar colorama para colores en terminal
colorama.init()

# Crear un formateador colorido para los mensajes de error
class ColoredFormatter(logging.Formatter):
    def format(self, record):
        # Formato base
        log_message = super().format(record)
        
        # Aplicar colores solo para ERROR y WARNING
        if record.levelno >= logging.ERROR:
            # Rojo para ERROR y CRITICAL
            return f"{colorama.Fore.RED}{log_message}{colorama.Style.RESET_ALL}"
        elif record.levelno >= logging.WARNING:
            # Amarillo para WARNING
            return f"{colorama.Fore.YELLOW}{log_message}{colorama.Style.RESET_ALL}"
        else:
            # Sin color para INFO y DEBUG
            return log_message

# Configurar logging global
def setup_logging():
    """Configura el logging global para la aplicación."""
    os.makedirs("logs", exist_ok=True)
    
    log_file = f"logs/strategy_runner_{datetime.now().strftime('%Y%m%d')}.log"
    
    # Configuración básica de logging
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Limpiar handlers existentes
    for handler in root_logger.handlers[:]: 
        root_logger.removeHandler(handler)
    
    # Crear handler para archivo (sin colores)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Crear handler para consola (con colores)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = ColoredFormatter('[%(asctime)s] %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    
    # Agregar handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
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

# Comando para cerrar todas las posiciones
def close_positions(args):
    """Cierra todas las posiciones abiertas o de una estrategia específica."""
    logger = logging.getLogger('close_positions')
    
    # Determinar si cerramos posiciones de una estrategia específica o todas
    if args.strategy != 'all':
        # Cerrar posiciones de una estrategia específica
        logger.info(f"Cerrando posiciones de la estrategia: {args.strategy}")
        
        # Inicializar la conexión IBKR
        client_id = args.client_id or 1
        ibkr = IBKRConnection(client_id=client_id)
        if not ibkr.connect():
            logger.error("No se pudo conectar a IBKR. Verifica que TWS o IB Gateway está en ejecución.")
            return
            
        # Inicializar la estrategia correspondiente
        strategy = None
        if args.strategy == 'odte_breakout':
            # Cargar configuración
            config_path = args.config or f"config/{args.strategy.lower()}_config.json"
            config = load_config(config_path)
            if not config:
                logger.error(f"No se pudo cargar la configuración para {args.strategy}")
                return
                
            # Verificar que client_id sea un entero
            if 'ibkr_client_id' in config:
                config['ibkr_client_id'] = int(config['ibkr_client_id'])
                
            # Crear estrategia
            strategy = ODTEBreakoutStrategy(config)
            
            # Cerrar todas las posiciones de esta estrategia
            logger.info("Cerrando todas las posiciones de ODTE Breakout")
            try:
                strategy.close_all_positions()
                logger.info("Todas las posiciones cerradas exitosamente")
            except Exception as e:
                logger.error(f"Error al cerrar posiciones: {e}")
                
        elif args.strategy == 'earnings_straddle':
            # Cargar configuración
            config_path = args.config or f"config/{args.strategy.lower()}_config.json"
            config = load_config(config_path)
            if not config:
                logger.error(f"No se pudo cargar la configuración para {args.strategy}")
                return
                
            # Verificar que client_id sea un entero
            if 'ibkr_client_id' in config:
                config['ibkr_client_id'] = int(config['ibkr_client_id'])
                
            # Crear estrategia
            strategy = EarningsStraddleStrategy(config)
            
            # Cerrar todos los straddles activos
            logger.info("Cerrando todos los straddles activos")
            for ticker, straddle in list(strategy.active_straddles.items()):
                if straddle["status"] == "OPEN":
                    try:
                        logger.info(f"Cerrando straddle para {ticker}")
                        strategy.close_straddle(ticker)
                    except Exception as e:
                        logger.error(f"Error al cerrar straddle para {ticker}: {e}")
                        
            logger.info("Todos los straddles activos han sido cerrados")
        else:
            logger.error(f"Estrategia desconocida: {args.strategy}")
            return
    else:
        # Cerrar todas las posiciones en IBKR
        logger.info("Cerrando todas las posiciones abiertas en IBKR")
        
        # Inicializar la conexión IBKR
        client_id = args.client_id or 1
        ibkr = IBKRConnection(client_id=client_id)
        if not ibkr.connect():
            logger.error("No se pudo conectar a IBKR. Verifica que TWS o IB Gateway está en ejecución.")
            return
            
        # Obtener todas las posiciones abiertas
        try:
            positions = ibkr.ib.positions()
            if not positions:
                logger.info("No hay posiciones abiertas en IBKR")
                return
                
            logger.info(f"Se encontraron {len(positions)} posiciones abiertas")
            
            # Cerrar cada posición
            for position in positions:
                contract = position.contract
                quantity = position.position
                
                if quantity == 0:
                    continue  # Saltar posiciones con cantidad 0
                    
                logger.info(f"Cerrando posición: {contract.symbol} {contract.secType} {quantity} unidades")
                
                # Crear y enviar orden de cierre
                from ib_insync import MarketOrder
                
                # Si la cantidad es positiva, vendemos; si es negativa, compramos
                action = "SELL" if quantity > 0 else "BUY"
                qty = abs(quantity)
                
                # Obtener el exchange apropiado para este contrato
                exchange = contract.exchange
                if not exchange or exchange == 'SMART':
                    # Para futuros, necesitamos un exchange específico
                    if contract.secType == 'FUT':
                        # Intentar obtener primaryExchange o usar el exchange por defecto según el producto
                        if hasattr(contract, 'primaryExchange') and contract.primaryExchange:
                            exchange = contract.primaryExchange
                        elif contract.symbol in ['ES', 'MES', 'NQ', 'MNQ', 'YM', 'MYM']:
                            exchange = 'GLOBEX'  # Para futuros de índices CME
                        elif contract.symbol in ['CL', 'GC', 'SI', 'HG']:
                            exchange = 'NYMEX'  # Para futuros de commodities
                        else:
                            # Intentar obtenerlo desde los detalles del contrato
                            try:
                                details = ibkr.ib.reqContractDetails(contract)
                                if details and details[0].marketName:
                                    exchange = details[0].marketName
                                else:
                                    exchange = 'GLOBEX'  # Usar GLOBEX como fallback
                            except:
                                exchange = 'GLOBEX'  # Fallback si todo lo demás falla
                
                # Asegurarse de que el contrato tenga el exchange correcto
                contract.exchange = exchange
                
                # Crear y enviar la orden
                try:
                    order = MarketOrder(action, qty)
                    trade = ibkr.ib.placeOrder(contract, order)
                    ibkr.ib.sleep(1)  # Pequeña pausa
                    
                    # Verificar estado de la orden
                    order_status = trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'Unknown'
                    logger.info(f"Orden de cierre enviada para {contract.symbol} ({contract.secType}, exchange: {exchange}). Estado: {order_status}")
                except Exception as order_e:
                    logger.error(f"Error al enviar orden para {contract.symbol}: {order_e}")
                    # Intentar con un enfoque alternativo si es un futuro
                    if contract.secType == 'FUT':
                        try:
                            logger.info(f"Intentando cerrar futuro {contract.symbol} con método alternativo")
                            # Crear un nuevo contrato con todos los detalles necesarios explícitamente
                            from ib_insync import Future
                            new_contract = Future(symbol=contract.symbol, 
                                                 lastTradeDateOrContractMonth=contract.lastTradeDateOrContractMonth,
                                                 exchange=exchange,
                                                 currency=contract.currency,
                                                 multiplier=contract.multiplier if hasattr(contract, 'multiplier') else None)
                            
                            # Calificar el contrato para asegurarnos de que esté completo
                            ibkr.ib.qualifyContracts(new_contract)
                            
                            # Crear y enviar la orden con el contrato completo
                            new_order = MarketOrder(action, qty)
                            new_trade = ibkr.ib.placeOrder(new_contract, new_order)
                            ibkr.ib.sleep(1)
                            
                            logger.info(f"Orden alternativa enviada para futuro {contract.symbol}")
                        except Exception as alt_e:
                            logger.error(f"También falló el método alternativo para {contract.symbol}: {alt_e}")
                    
                
            logger.info("Todas las posiciones han sido cerradas o se han enviado órdenes de cierre")
            
        except Exception as e:
            logger.error(f"Error al cerrar posiciones: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    # Asegurarnos de cerrar la conexión IBKR al finalizar
    IBKRConnection.cleanup_all()

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
    
    # Subcomando para cerrar posiciones
    close_parser = subparsers.add_parser('close', help='Cerrar posiciones abiertas')
    close_parser.add_argument('strategy', choices=['odte_breakout', 'earnings_straddle', 'all'],
                           help='Estrategia cuyas posiciones cerrar ("all" para todas)')
    close_parser.add_argument('-c', '--config', help='Ruta al archivo de configuración')
    close_parser.add_argument('--client-id', type=int, help='ID de cliente para IBKR')
    
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
    elif args.command == 'close':
        close_positions(args)
    else:
        parser.print_help()
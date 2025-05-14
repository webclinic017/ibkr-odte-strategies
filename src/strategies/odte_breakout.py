from ..core.strategy_base import StrategyBase
from ..core.options_utils import create_option_contract, get_option_expiry
from ib_insync import MarketOrder, Stock
import json
import os
import csv
from datetime import datetime
import time
import logging
import colorama

# Inicializar colorama para colores en terminal
colorama.init()

# Crear un formateador colorido para los mensajes de error
class ColoredFormatter(logging.Formatter):
    def format(self, record):
        # Formato base
        log_message = super().format(record)
        
        # Aplicar colores según el nivel
        if record.levelno >= logging.ERROR:
            # Rojo para ERROR y CRITICAL
            return f"{colorama.Fore.RED}{log_message}{colorama.Style.RESET_ALL}"
        elif record.levelno >= logging.WARNING:
            # Amarillo para WARNING
            return f"{colorama.Fore.YELLOW}{log_message}{colorama.Style.RESET_ALL}"
        elif record.levelno >= logging.INFO:
            # Verde para INFO
            return f"{colorama.Fore.GREEN}{log_message}{colorama.Style.RESET_ALL}"
        else:
            # Cyan para DEBUG
            return f"{colorama.Fore.CYAN}{log_message}{colorama.Style.RESET_ALL}"

class ODTEBreakoutStrategy(StrategyBase):
    """
    Estrategia para operar breakouts en opciones de 0 DTE.
    Basada en movimientos de precio y volumen por encima/debajo de un rango inicial.
    """
    
    def __init__(self, config=None):
        super().__init__(name="ODTE_Breakout", config=config)
        
        # Configuración por defecto
        self.default_config = {
            "tickers": ["SPY", "QQQ", "TSLA", "NVDA", "META", "AMD", "AMZN", "AAPL"],
            "max_capital": 10000,
            "risk_per_trade": 100,
            "min_volume": 200,         # Reducido para mayor sensibilidad
            "min_open_interest": 500,  # Reducido para mayor sensibilidad
            "orders_file": "data/odte_breakout_orders.json",
            "log_file": "data/odte_breakout_trades.csv",
            "scan_interval": 60,       # segundos
            "volume_multiplier": 0.9,   # Reducido para mayor sensibilidad
            "tp_multiplier": 1.5,      # Aumentado para mejor rendimiento
            "sl_multiplier": 0.7,      # Ajustado para mejor gestión de riesgo
            "max_daily_trades": 3,     # Máximo número de trades por día
            "min_score": 50           # Puntaje mínimo reducido para mayor sensibilidad
        }
        
        # Combinar configuración personalizada con valores por defecto
        self.config = {**self.default_config, **(config or {})}
        
        # Estado interno de la estrategia
        self.initial_ranges = {}    # Rangos iniciales por ticker
        self.active_trades = {}     # Trades activos
        self.market_trends = {}     # Tendencias de mercado por ticker
        self.daily_trades_count = 0 # Contador de trades diarios
        
        # Para seguimiento de rentabilidad
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        
        # Crear directorios de datos si no existen
        os.makedirs("data", exist_ok=True)
        
        # Inicializar objeto MarketData
        from ..core.market_data import MarketData
        self.market_data = MarketData(polygon_api_key=self.config.get("polygon_api_key"))
        
    def setup(self):
        """Configuración inicial de la estrategia."""
        super().setup()
        
        self.logger.info("Inicializando estrategia ODTE Breakout")
        
        # Verificar órdenes previas
        self.check_previous_orders()
        
        # Reiniciar contador de trades diarios
        self.daily_trades_count = 0
        
        # Reiniciar PnL diario
        self.daily_pnl = 0.0
        
        # Comprobar tickers con expiración 0DTE hoy
        self.tickers = self.filter_odte_tickers()
        if not self.tickers:
            self.logger.warning("No hay tickers disponibles con expiración 0DTE hoy")
            # Usar todos los tickers si no hay específicos para 0DTE
            self.tickers = self.config["tickers"][:4]  # Limitar a los primeros 4 para no sobrecargar
            self.logger.info(f"Usando tickers generales: {self.tickers}")
        else:
            self.logger.info(f"Tickers disponibles con 0DTE: {self.tickers}")
            
        # Cargar rangos iniciales
        self.load_initial_ranges()
        
        # Inicializar análisis de tendencias
        self.initialize_market_trends()
    
    def filter_odte_tickers(self):
        """Filtra tickers que tienen opciones expirando hoy."""
        from ib_insync import Stock
        
        self.ibkr.ensure_connection()
        ib = self.ibkr.ib
        
        odte_tickers = []
        today = datetime.now().strftime('%Y%m%d')
        
        for ticker in self.config["tickers"]:
            try:
                contract = Stock(ticker, 'SMART', 'USD')
                ib.qualifyContracts(contract)
                params = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
                
                if not params:
                    continue
                    
                expirations = params[0].expirations
                if today in expirations:
                    odte_tickers.append(ticker)
            except Exception as e:
                self.logger.error(f"Error al verificar expiración para {ticker}: {e}")
        
        return odte_tickers
    
    def check_previous_orders(self):
        """Verifica órdenes de días anteriores que puedan estar activas."""
        orders_file = self.config["orders_file"]
        if not os.path.exists(orders_file):
            return
            
        self.ibkr.ensure_connection()
        ib = self.ibkr.ib
        
        try:
            with open(orders_file, 'r') as f:
                orders = json.load(f)
                
            for order_id, data in orders.items():
                status = "UNKNOWN"
                try:
                    open_orders = ib.reqOpenOrders()
                    match = next((o for o in open_orders if o.orderId == int(order_id)), None)
                    
                    if match:
                        status = "OPEN"
                    else:
                        executions = ib.reqExecutions()
                        exec_match = [e for e in executions if e.orderId == int(order_id)]
                        status = "EXECUTED" if exec_match else "NOT_FOUND"
                        
                except Exception as e:
                    self.logger.error(f"Error al verificar orden {order_id}: {e}")
                    continue
                    
                self.logger.info(f"Orden recuperada: {order_id} - {data.get('ticker', 'Unknown')} - Estado: {status}")
                data["status"] = status
                self.log_trade(data)
        except Exception as e:
            self.logger.error(f"Error al leer órdenes previas: {e}")
    
    def load_initial_ranges(self):
        """Carga rangos iniciales para los tickers."""
        for ticker in self.tickers:
            data = self.market_data.get_last_bar(ticker)
            if not data:
                self.logger.warning(f"No se pudieron obtener datos para {ticker}")
                continue
                
            self.initial_ranges[ticker] = {
                "high": data["high"],
                "low": data["low"],
                "volume": data["volume"],
                "open": data["open"],
                "close": data["close"],
                "timestamp": data["timestamp"]
            }
            
            self.logger.info(f"Rango inicial cargado para {ticker}: Alto: {data['high']}, Bajo: {data['low']}, Volumen: {data['volume']}")
    
    def initialize_market_trends(self):
        """Inicializa el análisis de tendencias de mercado."""
        self.logger.info("Inicializando análisis de tendencias de mercado")
        
        for ticker in self.tickers:
            # Intentar obtener datos históricos recientes (últimas 3 horas)
            now = datetime.now()
            start_date = (now - timedelta(hours=3)).strftime('%Y-%m-%d')
            end_date = now.strftime('%Y-%m-%d')
            
            try:
                data = self.market_data.get_historical_data(ticker, start_date, end_date, timeframe='minute')
                if data is not None and not data.empty:
                    # Calcular tendencia basada en los últimos datos
                    closes = data['close'].values
                    if len(closes) > 10:
                        current = closes[-1]
                        prev_10 = closes[-10]
                        prev_5 = closes[-5]
                        
                        # Determinar tendencia basada en precios recientes
                        if current > prev_10 and current > prev_5 and prev_5 > prev_10:
                            trend = "BULLISH"
                            strength = min(1.0, (current - prev_10) / prev_10 * 10)  # Normalizado entre 0-1
                        elif current < prev_10 and current < prev_5 and prev_5 < prev_10:
                            trend = "BEARISH"
                            strength = min(1.0, (prev_10 - current) / prev_10 * 10)  # Normalizado entre 0-1
                        else:
                            trend = "NEUTRAL"
                            strength = 0.0
                            
                        self.market_trends[ticker] = {
                            "trend": trend,
                            "strength": strength,
                            "updated_at": datetime.now()
                        }
                        
                        self.logger.info(f"Tendencia para {ticker}: {trend} (fuerza: {strength:.2f})")
            except Exception as e:
                self.logger.error(f"Error al analizar tendencia para {ticker}: {e}")
                # Establecer tendencia neutral por defecto
                self.market_trends[ticker] = {
                    "trend": "NEUTRAL",
                    "strength": 0.0,
                    "updated_at": datetime.now()
                }
    
    def scan_for_opportunities(self):
        """Busca oportunidades de breakout en los tickers configurados."""
        # Comprobar si estamos en horario de trading
        if not self.is_trading_allowed():
            self.logger.info("Fuera de horario de trading. Esperando...")
            return []
            
        # Comprobar límite diario de trades
        if self.daily_trades_count >= self.config["max_daily_trades"]:
            self.logger.info(f"Límite diario de trades alcanzado ({self.daily_trades_count}). Esperando hasta mañana.")
            return []
            
        opportunities = []
        
        # Actualizar tendencias de mercado cada 5 minutos
        for ticker in self.tickers:
            if ticker not in self.market_trends or \
               (datetime.now() - self.market_trends[ticker]["updated_at"]).total_seconds() > 300:
                try:
                    self.update_market_trend(ticker)
                except Exception as e:
                    self.logger.error(f"Error al actualizar tendencia para {ticker}: {e}")
        
        # Buscar oportunidades en cada ticker
        for ticker in self.tickers:
            if ticker not in self.initial_ranges:
                continue
                
            # Obtener datos actuales
            data = self.market_data.get_last_bar(ticker)
            if not data:
                self.logger.warning(f"No se pudieron obtener datos actuales para {ticker}")
                continue
                
            # Detectar breakout
            signal = self.detect_breakout(ticker, data["close"], data["volume"])
            if signal:
                self.logger.info(f"Señal de breakout detectada: {ticker} {signal}")
                
                opportunity = {
                    "ticker": ticker,
                    "signal": signal,
                    "price": data["close"],
                    "volume": data["volume"],
                    "timestamp": datetime.now().isoformat()
                }
                
                # Calcular parámetros del trade
                premium, qty, sl, tp = self.calculate_trade(signal, data["close"])
                opportunity.update({
                    "premium": premium,
                    "quantity": qty,
                    "stop_loss": sl,
                    "take_profit": tp
                })
                
                # Validar liquidez de la opción
                # Usar strike ATM o ligeramente OTM para mejor liquidez
                if signal == "CALL":
                    strike = round(data["close"] * 1.005)  # 0.5% OTM para CALL
                else:  # PUT
                    strike = round(data["close"] * 0.995)  # 0.5% OTM para PUT
                    
                expiry = get_option_expiry()
                
                # Verificar opciones válidas disponibles
                if self.validate_option(ticker, signal, strike, expiry):
                    # Obtener contrato
                    option_contract = create_option_contract(
                        self.ibkr.ib, 
                        ticker, 
                        expiry, 
                        strike, 
                        'C' if signal == 'CALL' else 'P'
                    )
                    
                    # Solicitar datos de mercado
                    market_data = self.ibkr.ib.reqMktData(option_contract, '', False, False)
                    self.ibkr.ib.sleep(2)
                    
                    # Calcular score
                    score = self.score_signal(ticker, signal, data["close"], self.initial_ranges[ticker], option_contract, market_data)
                    opportunity["score"] = score
                    
                    # Verificar score mínimo (ahora usando el configurado)
                    min_score = self.config.get("min_score", 70)
                    if score >= min_score:
                        opportunities.append(opportunity)
                        self.logger.info(f"Oportunidad válida: {ticker} {signal} con score {score}")
                    else:
                        self.logger.info(f"Señal descartada: {ticker} {signal} con score insuficiente: {score} < {min_score}")
                else:
                    self.logger.info(f"No se encontró contrato válido para {ticker} {signal} Strike {strike}")
        
        return opportunities
        
    def update_market_trend(self, ticker):
        """Actualiza la tendencia de mercado para un ticker."""
        try:
            # Obtener últimos 15 minutos de datos
            now = datetime.now()
            start_date = (now - timedelta(minutes=30)).strftime('%Y-%m-%d')
            end_date = now.strftime('%Y-%m-%d')
            
            data = self.market_data.get_historical_data(ticker, start_date, end_date, timeframe='minute')
            if data is None or data.empty:
                self.logger.warning(f"No hay datos históricos recientes para {ticker}")
                return
                
            # Calcular tendencia usando SMA
            if len(data) >= 10:
                # SMA corta (5 períodos)
                short_sma = data['close'].rolling(window=5).mean().dropna()
                # SMA larga (10 períodos)
                long_sma = data['close'].rolling(window=10).mean().dropna()
                
                if len(short_sma) > 0 and len(long_sma) > 0:
                    current_short = short_sma.iloc[-1]
                    current_long = long_sma.iloc[-1]
                    current_price = data['close'].iloc[-1]
                    
                    # Determinar tendencia
                    if current_short > current_long and current_price > current_short:
                        trend = "BULLISH"
                        strength = min(1.0, (current_short / current_long - 1) * 10)
                    elif current_short < current_long and current_price < current_short:
                        trend = "BEARISH"
                        strength = min(1.0, (current_long / current_short - 1) * 10)
                    else:
                        trend = "NEUTRAL"
                        strength = 0.2  # Ligera tendencia para neutrales
                        
                    self.market_trends[ticker] = {
                        "trend": trend,
                        "strength": strength,
                        "updated_at": datetime.now()
                    }
                    
                    self.logger.info(f"Tendencia actualizada para {ticker}: {trend} (fuerza: {strength:.2f})")
                    return
            
            # Si no hay suficientes datos, mantener/establecer tendencia neutral
            self.market_trends[ticker] = {
                "trend": "NEUTRAL",
                "strength": 0.0,
                "updated_at": datetime.now()
            }
            
        except Exception as e:
            self.logger.error(f"Error al actualizar tendencia para {ticker}: {e}")
    
    def detect_breakout(self, ticker, price, volume):
        """Detecta señales de breakout."""
        r = self.initial_ranges.get(ticker)
        if not r:
            return None
            
        volume_threshold = r["volume"] * self.config["volume_multiplier"]
        price_threshold = (r["high"] - r["low"]) * 0.3  # 30% del rango como umbral
        
        # Breakout alcista
        if price > r["high"] - price_threshold and volume > volume_threshold * 0.8:
            self.logger.info(f"Breakout CALL detectado para {ticker}: {price} > {r['high']} (o cercano), Vol: {volume}")
            return "CALL"
        # Breakout bajista
        elif price < r["low"] + price_threshold and volume > volume_threshold * 0.8:
            self.logger.info(f"Breakout PUT detectado para {ticker}: {price} < {r['low']} (o cercano), Vol: {volume}")
            return "PUT"
        # Breakout por tendencia intraday
        elif ticker in self.market_trends and self.market_trends[ticker]["trend"] != "NEUTRAL":
            trend = self.market_trends[ticker]["trend"]
            strength = self.market_trends[ticker]["strength"]
            if trend == "BULLISH" and strength > 0.5:
                self.logger.info(f"Breakout CALL por tendencia para {ticker}: fuerza {strength}")
                return "CALL"
            elif trend == "BEARISH" and strength > 0.5:
                self.logger.info(f"Breakout PUT por tendencia para {ticker}: fuerza {strength}")
                return "PUT"
            
        return None
    
    def calculate_trade(self, signal, price):
        """Calcula parámetros del trade (prima, cantidad, stop loss, take profit)."""
        # Estimación básica de prima como porcentaje del precio
        premium = price * 0.015
        
        # Calcular cantidad basada en riesgo por trade
        qty = max(1, int(self.config["risk_per_trade"] / premium))
        
        # Calcular stop loss y take profit
        sl = premium * self.config["sl_multiplier"]
        tp = premium * self.config["tp_multiplier"]
        
        return round(premium, 2), qty, round(sl, 2), round(tp, 2)
    
    def validate_option(self, ticker, signal_type, strike, expiry, min_volume=None, min_oi=None):
        """Valida la liquidez de un contrato de opciones."""
        if min_volume is None:
            min_volume = self.config.get("min_volume", 500)
        if min_oi is None:
            min_oi = self.config.get("min_open_interest", 1000)
            
        self.logger.info(f"Validando contrato para {ticker} {signal_type} Strike {strike} Expiry {expiry}")
        
        # Asegurar conexión
        if not self.ibkr.ensure_connection():
            self.logger.error(f"No se pudo establecer conexión con IBKR para validar opción de {ticker}")
            return False
            
        ib = self.ibkr.ib
        
        try:
            # Verificar si el ticker subyacente está disponible
            stock = Stock(ticker, 'SMART', 'USD')
            try:
                ib.qualifyContracts(stock)
            except Exception as e:
                self.logger.error(f"No se pudo calificar stock para {ticker}: {e}")
                return False
                
            # Verificar si la fecha de expiración está disponible
            try:
                params = ib.reqSecDefOptParams(ticker, '', 'STK', stock.conId)
                
                if not params:
                    self.logger.error(f"No se pudieron obtener parámetros de opciones para {ticker}")
                    return False
                    
                # Verificar expiraciones disponibles
                available_expirations = set()
                available_strikes = set()
                
                for param in params:
                    available_expirations.update(param.expirations)
                    available_strikes.update(param.strikes)
                
                self.logger.debug(f"Expiraciones disponibles para {ticker}: {sorted(list(available_expirations))[:5]}...")
                self.logger.debug(f"Strikes disponibles para {ticker}: {sorted(list(available_strikes))[:5]}...")
                
                # Verificar si la expiración está disponible
                if expiry not in available_expirations:
                    self.logger.warning(f"Expiración {expiry} no disponible para {ticker}")
                    return False
                    
                # Verificar si el strike está disponible
                if strike not in available_strikes:
                    closest_strike = min(available_strikes, key=lambda x: abs(x - strike))
                    self.logger.warning(f"Strike {strike} no disponible para {ticker}. El más cercano es {closest_strike}")
                    strike = closest_strike
            except Exception as e:
                self.logger.error(f"Error al verificar parámetros de opciones para {ticker}: {e}")
                return False
            
            # Crear y validar el contrato
            contract = create_option_contract(
                ib, 
                ticker, 
                expiry, 
                strike, 
                'C' if signal_type == 'CALL' else 'P'
            )
            
            if not contract:
                self.logger.error(f"No se pudo crear contrato para {ticker} {signal_type} Strike {strike}")
                return False
                
            # Obtener datos de mercado
            self.logger.debug(f"Solicitando datos de mercado para {ticker} {signal_type}")
            snapshot = ib.reqMktData(contract, "", False, False)
            ib.sleep(2)
            
            # Verificar spread bid-ask
            if hasattr(snapshot, 'bid') and hasattr(snapshot, 'ask') and snapshot.bid and snapshot.ask:
                spread = snapshot.ask - snapshot.bid
                spread_pct = spread / snapshot.ask if snapshot.ask > 0 else float('inf')
                
                if spread_pct > 0.20:  # Spread mayor al 20%
                    self.logger.warning(f"{ticker} {signal_type} - Spread demasiado amplio: {spread_pct:.2%}")
                
            # Obtener detalles del contrato
            self.logger.debug(f"Solicitando detalles de contrato para {ticker} {signal_type}")
            details = ib.reqContractDetails(contract)
            if not details:
                self.logger.warning(f"{ticker} {signal_type} - Sin detalles de contrato disponibles")
                return False
                
            # Verificar volumen
            volume = snapshot.volume if hasattr(snapshot, 'volume') and snapshot.volume else 0
            
            # En un entorno real, obtendríamos el open interest correctamente
            # Aquí usamos un valor aproximado
            oi = 0
            try:
                if hasattr(details[0], "minTick"):
                    oi = details[0].minTick
            except Exception as e:
                self.logger.debug(f"Error al obtener open interest aproximado: {e}")
                oi = 0
                
            self.logger.info(f"{ticker} {signal_type} - Volumen: {volume}, Open Interest aprox: {oi}")
                
            # Validar criterios mínimos
            if volume < min_volume:
                self.logger.warning(f"{ticker} {signal_type} - Volumen insuficiente: {volume} < {min_volume}")
                return False
                
            if oi < min_oi:
                self.logger.warning(f"{ticker} {signal_type} - Open Interest insuficiente: {oi} < {min_oi}")
                return False
                
            self.logger.info(f"{ticker} {signal_type} Strike {strike} validado correctamente")
            return True
            
        except Exception as e:
            import traceback
            self.logger.error(f"Error al validar opción {ticker} {signal_type}: {e}")
            self.logger.debug(traceback.format_exc())
            return False
    
    def score_signal(self, ticker, signal_type, current_price, range_data, option_contract, market_data, trend_5m=None):
        """Asigna un puntaje a una señal basado en múltiples factores."""
        score = 0
        
        # Volumen elevado (ahora más sensible)
        if range_data and market_data.volume and range_data["volume"]:
            volume_ratio = market_data.volume / range_data["volume"]
            if volume_ratio >= 1.2:
                points = min(30, int(volume_ratio * 15))  # Hasta 30 puntos por volumen alto
                score += points
                self.logger.debug(f"{ticker} +{points} puntos por volumen alto (ratio: {volume_ratio:.2f})")
            elif volume_ratio >= 0.8:
                score += 10  # Puntos por volumen moderado
                self.logger.debug(f"{ticker} +10 puntos por volumen moderado")
            
        # Fuerza del movimiento de precio
        try:
            candle_range = range_data["high"] - range_data["low"]
            if candle_range > 0:
                # Para CALL, evaluar qué tan por encima del rango está
                if signal_type == "CALL":
                    price_strength = (current_price - range_data["low"]) / candle_range
                    if price_strength >= 0.7:
                        points = min(25, int(price_strength * 30))
                        score += points
                        self.logger.debug(f"{ticker} +{points} puntos por movimiento alcista fuerte")
                # Para PUT, evaluar qué tan por debajo del rango está
                else:  # PUT
                    price_strength = (range_data["high"] - current_price) / candle_range
                    if price_strength >= 0.3:
                        points = min(25, int(price_strength * 30))
                        score += points
                        self.logger.debug(f"{ticker} +{points} puntos por movimiento bajista fuerte")
        except Exception as e:
            self.logger.debug(f"Error al calcular fuerza de movimiento: {e}")
            
        # Tendencia de mercado
        if ticker in self.market_trends:
            market_trend = self.market_trends[ticker]["trend"]
            trend_strength = self.market_trends[ticker]["strength"]
            
            if market_trend == "BULLISH" and signal_type == "CALL":
                points = int(20 * trend_strength)
                score += points
                self.logger.debug(f"{ticker} +{points} puntos por tendencia alcista (fuerza: {trend_strength:.2f})")
            elif market_trend == "BEARISH" and signal_type == "PUT":
                points = int(20 * trend_strength)
                score += points
                self.logger.debug(f"{ticker} +{points} puntos por tendencia bajista (fuerza: {trend_strength:.2f})")
            
        # Spread ajustado (ahora más permisivo)
        if hasattr(market_data, 'bid') and hasattr(market_data, 'ask') and market_data.bid and market_data.ask:
            spread = market_data.ask - market_data.bid
            if market_data.ask > 0:
                spread_pct = spread / market_data.ask
                if spread_pct <= 0.15:
                    points = int((1 - spread_pct * 5) * 25)  # Hasta 25 puntos por spread bajo
                    score += max(5, points)  # Mínimo 5 puntos
                    self.logger.debug(f"{ticker} +{points} puntos por spread aceptable ({spread_pct:.2%})")
                
        # Calidad del contrato y liquidez
        ib = self.ibkr.ib
        try:
            details = ib.reqContractDetails(option_contract)
            if details:
                # Verificar volumen
                if hasattr(market_data, 'volume') and market_data.volume:
                    vol_points = min(20, market_data.volume // 10)
                    score += vol_points
                    self.logger.debug(f"{ticker} +{vol_points} puntos por volumen de opciones")
                
                # Bonificación por strike cercano al ATM
                atm_diff = abs(option_contract.strike - current_price) / current_price
                if atm_diff < 0.02:  # Dentro del 2% del precio ATM
                    score += 15
                    self.logger.debug(f"{ticker} +15 puntos por strike cercano al ATM")
        except Exception as e:
            self.logger.debug(f"Error al evaluar calidad del contrato: {e}")
                
        # Bonificación por hora del día (mañana/tarde)
        hour = datetime.now().hour
        if 9 <= hour <= 11:  # Mañana (más volatilidad)
            score += 10
            self.logger.debug(f"{ticker} +10 puntos por horario de mañana")
        elif 14 <= hour <= 15:  # Última hora (más volatilidad)
            score += 10
            self.logger.debug(f"{ticker} +10 puntos por horario de cierre")
        
        # Log detallado del score final
        self.logger.info(f"{ticker} {signal_type} score total: {score}")
        return score
    
    def execute_trade(self, opportunity):
        """Ejecuta una operación basada en la oportunidad detectada."""
        ticker = opportunity["ticker"]
        signal = opportunity["signal"]
        strike = round(opportunity["price"])
        expiry = get_option_expiry()  # Hoy (0DTE)
        qty = opportunity["quantity"]
        
        self.logger.info(f"Ejecutando trade: {ticker} {signal} x{qty} @ {strike}")
        
        try:
            self.ibkr.ensure_connection()
            ib = self.ibkr.ib
            
            contract = create_option_contract(
                ib, 
                ticker, 
                expiry, 
                strike, 
                'C' if signal == 'CALL' else 'P'
            )
            
            if not contract:
                self.logger.error(f"No se pudo crear contrato para {ticker}")
                return None
                
            order = MarketOrder('BUY', qty)
            trade = ib.placeOrder(contract, order)
            ib.sleep(2)
            
            order_id = trade.order.orderId
            
            # Registrar orden
            trade_data = {
                "orderId": order_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "ticker": ticker,
                "type": signal,
                "underlying_price": opportunity["price"],
                "premium": opportunity["premium"],
                "quantity": qty,
                "strike": strike,
                "expiry": expiry,
                "SL": opportunity["stop_loss"],
                "TP": opportunity["take_profit"],
                "status": "SENT",
                "score": opportunity.get("score", 0)
            }
            
            self.active_trades[order_id] = trade_data
            self.save_order(trade_data)
            self.log_trade(trade_data)
            
            # Notificar
            self.notify_trade(ticker, signal, strike, opportunity["premium"])
            
            return order_id
            
        except Exception as e:
            self.logger.error(f"Error al ejecutar trade: {e}")
            return None
    
    def manage_positions(self):
        """Gestiona posiciones activas (stop loss, take profit, etc)."""
        if not self.active_trades:
            return
            
        orders_file = self.config["orders_file"]
        if not os.path.exists(orders_file):
            return
            
        try:
            with open(orders_file, 'r') as f:
                orders = json.load(f)
                
            self.ibkr.ensure_connection()
            ib = self.ibkr.ib
            
            for order_id, data in orders.items():
                if data.get("status") not in ["SENT", "OPEN", "EXECUTED"]:
                    continue
                    
                # Crear contrato
                contract = create_option_contract(
                    ib,
                    data["ticker"],
                    data["expiry"],
                    data["strike"],
                    'C' if data["type"] == 'CALL' else 'P'
                )
                
                if not contract:
                    continue
                    
                # Solicitar datos de mercado
                md = ib.reqMktData(contract, "", False, False)
                ib.sleep(2)
                
                current_premium = md.last if md.last else md.close
                if not current_premium:
                    continue
                    
                # Comprobar stop loss y take profit
                if current_premium <= data["SL"]:
                    self.logger.info(f"Stop Loss alcanzado: {data['ticker']} @ {current_premium:.2f} <= {data['SL']:.2f}")
                    self.close_position(
                        data["ticker"], 
                        data["type"], 
                        data["strike"], 
                        data["expiry"], 
                        data["quantity"],
                        "STOP"
                    )
                    data["status"] = "STOP"
                    self.notify_close(data["ticker"], data["type"], "STOP")
                    
                elif current_premium >= data["TP"]:
                    self.logger.info(f"Take Profit alcanzado: {data['ticker']} @ {current_premium:.2f} >= {data['TP']:.2f}")
                    self.close_position(
                        data["ticker"], 
                        data["type"], 
                        data["strike"], 
                        data["expiry"], 
                        data["quantity"],
                        "TP"
                    )
                    data["status"] = "TP"
                    self.notify_close(data["ticker"], data["type"], "TP")
                    
                # Actualizar datos
                self.log_trade(data)
                
            # Guardar cambios
            with open(orders_file, 'w') as f:
                json.dump(orders, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Error al gestionar posiciones: {e}")
    
    def close_position(self, ticker, option_type, strike, expiry, qty, reason="MANUAL"):
        """Cierra una posición existente."""
        self.logger.info(f"Cerrando posición: {ticker} {option_type} x{qty} @ {strike} - Motivo: {reason}")
        
        try:
            self.ibkr.ensure_connection()
            ib = self.ibkr.ib
            
            contract = create_option_contract(
                ib,
                ticker,
                expiry,
                strike,
                'C' if option_type == 'CALL' else 'P'
            )
            
            if not contract:
                self.logger.error(f"No se pudo crear contrato para cerrar posición: {ticker}")
                return None
                
            order = MarketOrder('SELL', qty)
            trade = ib.placeOrder(contract, order)
            ib.sleep(2)
            
            return trade.order.orderId
            
        except Exception as e:
            self.logger.error(f"Error al cerrar posición: {e}")
            return None
    
    def close_all_positions(self):
        """Cierra todas las posiciones activas al final del día."""
        self.logger.info("Cerrando todas las posiciones activas")
        
        orders_file = self.config["orders_file"]
        if not os.path.exists(orders_file):
            return
            
        try:
            with open(orders_file, 'r') as f:
                orders = json.load(f)
                
            self.ibkr.ensure_connection()
            ib = self.ibkr.ib
            
            modified = 0
            for order_id, data in orders.items():
                if data.get("status") in ["TP", "STOP", "EXPIRED", "CLOSED"]:
                    continue
                    
                contract = create_option_contract(
                    ib,
                    data["ticker"],
                    data["expiry"],
                    data["strike"],
                    'C' if data["type"] == 'CALL' else 'P'
                )
                
                if not contract:
                    continue
                    
                md = ib.reqMktData(contract, "", False, False)
                ib.sleep(2)
                
                price = md.last if md.last else md.close
                if price:
                    self.close_position(
                        data["ticker"], 
                        data["type"], 
                        data["strike"], 
                        data["expiry"], 
                        data["quantity"],
                        "FORCED_CLOSE"
                    )
                    data["status"] = "FORCED_CLOSE"
                    self.notify_close(data["ticker"], data["type"], "FORCED_CLOSE")
                else:
                    data["status"] = "EXPIRED"
                    self.notify_close(data["ticker"], data["type"], "EXPIRED")
                    
                modified += 1
                self.log_trade(data)
                
            # Guardar cambios
            with open(orders_file, 'w') as f:
                json.dump(orders, f, indent=2)
                
            self.logger.info(f"Se cerraron/marcaron {modified} posiciones")
            
        except Exception as e:
            self.logger.error(f"Error al cerrar todas las posiciones: {e}")
    
    def save_order(self, data):
        """Guarda datos de una orden en el archivo de órdenes."""
        orders_file = self.config["orders_file"]
        
        try:
            if os.path.exists(orders_file):
                with open(orders_file, 'r') as f:
                    orders = json.load(f)
            else:
                orders = {}
                
            orders[data["orderId"]] = data
            
            with open(orders_file, 'w') as f:
                json.dump(orders, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Error al guardar orden: {e}")
    
    def log_trade(self, data):
        """Registra un trade en el archivo de log."""
        log_file = self.config["log_file"]
        
        try:
            with open(log_file, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=data.keys())
                if f.tell() == 0:
                    writer.writeheader()
                writer.writerow(data)
                
        except Exception as e:
            self.logger.error(f"Error al registrar trade: {e}")
    
    def is_trading_allowed(self):
        """Verifica si es horario válido para operar."""
        now = datetime.utcnow()
        
        # Restricción de fin de semana
        if now.weekday() >= 5:  # 5 = Sábado, 6 = Domingo
            return False
            
        # Restricción de horario (9:30am - 3:30pm ET)
        # Convertido a UTC (aproximadamente +4/5 horas)
        now_str = now.strftime('%H:%M')
        return "13:30" <= now_str <= "19:30"  # 9:30am-3:30pm ET en UTC
    
    def generate_summary(self):
        """Genera un resumen diario de la actividad."""
        log_file = self.config["log_file"]
        if not os.path.exists(log_file):
            return "No hay datos disponibles para generar resumen"
            
        today = datetime.now().strftime('%Y-%m-%d')
        today_trades = []
        
        try:
            with open(log_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("date", "").startswith(today):
                        today_trades.append(row)
                        
            if not today_trades:
                return "No hay trades hoy para generar resumen"
                
            total = len(today_trades)
            tp_count = sum(1 for t in today_trades if t.get("status") == "TP")
            sl_count = sum(1 for t in today_trades if t.get("status") == "STOP")
            pending = sum(1 for t in today_trades if t.get("status") in ["SENT", "OPEN", "EXECUTED"])
            forced = sum(1 for t in today_trades if t.get("status") == "FORCED_CLOSE")
            expired = sum(1 for t in today_trades if t.get("status") == "EXPIRED")
            closed = total - pending
            
            # Cálculo de rendimiento (estimado)
            initial_balance = 0
            final_balance = 0
            
            for trade in today_trades:
                try:
                    premium = float(trade.get("premium", 0))
                    qty = int(trade.get("quantity", 0))
                    sl = float(trade.get("SL", 0))
                    tp = float(trade.get("TP", 0))
                    status = trade.get("status", "")
                    
                    initial_balance -= premium * qty
                    
                    if status == "TP":
                        final_balance += (tp - premium) * qty
                    elif status == "STOP":
                        final_balance += (sl - premium) * qty
                    elif status in ["FORCED_CLOSE", "EXPIRED"]:
                        final_balance -= premium * qty
                except:
                    continue
                    
            summary = (
                f"=== Resumen ODTE {today} ===\n"
                f"Total trades: {total}\n"
                f"Take Profit: {tp_count}\n"
                f"Stop Loss: {sl_count}\n"
                f"Forzados: {forced}\n"
                f"Expirados: {expired}\n"
                f"Cerrados: {closed}\n"
                f"Pendientes: {pending}\n"
                f"Inversión inicial: ${initial_balance:.2f}\n"
                f"Balance final est.: ${(initial_balance + final_balance):.2f}\n"
                f"P&L est.: ${final_balance:.2f}"
            )
            
            # Guardar resumen en archivo
            os.makedirs("reports", exist_ok=True)
            summary_file = f"reports/summary_odte_{today.replace('-', '')}.txt"
            
            with open(summary_file, "w") as f:
                f.write(summary)
                
            self.logger.info(f"Resumen diario guardado en {summary_file}")
                
            return summary
            
        except Exception as e:
            self.logger.error(f"Error al generar resumen: {e}")
            return f"Error al generar resumen: {e}"
    
    def notify_trade(self, ticker, option_type, strike, premium):
        """Notifica al usuario sobre ejecución de un trade."""
        self.logger.info(f"TRADE: {ticker} {option_type} Strike {strike} @ {premium:.2f}")
        
        # En macOS, podemos usar notificaciones del sistema
        try:
            import subprocess
            title = "Orden Ejecutada"
            msg = f"{ticker} {option_type} Strike {strike} @ {premium:.2f}"
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}"'])
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
        except:
            pass
    
    def notify_close(self, ticker, option_type, reason):
        """Notifica al usuario sobre cierre de un trade."""
        self.logger.info(f"CIERRE: {ticker} {option_type} - Motivo: {reason}")
        
        # En macOS, podemos usar notificaciones del sistema
        try:
            import subprocess
            title = "Cierre de Posición"
            msg = f"{ticker} {option_type} cerrado por {reason}"
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}"'])
            
            # Sonido diferente según resultado
            sound = "/System/Library/Sounds/Submarine.aiff" if reason == "TP" else "/System/Library/Sounds/Funk.aiff"
            subprocess.run(["afplay", sound])
        except:
            pass
    
    def run(self):
        """Ejecuta el bucle principal de la estrategia."""
        if not self.active:
            self.logger.warning("La estrategia no está activa. Llama a start() primero.")
            return
            
        try:
            self.logger.info("Iniciando bucle principal de la estrategia")
            
            # Verificar la fecha actual para el contador de trades diarios
            current_date = datetime.now().date()
            last_reset_date = current_date
            
            while self.active:
                # Resetear contador diario si cambia el día
                today = datetime.now().date()
                if today != last_reset_date:
                    self.logger.info(f"Nuevo día detectado. Reseteando contador de trades diarios y PnL diario")
                    self.daily_trades_count = 0
                    self.daily_pnl = 0.0
                    last_reset_date = today
                    # Reiniciar rangos iniciales para el nuevo día
                    self.initial_ranges = {}
                    self.load_initial_ranges()
                
                # Verificar si el mercado está abierto
                if not self.is_trading_allowed():
                    self.logger.info("Fuera de horario de trading. Esperando...")
                    time.sleep(60)
                    continue
                    
                # Gestionar posiciones existentes (prioridad)
                self.manage_positions()
                
                # Escanear oportunidades si no hemos alcanzado límite diario
                if self.daily_trades_count < self.config["max_daily_trades"]:
                    opportunities = self.scan_for_opportunities()
                    
                    # Ejecutar trades para oportunidades encontradas
                    for opportunity in opportunities:
                        trade_id = self.execute_trade(opportunity)
                        if trade_id:
                            self.daily_trades_count += 1
                            self.logger.info(f"Trade ejecutado. Total de trades hoy: {self.daily_trades_count}/{self.config['max_daily_trades']}")
                else:
                    self.logger.info(f"Límite diario de trades alcanzado ({self.daily_trades_count}). Solo gestionando posiciones existentes.")
                
                # Actualizar PnL en tiempo real para mostrar rendimiento
                current_pnl = self.calculate_current_pnl()
                if current_pnl != self.daily_pnl:
                    self.daily_pnl = current_pnl
                    self.logger.info(f"PnL diario actual: ${self.daily_pnl:.2f}")
                
                # Mostrar resumen cada hora (aproximadamente)
                now = datetime.now()
                if now.minute == 0:
                    self.show_performance_summary()
                
                # Esperar antes del siguiente escaneo
                time.sleep(self.config["scan_interval"])
                
        except KeyboardInterrupt:
            self.logger.info("Bucle de estrategia interrumpido por el usuario")
            self.stop()
        except Exception as e:
            self.logger.error(f"Error en bucle principal: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            self.stop()
            
    def calculate_current_pnl(self):
        """Calcula el PnL actual de todas las posiciones."""
        total_pnl = 0.0
        
        # Verificar órdenes del día actual
        orders_file = self.config["orders_file"]
        if not os.path.exists(orders_file):
            return total_pnl
            
        try:
            with open(orders_file, 'r') as f:
                orders = json.load(f)
                
            today = datetime.now().strftime("%Y-%m-%d")
            
            for order_id, data in orders.items():
                if not data.get("date", "").startswith(today):
                    continue  # Solo contabilizar trades de hoy
                    
                status = data.get("status", "")
                
                # Para operaciones ya cerradas, usar el PnL registrado
                if status in ["TP", "STOP", "FORCED_CLOSE"]:
                    if "pnl" in data:
                        total_pnl += data["pnl"]
                    continue
                    
                # Para operaciones abiertas, calcular PnL actual
                if status in ["SENT", "OPEN", "EXECUTED"]:
                    try:
                        contract = create_option_contract(
                            self.ibkr.ib,
                            data["ticker"],
                            data["expiry"],
                            data["strike"],
                            'C' if data["type"] == 'CALL' else 'P'
                        )
                        
                        if contract:
                            md = self.ibkr.ib.reqMktData(contract, "", False, False)
                            self.ibkr.ib.sleep(1)  # Tiempo reducido para optimizar
                            
                            current_premium = md.last if md.last else md.close
                            if current_premium:
                                entry_premium = data.get("premium", 0)
                                qty = data.get("quantity", 0)
                                position_pnl = (current_premium - entry_premium) * qty
                                total_pnl += position_pnl
                    except Exception as e:
                        self.logger.error(f"Error al calcular PnL para orden {order_id}: {e}")
            
            return total_pnl
        except Exception as e:
            self.logger.error(f"Error al calcular PnL total: {e}")
            return 0.0
            
    def show_performance_summary(self):
        """Muestra un resumen del rendimiento de la estrategia."""
        self.logger.info("=========== RESUMEN DE RENDIMIENTO ===========")
        self.logger.info(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self.logger.info(f"Trades ejecutados hoy: {self.daily_trades_count}/{self.config['max_daily_trades']}")
        self.logger.info(f"PnL diario: ${self.daily_pnl:.2f}")
        self.logger.info(f"PnL total estimado: ${self.total_pnl + self.daily_pnl:.2f}")
        
        # Contar operaciones por resultado
        orders_file = self.config["orders_file"]
        if os.path.exists(orders_file):
            try:
                with open(orders_file, 'r') as f:
                    orders = json.load(f)
                    
                today = datetime.now().strftime("%Y-%m-%d")
                today_orders = {k: v for k, v in orders.items() if v.get("date", "").startswith(today)}
                
                tp_count = sum(1 for data in today_orders.values() if data.get("status") == "TP")
                sl_count = sum(1 for data in today_orders.values() if data.get("status") == "STOP")
                open_count = sum(1 for data in today_orders.values() if data.get("status") in ["SENT", "OPEN", "EXECUTED"])
                
                self.logger.info(f"Trades con Take Profit: {tp_count}")
                self.logger.info(f"Trades con Stop Loss: {sl_count}")
                self.logger.info(f"Trades abiertos: {open_count}")
            except Exception as e:
                self.logger.error(f"Error al generar resumen: {e}")
                
        self.logger.info("==============================================")
    
    def teardown(self):
        """Cierra recursos y genera resumen al detener la estrategia."""
        super().teardown()
        
        # Cerrar todas las posiciones abiertas
        self.close_all_positions()
        
        # Generar resumen diario
        summary = self.generate_summary()
        self.logger.info(f"Resumen final:\n{summary}")
        
        # Notificar resumen
        try:
            import subprocess
            title = "Resumen Diario ODTE"
            subprocess.run(["osascript", "-e", f'display notification "{summary}" with title "{title}"'])
        except:
            pass
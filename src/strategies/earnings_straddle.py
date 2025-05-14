from ..core.strategy_base import StrategyBase
from ..core.options_utils import create_option_contract, get_atm_straddle
from ..core.market_data import MarketData
from ib_insync import MarketOrder, Stock
import json
import os
from datetime import datetime, timedelta
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

class EarningsStraddleStrategy(StrategyBase):
    """
    Estrategia de straddle para empresas con reportes de ganancias.
    Compra un straddle (CALL + PUT) el día anterior al reporte 
    y cierra después del movimiento post-earnings.
    """
    
    def __init__(self, config=None):
        super().__init__(name="Earnings_Straddle", config=config)
        
        # Configuración por defecto
        self.default_config = {
            "tickers_whitelist": [
                "TSLA", "NFLX", "NVDA", "AMD", "META", "AMZN", 
                "BABA", "SHOP", "ROKU", "COIN", "MSFT", "AAPL",
                "GOOGL", "ADBE", "CRM", "ZM", "PYPL", "SQ", "SNAP"
            ],
            "max_capital_per_trade": 500,
            "polygon_api_key": None,
            "ibkr_host": "127.0.0.1",
            "ibkr_port": 7497,
            "ibkr_client_id": 2,
            "data_dir": "data/earnings",
            "scan_interval": 1800,       # segundos (30 minutos)
            "auto_close_time": "14:35",  # Hora UTC para cierre automático
            "entry_days_before": 1,      # Entrar 1 día antes del reporte
            "exit_days_after": 1,        # Salir 1 día después del reporte
            "min_iv_rank": 35,           # IV rank mínimo reducido para más oportunidades
            "max_days_to_expiry": 7,     # Expiración máxima extendida para opciones
            "use_simulation": True,      # Usar datos simulados si la API no devuelve datos
            "max_daily_trades": 3,       # Máximo número de straddles por día
            "same_day_entry": True,      # Permitir entrar el mismo día del reporte
            "extended_hours": True       # Incluir horas extendidas para atrapar movimientos
        }
        
        # Combinar configuración personalizada con valores por defecto
        self.config = {**self.default_config, **(config or {})}
        
        # Asegurar que client_id sea un entero
        if 'ibkr_client_id' in self.config:
            self.config['ibkr_client_id'] = int(self.config['ibkr_client_id'])
            
        # Inicializar MarketData con la api key
        self.market_data = MarketData(
            polygon_api_key=self.config.get('polygon_api_key')
        )
        
        # Datos internos
        self.earnings_calendar = {}    # Calendario de earnings próximos
        self.active_straddles = {}     # Straddles activos
        self.daily_trades_count = 0    # Contador de trades diarios
        self.daily_pnl = 0.0           # PnL diario
        self.total_pnl = 0.0           # PnL total acumulado
        
        # Crear directorios de datos
        os.makedirs(self.config["data_dir"], exist_ok=True)
    
    def setup(self):
        """Configuración inicial de la estrategia."""
        super().setup()
        
        self.logger.info("Inicializando estrategia Earnings Straddle")
        
        # Cargar straddles activos
        self.load_active_straddles()
        
        # Actualizar calendario de earnings
        self.update_earnings_calendar()
    
    def load_active_straddles(self):
        """Carga straddles activos desde archivos guardados."""
        data_dir = self.config["data_dir"]
        straddles_dir = f"{data_dir}/straddles"
        
        if not os.path.exists(straddles_dir):
            os.makedirs(straddles_dir, exist_ok=True)
            return
            
        for filename in os.listdir(straddles_dir):
            if not filename.endswith("_straddle.json"):
                continue
                
            file_path = f"{straddles_dir}/{filename}"
            ticker = filename.split("_")[0]
            
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                    self.active_straddles[ticker] = data
                    self.logger.info(f"Straddle cargado para {ticker}")
            except Exception as e:
                self.logger.error(f"Error al cargar straddle para {ticker}: {e}")
    
    def get_simulated_earnings(self):
        """Genera datos simulados de earnings para pruebas."""
        self.logger.info("Usando datos simulados de earnings para pruebas")
        
        # Generar fechas de earnings para los próximos días
        today = datetime.now().date()
        earnings = {}
        
        # Lista ampliada de tickers para simulación
        all_tickers = [
            "AAPL", "MSFT", "NVDA", "AMD", "META", "AMZN", "TSLA", "NFLX",
            "GOOGL", "BABA", "SHOP", "ROKU", "COIN", "SQ", "PYPL", "ZM",
            "ADBE", "CRM", "SNAP", "UBER", "LYFT", "TWLO", "PTON", "DOCU"
        ]
        
        # Asegurarse de que todos los tickers en whitelist estén disponibles
        whitelist = self.config["tickers_whitelist"]
        for ticker in whitelist:
            if ticker not in all_tickers:
                all_tickers.append(ticker)
        
        # Día actual - para pruebas inmediatas
        today_str = today.strftime('%Y-%m-%d')
        earnings[today_str] = ["AAPL", "MSFT", "GOOGL", "SHOP"]
        
        # Mañana
        tomorrow = today + timedelta(days=1)
        tomorrow_str = tomorrow.strftime('%Y-%m-%d')
        earnings[tomorrow_str] = ["NVDA", "AMD", "COIN", "ROKU"]
        
        # Próximos días
        next_day = today + timedelta(days=2)
        next_day_str = next_day.strftime('%Y-%m-%d')
        earnings[next_day_str] = ["META", "AMZN", "SQ", "PYPL"]
        
        # Día adicional
        next_day2 = today + timedelta(days=3)
        next_day2_str = next_day2.strftime('%Y-%m-%d')
        earnings[next_day2_str] = ["TSLA", "NFLX", "ADBE", "CRM"]
        
        # Día adicional 2
        next_day3 = today + timedelta(days=4)
        next_day3_str = next_day3.strftime('%Y-%m-%d')
        earnings[next_day3_str] = ["SNAP", "PTON", "DOCU", "ZM"]
        
        # Asegurarse de que todos los días tienen al menos algunos tickers de la whitelist
        for date, tickers in earnings.items():
            whitelist_intersection = [t for t in tickers if t in whitelist]
            if not whitelist_intersection:
                # Añadir algunos tickers de la whitelist a esta fecha
                import random
                additional = random.sample([t for t in whitelist if t not in tickers], min(2, len(whitelist)))
                earnings[date].extend(additional)
        
        self.logger.info(f"Datos simulados generados para {len(earnings)} fechas")
        return earnings
    
    def update_earnings_calendar(self):
        """Actualiza el calendario de earnings próximos."""
        # Verificar API key
        if not self.config.get('polygon_api_key'):
            self.logger.error("No se ha configurado Polygon API key. Verificar config.")
            if self.config.get('use_simulation'):
                # Usar datos simulados como fallback
                self.earnings_calendar = self.get_simulated_earnings()
            return
            
        # Obtener datos para los próximos 7 días
        earnings = self.market_data.get_earnings_calendar(days_ahead=7)
        
        # Si no hay datos y está activada la simulación, usar datos simulados
        if not earnings and self.config.get('use_simulation'):
            self.logger.info("API no devolvió datos de earnings. Usando datos simulados.")
            earnings = self.get_simulated_earnings()
        elif not earnings:
            self.logger.warning("No se pudieron obtener datos de earnings")
            return
            
        # Filtrar por lista blanca de tickers
        whitelist = self.config["tickers_whitelist"]
        filtered_earnings = {}
        
        for date, tickers in earnings.items():
            filtered = [t for t in tickers if t in whitelist]
            if filtered:
                filtered_earnings[date] = filtered
                
        self.earnings_calendar = filtered_earnings
        
        # Guardar calendario
        earnings_file = f"{self.config['data_dir']}/earnings_calendar.json"
        with open(earnings_file, "w") as f:
            json.dump(filtered_earnings, f, indent=2)
            
        self.logger.info(f"Calendario de earnings actualizado: {filtered_earnings}")
    
    def scan_for_opportunities(self):
        """Busca oportunidades para straddles antes de earnings."""
        # Verificar límite diario de trades
        if self.daily_trades_count >= self.config.get("max_daily_trades", 3):
            self.logger.info(f"Límite diario de straddles alcanzado ({self.daily_trades_count}). Esperando hasta mañana.")
            return []
            
        # Si no hay calendario, actualizar
        if not self.earnings_calendar:
            self.update_earnings_calendar()
            if not self.earnings_calendar:
                return []
                
        opportunities = []
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        
        # Determinar fechas objetivo (día actual si same_day_entry está habilitado + futuras fechas configuradas)
        target_dates = []
        if self.config.get("same_day_entry", True):
            target_dates.append(today_str)
            
        future_target = (today + timedelta(days=self.config["entry_days_before"])).strftime("%Y-%m-%d")
        if future_target != today_str:  # Evitar duplicados
            target_dates.append(future_target)
        
        self.logger.info(f"Buscando oportunidades para fechas objetivo: {target_dates}")
        self.logger.info(f"Fechas disponibles en calendario: {list(self.earnings_calendar.keys())}")
        
        # Buscar earnings para las fechas objetivo
        for target_date in target_dates:
            earnings_tickers = self.earnings_calendar.get(target_date, [])
            
            if not earnings_tickers:
                self.logger.info(f"No hay earnings programados para {target_date}")
                continue
                
            self.logger.info(f"Tickers con earnings para {target_date}: {earnings_tickers}")
            
            # Filtrar por whitelist
            whitelist = self.config["tickers_whitelist"]
            filtered_tickers = [ticker for ticker in earnings_tickers if ticker in whitelist]
            
            if not filtered_tickers:
                self.logger.info(f"Ningún ticker en la lista blanca para {target_date}")
                continue
                
            for ticker in filtered_tickers:
                # Evitar duplicados si ya tenemos un straddle para este ticker
                if ticker in self.active_straddles:
                    self.logger.info(f"Ya existe un straddle activo para {ticker}")
                    continue
                
                # Verificar si hay datos de precio disponibles
                price_data = self.market_data.get_last_bar(ticker)
                if not price_data:
                    self.logger.warning(f"No hay datos de precio disponibles para {ticker}")
                    continue
                    
                # Verificar volatilidad implícita
                iv_rank = self.get_iv_rank(ticker)
                if iv_rank < self.config["min_iv_rank"]:
                    self.logger.info(f"IV Rank insuficiente para {ticker}: {iv_rank}%")
                    continue
                    
                # Asignar un score de oportunidad
                score = self.score_opportunity(ticker, target_date, iv_rank, price_data)
                
                # Crear oportunidad
                opportunity = {
                    "ticker": ticker,
                    "earnings_date": target_date,
                    "timestamp": datetime.now().isoformat(),
                    "iv_rank": iv_rank,
                    "current_price": price_data["close"],
                    "score": score
                }
                
                opportunities.append(opportunity)
                self.logger.info(f"Oportunidad de straddle detectada: {ticker} (Earnings: {target_date}, IV Rank: {iv_rank}%, Score: {score})")
        
        # Ordenar oportunidades por score (mayor a menor)
        opportunities.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        return opportunities
        
    def score_opportunity(self, ticker, earnings_date, iv_rank, price_data):
        """Asigna un puntaje a una oportunidad de straddle basado en varios factores."""
        score = 0
        
        # Factor de IV Rank (hasta 40 puntos)
        iv_points = min(40, int(iv_rank * 0.5))
        score += iv_points
        self.logger.debug(f"{ticker} +{iv_points} puntos por IV Rank de {iv_rank}%")
        
        # Proximidad a earnings (hasta 20 puntos)
        today = datetime.now().date()
        earnings_day = datetime.strptime(earnings_date, '%Y-%m-%d').date()
        days_to_earnings = (earnings_day - today).days
        
        if days_to_earnings == 0:  # Hoy
            proximity_points = 20
        elif days_to_earnings == 1:  # Mañana
            proximity_points = 15
        else:
            proximity_points = max(0, 15 - (days_to_earnings - 1) * 5)
            
        score += proximity_points
        self.logger.debug(f"{ticker} +{proximity_points} puntos por proximidad a earnings ({days_to_earnings} días)")
        
        # Volatilidad histórica reciente (hasta 30 puntos)
        try:
            start_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            
            hist_data = self.market_data.get_historical_data(ticker, start_date, end_date)
            if hist_data is not None and not hist_data.empty and len(hist_data) > 5:
                # Calcular volatilidad como desviación estándar de rendimientos diarios
                returns = hist_data['close'].pct_change().dropna()
                vol = returns.std() * 100  # Convertir a porcentaje
                
                # Asignar puntos basados en volatilidad (más volatilidad = más puntos)
                vol_points = min(30, int(vol * 10))
                score += vol_points
                self.logger.debug(f"{ticker} +{vol_points} puntos por volatilidad histórica de {vol:.2f}%")
        except Exception as e:
            self.logger.debug(f"Error al calcular volatilidad histórica para {ticker}: {e}")
        
        # Popularidad del ticker (hasta 10 puntos)
        popularity_map = {
            "TSLA": 10, "NVDA": 10, "AAPL": 10, "AMZN": 10, "META": 9,
            "MSFT": 9, "GOOGL": 9, "AMD": 8, "NFLX": 8, "ROKU": 7,
            "COIN": 7, "SHOP": 6, "PYPL": 6, "SQ": 6, "ZM": 5,
            "BABA": 5, "ADBE": 4, "CRM": 4, "SNAP": 3
        }
        
        popularity_points = popularity_map.get(ticker, 2)
        score += popularity_points
        self.logger.debug(f"{ticker} +{popularity_points} puntos por popularidad del ticker")
        
        self.logger.info(f"{ticker} score total: {score}")
        return score
    
    def get_iv_rank(self, ticker):
        """Obtiene el IV Rank para un ticker."""
        # En una implementación completa, se debería obtener datos históricos
        # de volatilidad implícita y calcular el percentil actual
        # Aquí usamos un valor aleatorio con más probabilidad de generar valores altos
        import random
        
        # Verificar si hay earnings programados para hoy o mañana
        today = datetime.now().date().strftime("%Y-%m-%d")
        tomorrow = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        has_upcoming_earnings = False
        for earnings_date in [today, tomorrow]:
            if earnings_date in self.earnings_calendar and ticker in self.earnings_calendar.get(earnings_date, []):
                has_upcoming_earnings = True
                break
        
        # Si hay earnings cercanos, favorecer valores más altos de IV
        if has_upcoming_earnings:
            base = random.randint(50, 85)  # Base más alta para earnings cercanos
            bonus = random.randint(5, 15)  # Bonus adicional
            rank = min(95, base + bonus)   # Limitar a 95 como máximo
        else:
            # Distribución sesgada para favorecer valores cercanos al umbral mínimo
            min_threshold = self.config["min_iv_rank"]
            if random.random() < 0.7:  # 70% de probabilidad de estar por encima del umbral
                rank = random.randint(min_threshold, 90)
            else:
                rank = random.randint(30, min_threshold - 1)
        
        self.logger.info(f"IV Rank simulado para {ticker}: {rank}%")
        return rank
    
    def execute_trade(self, opportunity):
        """Ejecuta un straddle para la oportunidad detectada."""
        ticker = opportunity["ticker"]
        
        self.logger.info(f"Ejecutando straddle para {ticker}")
        
        try:
            # Asegurar conexión con IBKR
            if not self.ibkr.ensure_connection():
                self.logger.error(f"No se pudo establecer conexión con IBKR para ejecutar straddle de {ticker}")
                return None
                
            ib = self.ibkr.ib
            
            # Obtener fecha de expiración cercana
            expiry_days = self.config["max_days_to_expiry"]
            expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y%m%d")
            self.logger.info(f"Buscando expiración {expiry_date} para {ticker} (a {expiry_days} días)")
            
            # Verificar si el ticker tiene un precio válido
            stock = Stock(ticker, 'SMART', 'USD')
            try:
                ib.qualifyContracts(stock)
                stock_ticker = ib.reqMktData(stock, '', False, False)
                ib.sleep(1)
                
                stock_price = stock_ticker.last or stock_ticker.close
                if not stock_price or stock_price <= 0:
                    self.logger.error(f"No se pudo obtener precio válido para {ticker}. Last: {stock_ticker.last}, Close: {stock_ticker.close}")
                    return None
                    
                self.logger.info(f"Precio actual de {ticker}: ${stock_price}")
            except Exception as e:
                self.logger.error(f"Error al obtener precio de {ticker}: {e}")
                return None
            
            # Obtener contratos para el straddle ATM
            self.logger.info(f"Obteniendo contratos ATM para {ticker} con expiración {expiry_date}")
            call, put, current_price = get_atm_straddle(ib, ticker, expiry_date)
            
            if not call or not put:
                self.logger.error(f"No se pudieron crear contratos para {ticker}")
                # Intentar con una fecha de expiración alternativa
                alt_expiry_date = (datetime.now() + timedelta(days=expiry_days + 7)).strftime("%Y%m%d")
                self.logger.info(f"Intentando con expiración alternativa {alt_expiry_date} para {ticker}")
                
                call, put, current_price = get_atm_straddle(ib, ticker, alt_expiry_date)
                if not call or not put:
                    self.logger.error(f"Tampoco se pudieron crear contratos con expiración alternativa para {ticker}")
                    return None
                
            self.logger.info(f"Contratos creados exitosamente para {ticker}: CALL {call.strike} y PUT {put.strike}, expiración {call.lastTradeDateOrContractMonth}")
                
            # Obtener precios de mercado
            self.logger.info(f"Obteniendo precios de mercado para opciones de {ticker}")
            call_data = ib.reqMktData(call, "", False, False)
            put_data = ib.reqMktData(put, "", False, False)
            ib.sleep(2)
            
            # Intentar obtener precios válidos
            call_price = call_data.ask if call_data.ask else call_data.last
            if not call_price:
                call_price = call_data.close
                
            put_price = put_data.ask if put_data.ask else put_data.last
            if not put_price:
                put_price = put_data.close
            
            if not call_price or not put_price:
                self.logger.error(f"No se pudieron obtener precios válidos para opciones de {ticker}.")
                self.logger.error(f"CALL - Ask: {call_data.ask}, Last: {call_data.last}, Close: {call_data.close}")
                self.logger.error(f"PUT - Ask: {put_data.ask}, Last: {put_data.last}, Close: {put_data.close}")
                return None
                
            self.logger.info(f"Precios obtenidos para {ticker}: CALL ${call_price}, PUT ${put_price}")
                
            # Calcular cantidad basada en capital máximo
            total_cost = call_price + put_price
            max_capital = self.config["max_capital_per_trade"]
            qty = int(max_capital / total_cost) if total_cost > 0 else 0
            
            if qty < 1:
                self.logger.info(f"Capital insuficiente para {ticker}. Costo total: ${total_cost:.2f} > Capital máximo: ${max_capital}")
                return None
                
            self.logger.info(f"Ejecutando órdenes para {ticker}: {qty} contratos, costo total: ${(total_cost * qty):.2f}")
                
            # Ejecutar órdenes de compra
            call_order = MarketOrder('BUY', qty)
            put_order = MarketOrder('BUY', qty)
            
            # Colocar órdenes y verificar su estado
            try:
                call_trade = ib.placeOrder(call, call_order)
                put_trade = ib.placeOrder(put, put_order)
                ib.sleep(2)
                
                # Verificar estado de las órdenes
                call_order_status = call_trade.orderStatus.status
                put_order_status = put_trade.orderStatus.status
                
                self.logger.info(f"Estado de órdenes para {ticker} - CALL: {call_order_status}, PUT: {put_order_status}")
                
                # Verificar si alguna orden falló
                if call_order_status in ['Cancelled', 'Inactive'] or put_order_status in ['Cancelled', 'Inactive']:
                    self.logger.error(f"Al menos una orden fue rechazada para {ticker}")
                    # Cancelar la otra orden si una falló
                    if call_order_status not in ['Cancelled', 'Inactive']:
                        ib.cancelOrder(call_trade.order)
                    if put_order_status not in ['Cancelled', 'Inactive']:
                        ib.cancelOrder(put_trade.order)
                    return None
            except Exception as e:
                self.logger.error(f"Error al colocar órdenes para {ticker}: {e}")
                return None
            
            # Registrar straddle
            straddle_data = {
                "date": datetime.now().strftime('%Y-%m-%d'),
                "ticker": ticker,
                "strike": call.strike,
                "expiry": call.lastTradeDateOrContractMonth,
                "quantity": qty,
                "current_price": current_price,
                "call_price": call_price,
                "put_price": put_price,
                "total_cost": total_cost,
                "iv_rank": opportunity["iv_rank"],
                "earnings_date": opportunity["earnings_date"],
                "call_order_id": call_trade.order.orderId,
                "put_order_id": put_trade.order.orderId,
                "status": "OPEN",
                "close_date": None,
                "score": opportunity.get("score", 0)
            }
            
            # Guardar datos
            self.active_straddles[ticker] = straddle_data
            self.save_straddle(straddle_data)
            
            # Notificar
            self.notify_straddle_opened(ticker, call.strike, qty, total_cost)
            
            self.logger.info(f"Straddle ejecutado exitosamente para {ticker}")
            return {
                "call_order_id": call_trade.order.orderId,
                "put_order_id": put_trade.order.orderId
            }
            
        except Exception as e:
            import traceback
            self.logger.error(f"Error al ejecutar straddle para {ticker}: {e}")
            self.logger.debug(traceback.format_exc())
            return None
    
    def save_straddle(self, data):
        """Guarda datos de un straddle en archivo."""
        straddles_dir = f"{self.config['data_dir']}/straddles"
        os.makedirs(straddles_dir, exist_ok=True)
        
        file_path = f"{straddles_dir}/{data['ticker']}_straddle.json"
        
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
                
            self.logger.info(f"Straddle guardado: {file_path}")
            
        except Exception as e:
            self.logger.error(f"Error al guardar straddle: {e}")
    
    def close_straddle(self, ticker):
        """Cierra un straddle activo."""
        if ticker not in self.active_straddles:
            self.logger.warning(f"No hay straddle activo para {ticker}")
            return False
            
        straddle = self.active_straddles[ticker]
        
        self.logger.info(f"Cerrando straddle para {ticker}")
        
        try:
            self.ibkr.ensure_connection()
            ib = self.ibkr.ib
            
            # Crear contratos
            call = create_option_contract(
                ib,
                ticker,
                straddle["expiry"],
                straddle["strike"],
                'C'
            )
            
            put = create_option_contract(
                ib,
                ticker,
                straddle["expiry"],
                straddle["strike"],
                'P'
            )
            
            if not call or not put:
                self.logger.error(f"No se pudieron crear contratos para cerrar {ticker}")
                return False
                
            # Crear órdenes de venta
            qty = straddle["quantity"]
            call_order = MarketOrder('SELL', qty)
            put_order = MarketOrder('SELL', qty)
            
            # Ejecutar órdenes
            ib.placeOrder(call, call_order)
            ib.placeOrder(put, put_order)
            ib.sleep(2)
            
            # Actualizar estado
            straddle["status"] = "CLOSED"
            straddle["close_date"] = datetime.now().strftime('%Y-%m-%d')
            
            # Calcular P&L estimado
            call_data = ib.reqMktData(call, "", False, False)
            put_data = ib.reqMktData(put, "", False, False)
            ib.sleep(2)
            
            call_close = call_data.bid if call_data.bid else call_data.close
            put_close = put_data.bid if put_data.bid else put_data.close
            
            if call_close and put_close:
                entry_cost = straddle["call_price"] + straddle["put_price"]
                exit_value = call_close + put_close
                pnl = (exit_value - entry_cost) * qty
                pnl_pct = (exit_value / entry_cost - 1) * 100
                
                straddle["call_close"] = call_close
                straddle["put_close"] = put_close
                straddle["pnl"] = pnl
                straddle["pnl_pct"] = pnl_pct
                
                self.logger.info(f"P&L para {ticker}: ${pnl:.2f} ({pnl_pct:.2f}%)")
            
            # Guardar datos actualizados
            self.save_straddle(straddle)
            
            # Notificar
            self.notify_straddle_closed(ticker, straddle.get("pnl", 0), straddle.get("pnl_pct", 0))
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error al cerrar straddle para {ticker}: {e}")
            return False
    
    def manage_positions(self):
        """Gestiona posiciones activas (cierre automático post-earnings)."""
        today = datetime.now().date()
        
        # Verificar hora de cierre automático
        now = datetime.utcnow().strftime('%H:%M')
        auto_close_time = self.config["auto_close_time"]
        
        for ticker, straddle in list(self.active_straddles.items()):
            if straddle["status"] != "OPEN":
                continue
                
            # Obtener fecha de earnings
            earnings_date = straddle.get("earnings_date")
            if not earnings_date:
                continue
                
            earnings_date = datetime.strptime(earnings_date, '%Y-%m-%d').date()
            days_after = (today - earnings_date).days
            
            # Cierre automático basado en tiempo
            if days_after >= self.config["exit_days_after"] and now == auto_close_time:
                self.logger.info(f"Cierre automático programado para {ticker} (post-earnings)")
                self.close_straddle(ticker)
    
    def is_market_open(self):
        """Verifica si el mercado está abierto."""
        return self.market_data.is_market_open()
    
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
                    # Actualizar calendario de earnings
                    self.update_earnings_calendar()
                
                # Gestionar posiciones existentes (prioridad)
                self.manage_positions()
                
                # Verificar si el mercado está abierto (o horas extendidas si está habilitado)
                market_open = self.is_market_open() or \
                            (self.config.get("extended_hours", False) and self.is_extended_hours())
                
                if not market_open:
                    self.logger.info("Mercado cerrado. Esperando...")
                    time.sleep(300)  # 5 minutos
                    continue
                    
                # Buscar nuevas oportunidades si no hemos alcanzado límite diario
                if self.daily_trades_count < self.config.get("max_daily_trades", 3):
                    opportunities = self.scan_for_opportunities()
                    
                    # Ejecutar trades para oportunidades encontradas (limitado al máximo diario)
                    for opportunity in opportunities:
                        if self.daily_trades_count >= self.config.get("max_daily_trades", 3):
                            break
                            
                        trade_result = self.execute_trade(opportunity)
                        if trade_result:
                            self.daily_trades_count += 1
                            self.logger.info(f"Straddle ejecutado. Total de trades hoy: {self.daily_trades_count}/{self.config.get('max_daily_trades', 3)}")
                else:
                    self.logger.info(f"Límite diario de straddles alcanzado ({self.daily_trades_count}). Solo gestionando posiciones existentes.")
                
                # Calcular y mostrar PnL actual
                current_pnl = self.calculate_current_pnl()
                if abs(current_pnl - self.daily_pnl) > 1.0:  # Solo actualizar si cambió más de $1
                    self.daily_pnl = current_pnl
                    self.logger.info(f"PnL diario actual: ${self.daily_pnl:.2f}")
                
                # Mostrar resumen cada hora (aproximadamente)
                now = datetime.now()
                if now.minute <= 5 and now.second <= 30:  # Primeros 5 minutos de cada hora
                    self.show_performance_summary()
                
                # Esperar antes del siguiente escaneo
                self.logger.info(f"Esperando {self.config['scan_interval']} segundos para el siguiente escaneo")
                time.sleep(self.config["scan_interval"])
                
        except KeyboardInterrupt:
            self.logger.info("Bucle de estrategia interrumpido por el usuario")
            self.stop()
        except Exception as e:
            self.logger.error(f"Error en bucle principal: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            self.stop()
    
    def is_extended_hours(self):
        """Verifica si estamos en horas extendidas del mercado."""
        # Verificar si es fin de semana
        now = datetime.utcnow()
        if now.weekday() >= 5:  # 5=Sábado, 6=Domingo
            return False
            
        # Horas extendidas (4am-9:30am y 4pm-8pm ET, convertido a UTC)
        # Considerando UTC-4 para EST
        hour = now.hour
        return (8 <= hour < 13) or (20 <= hour < 24)  # 8am-1pm UTC o 8pm-12am UTC
    
    def calculate_current_pnl(self):
        """Calcula el PnL actual de todos los straddles activos."""
        total_pnl = 0.0
        
        for ticker, straddle in self.active_straddles.items():
            if straddle["status"] != "OPEN":
                # Para straddles ya cerrados, usar el PnL registrado
                if "pnl" in straddle:
                    total_pnl += straddle["pnl"]
                continue
                
            # Para straddles abiertos, calcular PnL actual
            try:
                # Recrear contratos
                self.ibkr.ensure_connection()
                ib = self.ibkr.ib
                
                call = create_option_contract(
                    ib,
                    straddle["ticker"],
                    straddle["expiry"],
                    straddle["strike"],
                    'C'
                )
                
                put = create_option_contract(
                    ib,
                    straddle["ticker"],
                    straddle["expiry"],
                    straddle["strike"],
                    'P'
                )
                
                if not call or not put:
                    self.logger.debug(f"No se pudieron recrear contratos para {ticker}")
                    continue
                    
                # Obtener precios actuales
                call_data = ib.reqMktData(call, "", False, False)
                put_data = ib.reqMktData(put, "", False, False)
                ib.sleep(1)  # Tiempo reducido para optimizar
                
                call_price = call_data.last or call_data.close or 0
                put_price = put_data.last or put_data.close or 0
                
                if call_price > 0 and put_price > 0:
                    # Calcular P&L
                    entry_cost = straddle["call_price"] + straddle["put_price"]
                    current_value = call_price + put_price
                    position_pnl = (current_value - entry_cost) * straddle["quantity"]
                    
                    total_pnl += position_pnl
            except Exception as e:
                self.logger.debug(f"Error al calcular PnL para {ticker}: {e}")
        
        return total_pnl
    
    def show_performance_summary(self):
        """Muestra un resumen del rendimiento de la estrategia."""
        self.logger.info("=========== RESUMEN DE RENDIMIENTO ===========")
        self.logger.info(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self.logger.info(f"Straddles ejecutados hoy: {self.daily_trades_count}/{self.config.get('max_daily_trades', 3)}")
        self.logger.info(f"PnL diario: ${self.daily_pnl:.2f}")
        self.logger.info(f"PnL total estimado: ${self.total_pnl + self.daily_pnl:.2f}")
        
        # Contar straddles abiertos y cerrados
        open_count = sum(1 for s in self.active_straddles.values() if s.get("status") == "OPEN")
        closed_count = sum(1 for s in self.active_straddles.values() if s.get("status") == "CLOSED")
        
        self.logger.info(f"Straddles activos: {open_count}")
        self.logger.info(f"Straddles cerrados: {closed_count}")
        self.logger.info("==============================================")
    
    def notify_straddle_opened(self, ticker, strike, quantity, cost):
        """Notifica apertura de straddle."""
        msg = f"Straddle abierto para {ticker} @ {strike} x{quantity} (${cost:.2f})"
        self.logger.info(msg)
        
        try:
            import subprocess
            title = "Straddle Abierto"
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}"'])
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
        except:
            pass
    
    def notify_straddle_closed(self, ticker, pnl, pnl_pct):
        """Notifica cierre de straddle."""
        msg = f"Straddle cerrado para {ticker} - P&L: ${pnl:.2f} ({pnl_pct:.2f}%)"
        self.logger.info(msg)
        
        try:
            import subprocess
            title = "Straddle Cerrado"
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}"'])
            
            # Sonido diferente según resultado
            sound = "/System/Library/Sounds/Submarine.aiff" if pnl > 0 else "/System/Library/Sounds/Funk.aiff"
            subprocess.run(["afplay", sound])
        except:
            pass
    
    def generate_report(self):
        """Genera un informe de rendimiento de la estrategia."""
        straddles_dir = f"{self.config['data_dir']}/straddles"
        
        if not os.path.exists(straddles_dir):
            return "No hay datos disponibles para generar informe"
            
        closed_straddles = []
        open_straddles = []
        
        # Cargar todos los datos de straddles
        for filename in os.listdir(straddles_dir):
            if not filename.endswith("_straddle.json"):
                continue
                
            file_path = f"{straddles_dir}/{filename}"
            
            try:
                with open(file_path, "r") as f:
                    straddle = json.load(f)
                    
                if straddle["status"] == "CLOSED":
                    closed_straddles.append(straddle)
                else:
                    open_straddles.append(straddle)
                    
            except Exception as e:
                self.logger.error(f"Error al cargar straddle {filename}: {e}")
        
        # Si no hay straddles cerrados, mostrar solo abiertos
        if not closed_straddles and not open_straddles:
            return "No hay straddles para analizar"
            
        # Calcular estadísticas para straddles cerrados
        total_trades = len(closed_straddles)
        profitable_trades = sum(1 for s in closed_straddles if s.get("pnl", 0) > 0)
        total_pnl = sum(s.get("pnl", 0) for s in closed_straddles)
        avg_pnl_pct = sum(s.get("pnl_pct", 0) for s in closed_straddles) / total_trades if total_trades > 0 else 0
        
        # Construir informe
        report = []
        report.append("=== INFORME DE RENDIMIENTO: STRADDLE EARNINGS ===")
        report.append(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("")
        
        report.append("ESTADÍSTICAS GLOBALES:")
        report.append(f"Total de operaciones cerradas: {total_trades}")
        if total_trades > 0:
            report.append(f"Operaciones rentables: {profitable_trades} ({profitable_trades/total_trades*100:.2f}%)")
            report.append(f"P&L total: ${total_pnl:.2f}")
            report.append(f"P&L promedio: {avg_pnl_pct:.2f}%")
        report.append("")
        
        report.append("STRADDLES ACTIVOS:")
        if open_straddles:
            for straddle in open_straddles:
                ticker = straddle["ticker"]
                cost = straddle["total_cost"] * straddle["quantity"]
                report.append(f"- {ticker}: Strike {straddle['strike']}, Cantidad: {straddle['quantity']}, Costo: ${cost:.2f}, Earnings: {straddle['earnings_date']}")
        else:
            report.append("No hay straddles activos")
        report.append("")
        
        report.append("ÚLTIMAS OPERACIONES CERRADAS:")
        if closed_straddles:
            # Ordenar por fecha de cierre, más recientes primero
            recent_closed = sorted(closed_straddles, key=lambda x: x.get("close_date", ""), reverse=True)[:5]
            
            for straddle in recent_closed:
                ticker = straddle["ticker"]
                pnl = straddle.get("pnl", 0)
                pnl_pct = straddle.get("pnl_pct", 0)
                close_date = straddle.get("close_date", "Desconocido")
                report.append(f"- {ticker} ({close_date}): P&L ${pnl:.2f} ({pnl_pct:.2f}%)")
        else:
            report.append("No hay operaciones cerradas")
            
        # Guardar informe
        report_str = "\n".join(report)
        report_file = f"{self.config['data_dir']}/earnings_report_{datetime.now().strftime('%Y%m%d')}.txt"
        
        with open(report_file, "w") as f:
            f.write(report_str)
            
        self.logger.info(f"Informe generado: {report_file}")
        
        return report_str
    
    def teardown(self):
        """Cierra recursos y genera informe al detener la estrategia."""
        super().teardown()
        
        # Generar informe final
        report = self.generate_report()
        self.logger.info(f"Informe final generado")
        
        # Notificar cierre
        try:
            import subprocess
            title = "Estrategia Detenida"
            msg = "Earnings Straddle finalizado. Consulta el informe para más detalles."
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}"'])
        except:
            pass
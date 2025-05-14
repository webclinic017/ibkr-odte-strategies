from ..core.strategy_base import StrategyBase
from ..core.options_utils import create_option_contract, get_atm_straddle
from ib_insync import MarketOrder
import json
import os
from datetime import datetime, timedelta
import time

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
                "GOOG", "GOOGL", "ADBE", "CRM", "PYPL"
            ],
            "max_capital_per_trade": 500,
            "polygon_api_key": None,
            "data_dir": "data/earnings",
            "scan_interval": 3600,  # segundos (1 hora)
            "auto_close_time": "14:35",  # Hora UTC para cierre automático
            "entry_days_before": 1,      # Entrar 1 día antes del reporte
            "exit_days_after": 1,        # Salir 1 día después del reporte
            "min_iv_rank": 55,           # IV rank mínimo para entrada (percentil)
            "max_days_to_expiry": 5,     # Expiración máxima para opciones
        }
        
        # Combinar configuración personalizada con valores por defecto
        self.config = {**self.default_config, **(config or {})}
        
        # Datos internos
        self.earnings_calendar = {}  # Calendario de earnings próximos
        self.active_straddles = {}   # Straddles activos
        
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
    
    def update_earnings_calendar(self):
        """Actualiza el calendario de earnings próximos."""
        from ..core.market_data import MarketData
        
        market_data = MarketData(polygon_api_key=self.config.get("polygon_api_key"))
        
        # Obtener datos para los próximos 7 días
        earnings = market_data.get_earnings_calendar(days_ahead=7)
        
        if not earnings:
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
        # Si no hay calendario, actualizar
        if not self.earnings_calendar:
            self.update_earnings_calendar()
            if not self.earnings_calendar:
                return []
                
        opportunities = []
        today = datetime.now().date()
        target_date = (today + timedelta(days=self.config["entry_days_before"])).strftime("%Y-%m-%d")
        
        # Buscar earnings para la fecha objetivo
        earnings_tickers = self.earnings_calendar.get(target_date, [])
        
        for ticker in earnings_tickers:
            # Evitar duplicados si ya tenemos un straddle para este ticker
            if ticker in self.active_straddles:
                continue
                
            # Verificar volatilidad implícita
            iv_rank = self.get_iv_rank(ticker)
            if iv_rank < self.config["min_iv_rank"]:
                self.logger.info(f"IV Rank insuficiente para {ticker}: {iv_rank}%")
                continue
                
            # Crear oportunidad
            opportunity = {
                "ticker": ticker,
                "earnings_date": target_date,
                "timestamp": datetime.now().isoformat(),
                "iv_rank": iv_rank
            }
            
            opportunities.append(opportunity)
            self.logger.info(f"Oportunidad de straddle detectada: {ticker} (Earnings: {target_date}, IV Rank: {iv_rank}%)")
        
        return opportunities
    
    def get_iv_rank(self, ticker):
        """Obtiene el IV Rank para un ticker."""
        # En una implementación completa, se debería obtener datos históricos
        # de volatilidad implícita y calcular el percentil actual
        # Aquí usamos un valor aleatorio para simular
        import random
        return random.randint(40, 90)
    
    def execute_trade(self, opportunity):
        """Ejecuta un straddle para la oportunidad detectada."""
        ticker = opportunity["ticker"]
        
        self.logger.info(f"Ejecutando straddle para {ticker}")
        
        try:
            self.ibkr.ensure_connection()
            ib = self.ibkr.ib
            
            # Obtener fecha de expiración cercana
            expiry_days = self.config["max_days_to_expiry"]
            expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y%m%d")
            
            # Obtener contratos para el straddle ATM
            call, put, current_price = get_atm_straddle(ib, ticker, expiry_date)
            
            if not call or not put:
                self.logger.error(f"No se pudieron crear contratos para {ticker}")
                return None
                
            # Obtener precios de mercado
            call_data = ib.reqMktData(call, "", False, False)
            put_data = ib.reqMktData(put, "", False, False)
            ib.sleep(2)
            
            call_price = call_data.ask if call_data.ask else call_data.close
            put_price = put_data.ask if put_data.ask else put_data.close
            
            if not call_price or not put_price:
                self.logger.error(f"No se pudieron obtener precios para {ticker}")
                return None
                
            # Calcular cantidad basada en capital máximo
            total_cost = call_price + put_price
            max_capital = self.config["max_capital_per_trade"]
            qty = int(max_capital / total_cost) if total_cost > 0 else 0
            
            if qty < 1:
                self.logger.info(f"Capital insuficiente para {ticker}. Costo: ${total_cost:.2f}")
                return None
                
            # Ejecutar órdenes de compra
            call_order = MarketOrder('BUY', qty)
            put_order = MarketOrder('BUY', qty)
            
            call_trade = ib.placeOrder(call, call_order)
            put_trade = ib.placeOrder(put, put_order)
            ib.sleep(2)
            
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
                "close_date": None
            }
            
            # Guardar datos
            self.active_straddles[ticker] = straddle_data
            self.save_straddle(straddle_data)
            
            # Notificar
            self.notify_straddle_opened(ticker, call.strike, qty, total_cost)
            
            return {
                "call_order_id": call_trade.order.orderId,
                "put_order_id": put_trade.order.orderId
            }
            
        except Exception as e:
            self.logger.error(f"Error al ejecutar straddle para {ticker}: {e}")
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
        now = datetime.utcnow()
        
        # Verificar fin de semana
        if now.weekday() >= 5:  # 5 = Sábado, 6 = Domingo
            return False
            
        # Horario de mercado (9:30am - 4:00pm ET)
        now_str = now.strftime('%H:%M')
        return "13:30" <= now_str <= "20:00"  # Convertido a UTC
    
    def run(self):
        """Ejecuta el bucle principal de la estrategia."""
        if not self.active:
            self.logger.warning("La estrategia no está activa. Llama a start() primero.")
            return
            
        try:
            self.logger.info("Iniciando bucle principal de la estrategia")
            
            while self.active:
                # Gestionar posiciones existentes (prioridad)
                self.manage_positions()
                
                # Verificar si el mercado está abierto
                if not self.is_market_open():
                    self.logger.info("Mercado cerrado. Esperando...")
                    time.sleep(300)  # 5 minutos
                    continue
                    
                # Buscar nuevas oportunidades
                opportunities = self.scan_for_opportunities()
                
                # Ejecutar trades para oportunidades encontradas
                for opportunity in opportunities:
                    self.execute_trade(opportunity)
                    
                # Esperar antes del siguiente escaneo
                self.logger.info(f"Esperando {self.config['scan_interval']} segundos para el siguiente escaneo")
                time.sleep(self.config["scan_interval"])
                
        except KeyboardInterrupt:
            self.logger.info("Bucle de estrategia interrumpido por el usuario")
            self.stop()
        except Exception as e:
            self.logger.error(f"Error en bucle principal: {e}")
            self.stop()
    
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
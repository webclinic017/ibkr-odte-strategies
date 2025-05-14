from ..core.strategy_base import StrategyBase
from ..core.options_utils import create_option_contract, get_option_expiry
from ib_insync import MarketOrder
import json
import os
import csv
from datetime import datetime
import time

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
            "min_volume": 500,
            "min_open_interest": 1000,
            "orders_file": "data/odte_breakout_orders.json",
            "log_file": "data/odte_breakout_trades.csv",
            "scan_interval": 60,  # segundos
            "volume_multiplier": 1.2,  # volumen debe ser X veces el volumen inicial
            "tp_multiplier": 1.2,  # take profit como múltiplo de la prima
            "sl_multiplier": 0.6   # stop loss como múltiplo de la prima
        }
        
        # Combinar configuración personalizada con valores por defecto
        self.config = {**self.default_config, **(config or {})}
        
        # Estado interno de la estrategia
        self.initial_ranges = {}  # Rangos iniciales por ticker
        self.active_trades = {}   # Trades activos
        
        # Crear directorios de datos si no existen
        os.makedirs("data", exist_ok=True)
        
    def setup(self):
        """Configuración inicial de la estrategia."""
        super().setup()
        
        self.logger.info("Inicializando estrategia ODTE Breakout")
        
        # Verificar órdenes previas
        self.check_previous_orders()
        
        # Comprobar tickers con expiración 0DTE hoy
        self.tickers = self.filter_odte_tickers()
        if not self.tickers:
            self.logger.warning("No hay tickers disponibles con expiración 0DTE hoy")
        else:
            self.logger.info(f"Tickers disponibles con 0DTE: {self.tickers}")
            
        # Cargar rangos iniciales
        self.load_initial_ranges()
    
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
        from ..core.market_data import MarketData
        
        market_data = MarketData(polygon_api_key=self.config.get("polygon_api_key"))
        
        for ticker in self.tickers:
            data = market_data.get_last_bar(ticker)
            if not data:
                continue
                
            self.initial_ranges[ticker] = {
                "high": data["high"],
                "low": data["low"],
                "volume": data["volume"]
            }
            
            self.logger.info(f"Rango inicial cargado para {ticker}: Alto: {data['high']}, Bajo: {data['low']}, Volumen: {data['volume']}")
    
    def scan_for_opportunities(self):
        """Busca oportunidades de breakout en los tickers configurados."""
        from ..core.market_data import MarketData
        
        if not self.is_trading_allowed():
            return []
            
        market_data = MarketData(polygon_api_key=self.config.get("polygon_api_key"))
        opportunities = []
        
        for ticker in self.tickers:
            if ticker not in self.initial_ranges:
                continue
                
            data = market_data.get_last_bar(ticker)
            if not data:
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
                
                # Calcula parámetros del trade
                premium, qty, sl, tp = self.calculate_trade(signal, data["close"])
                opportunity.update({
                    "premium": premium,
                    "quantity": qty,
                    "stop_loss": sl,
                    "take_profit": tp
                })
                
                # Validar liquidez de la opción
                strike = round(data["close"])
                expiry = get_option_expiry()
                
                if self.validate_option(ticker, signal, strike, expiry):
                    # Calcular score de la señal
                    option_contract = create_option_contract(
                        self.ibkr.ib, 
                        ticker, 
                        expiry, 
                        strike, 
                        'C' if signal == 'CALL' else 'P'
                    )
                    
                    market_data = self.ibkr.ib.reqMktData(option_contract, '', False, False)
                    self.ibkr.ib.sleep(2)
                    
                    score = self.score_signal(ticker, signal, data["close"], self.initial_ranges[ticker], option_contract, market_data)
                    opportunity["score"] = score
                    
                    if score >= 70:
                        opportunities.append(opportunity)
                        self.logger.info(f"Oportunidad válida: {ticker} {signal} con score {score}")
                    else:
                        self.logger.info(f"Señal descartada: {ticker} {signal} con score insuficiente: {score}")
        
        return opportunities
    
    def detect_breakout(self, ticker, price, volume):
        """Detecta señales de breakout."""
        r = self.initial_ranges.get(ticker)
        if not r:
            return None
            
        volume_threshold = r["volume"] * self.config["volume_multiplier"]
        
        if price > r["high"] and volume > volume_threshold:
            return "CALL"
        elif price < r["low"] and volume > volume_threshold:
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
            
        self.ibkr.ensure_connection()
        ib = self.ibkr.ib
        
        try:
            contract = create_option_contract(
                ib, 
                ticker, 
                expiry, 
                strike, 
                'C' if signal_type == 'CALL' else 'P'
            )
            
            if not contract:
                return False
                
            snapshot = ib.reqMktData(contract, "", False, False)
            ib.sleep(2)
            
            details = ib.reqContractDetails(contract)
            if not details:
                self.logger.info(f"{ticker} {signal_type} - Sin detalles de contrato disponibles")
                return False
                
            volume = snapshot.volume if snapshot.volume else 0
            
            # En un entorno real, obtendríamos el open interest correctamente
            # Aquí usamos un valor aproximado
            oi = 0
            try:
                oi = details[0].minTick if hasattr(details[0], "minTick") else 0
            except:
                oi = 0
                
            if volume < min_volume:
                self.logger.info(f"{ticker} {signal_type} - Volumen insuficiente: {volume}")
                return False
                
            if oi < min_oi:
                self.logger.info(f"{ticker} {signal_type} - Open Interest insuficiente: {oi}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error al validar opción {ticker} {signal_type}: {e}")
            return False
    
    def score_signal(self, ticker, signal_type, current_price, range_data, option_contract, market_data, trend_5m=None):
        """Asigna un puntaje a una señal basado en múltiples factores."""
        score = 0
        
        # Volumen elevado
        if range_data and market_data.volume > range_data["volume"] * 1.5:
            score += 20
            self.logger.debug(f"{ticker} +20 puntos por volumen alto")
            
        # Cierre de vela fuerte
        try:
            candle_range = range_data["high"] - range_data["low"]
            if candle_range > 0 and (current_price - range_data["low"]) / candle_range >= 0.75:
                score += 20
                self.logger.debug(f"{ticker} +20 puntos por vela sólida")
        except:
            pass
            
        # Tendencia de acuerdo con la señal
        if trend_5m == "bullish" and signal_type == "CALL":
            score += 20
            self.logger.debug(f"{ticker} +20 puntos por tendencia alcista")
        elif trend_5m == "bearish" and signal_type == "PUT":
            score += 20
            self.logger.debug(f"{ticker} +20 puntos por tendencia bajista")
            
        # Spread ajustado
        if market_data.bid and market_data.ask:
            spread = market_data.ask - market_data.bid
            if spread / market_data.ask <= 0.10:
                score += 20
                self.logger.debug(f"{ticker} +20 puntos por spread bajo")
                
        # Open interest
        ib = self.ibkr.ib
        details = ib.reqContractDetails(option_contract)
        if details and hasattr(details[0], "minTick"):
            oi_approx = details[0].minTick
            if oi_approx > 2000:
                score += 20
                self.logger.debug(f"{ticker} +20 puntos por OI alto")
                
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
            
            while self.active:
                # Verificar si el mercado está abierto
                if not self.is_trading_allowed():
                    self.logger.info("Fuera de horario de trading. Esperando...")
                    time.sleep(60)
                    continue
                    
                # Escanear oportunidades
                opportunities = self.scan_for_opportunities()
                
                # Ejecutar trades para oportunidades encontradas
                for opportunity in opportunities:
                    self.execute_trade(opportunity)
                    
                # Gestionar posiciones existentes
                self.manage_positions()
                
                # Esperar antes del siguiente escaneo
                time.sleep(self.config["scan_interval"])
                
        except KeyboardInterrupt:
            self.logger.info("Bucle de estrategia interrumpido por el usuario")
            self.stop()
        except Exception as e:
            self.logger.error(f"Error en bucle principal: {e}")
            self.stop()
    
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
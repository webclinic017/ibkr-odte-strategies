import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import json
import logging
from ..core.market_data import MarketData

class BacktestEngine:
    """Motor de backtesting para estrategias de trading."""
    
    def __init__(self, strategy_name, start_date, end_date=None, initial_capital=10000):
        self.strategy_name = strategy_name
        self.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        
        if end_date:
            self.end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            self.end_date = datetime.now().date()
            
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.market_data = MarketData()
        
        # Resultados
        self.trades = []
        self.equity_curve = []
        self.performance_metrics = {}
        
        # Configurar logging
        self.logger = self._setup_logger()
        
        # Directorio de resultados
        self.results_dir = f"results/backtest_{strategy_name}_{start_date.replace('-', '')}_{end_date.replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')}"
        os.makedirs(self.results_dir, exist_ok=True)
    
    def _setup_logger(self):
        """Configura el logger para el backtesting."""
        logger = logging.getLogger(f'Backtest.{self.strategy_name}')
        logger.setLevel(logging.DEBUG)
        
        # Crear directorio de logs si no existe
        os.makedirs("logs", exist_ok=True)
        
        # Handler para archivo
        log_file = f"logs/backtest_{self.strategy_name}_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        
        # Handler para consola
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formato
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def load_historical_data(self, symbols, timeframe='day'):
        """
        Carga datos históricos para los símbolos especificados.
        
        Args:
            symbols (list): Lista de símbolos
            timeframe (str): Intervalo de tiempo ('minute', 'hour', 'day')
            
        Returns:
            dict: Diccionario con DataFrames de datos históricos por símbolo
        """
        self.logger.info(f"Cargando datos históricos para {len(symbols)} símbolos")
        
        historical_data = {}
        start_date_str = self.start_date.strftime('%Y-%m-%d')
        end_date_str = self.end_date.strftime('%Y-%m-%d')
        
        for symbol in symbols:
            self.logger.info(f"Cargando datos para {symbol}")
            data = self.market_data.get_historical_data(
                symbol, 
                start_date_str, 
                end_date_str, 
                timeframe
            )
            
            if data is not None:
                historical_data[symbol] = data
                self.logger.info(f"Datos cargados para {symbol}: {len(data)} barras")
            else:
                self.logger.warning(f"No se pudieron cargar datos para {symbol}")
        
        return historical_data
    
    def backtest_odte_breakout(self, config=None):
        """
        Realiza backtest para la estrategia ODTE Breakout.
        
        Args:
            config (dict): Configuración personalizada para la estrategia
            
        Returns:
            dict: Métricas de rendimiento del backtest
        """
        # Configuración por defecto
        default_config = {
            "tickers": ["SPY", "QQQ", "TSLA", "NVDA", "META", "AMD", "AMZN", "AAPL"],
            "risk_per_trade": 100,
            "volume_multiplier": 1.2,
            "tp_multiplier": 1.2,
            "sl_multiplier": 0.6
        }
        
        # Combinar configuración personalizada con valores por defecto
        config = {**default_config, **(config or {})}
        
        self.logger.info(f"Iniciando backtest para ODTE Breakout con {len(config['tickers'])} tickers")
        
        # Cargar datos históricos
        historical_data = self.load_historical_data(config['tickers'])
        
        if not historical_data:
            self.logger.error("No se pudieron cargar datos históricos")
            return None
            
        # Inicializar resultados
        self.trades = []
        self.equity_curve = [self.initial_capital]
        current_capital = self.initial_capital
        
        # Iterar por cada día
        current_date = self.start_date
        while current_date <= self.end_date:
            # Saltar fines de semana
            if current_date.weekday() >= 5:  # 5=Sábado, 6=Domingo
                current_date += timedelta(days=1)
                continue
                
            date_str = current_date.strftime('%Y-%m-%d')
            self.logger.info(f"Procesando fecha: {date_str}")
            
            daily_pnl = 0
            
            for ticker in config['tickers']:
                if ticker not in historical_data:
                    continue
                    
                ticker_data = historical_data[ticker]
                
                # Obtener datos para el día actual
                day_data = ticker_data[ticker_data.index.strftime('%Y-%m-%d') == date_str]
                
                if day_data.empty:
                    continue
                    
                # Simulación simplificada:
                # Usamos el primer precio como rango inicial
                initial_high = day_data.iloc[0]['high']
                initial_low = day_data.iloc[0]['low']
                initial_volume = day_data.iloc[0]['volume']
                
                # Buscar señales de breakout durante el día
                for i in range(1, len(day_data)):
                    bar = day_data.iloc[i]
                    close = bar['close']
                    volume = bar['volume']
                    
                    # Detectar breakout
                    signal = None
                    if close > initial_high and volume > initial_volume * config['volume_multiplier']:
                        signal = "CALL"
                    elif close < initial_low and volume > initial_volume * config['volume_multiplier']:
                        signal = "PUT"
                        
                    if signal:
                        # Calcular parámetros de trade
                        premium = close * 0.015  # Estimación
                        qty = max(1, int(config['risk_per_trade'] / premium))
                        sl = premium * config['sl_multiplier']
                        tp = premium * config['tp_multiplier']
                        
                        # Simular resultado
                        # Para simplificar, usamos movimiento del precio subyacente
                        # En una implementación completa, modelaríamos el comportamiento de opciones
                        
                        # Datos restantes del día
                        remaining_data = day_data.iloc[i+1:] if i+1 < len(day_data) else pd.DataFrame()
                        
                        result = 0
                        exit_price = premium
                        exit_time = None
                        
                        if not remaining_data.empty:
                            for j, future_bar in remaining_data.iterrows():
                                # Modelado muy simplificado del precio de la opción
                                if signal == "CALL":
                                    option_price = premium * (1 + (future_bar['close'] - close) / close)
                                else:  # PUT
                                    option_price = premium * (1 + (close - future_bar['close']) / close)
                                    
                                # Verificar stop loss o take profit
                                if option_price <= sl:
                                    result = (sl - premium) * qty
                                    exit_price = sl
                                    exit_time = j
                                    break
                                elif option_price >= tp:
                                    result = (tp - premium) * qty
                                    exit_price = tp
                                    exit_time = j
                                    break
                                    
                                # Última barra - expira sin tocar SL/TP
                                if j == remaining_data.index[-1]:
                                    result = (option_price - premium) * qty
                                    exit_price = option_price
                                    exit_time = j
                        else:
                            # No quedan más barras, simular expiración
                            result = -premium * qty
                            exit_time = day_data.index[-1]
                        
                        # Registrar trade
                        trade = {
                            "date": date_str,
                            "ticker": ticker,
                            "signal": signal,
                            "entry_time": day_data.index[i],
                            "exit_time": exit_time,
                            "entry_price": close,
                            "premium": premium,
                            "quantity": qty,
                            "exit_price": exit_price,
                            "pnl": result,
                            "status": "TP" if exit_price >= tp else "SL" if exit_price <= sl else "EXPIRED"
                        }
                        
                        self.trades.append(trade)
                        daily_pnl += result
                        
                        self.logger.info(f"Trade: {ticker} {signal} - P&L: ${result:.2f}")
                        
                        # Sólo una señal por ticker por día para simplificar
                        break
            
            # Actualizar capital y curva de equidad
            current_capital += daily_pnl
            self.equity_curve.append(current_capital)
            
            current_date += timedelta(days=1)
        
        # Calcular métricas de rendimiento
        self.calculate_performance_metrics()
        
        # Generar reportes
        self.generate_reports()
        
        return self.performance_metrics
    
    def backtest_earnings_straddle(self, config=None):
        """
        Realiza backtest para la estrategia Earnings Straddle.
        
        Args:
            config (dict): Configuración personalizada para la estrategia
            
        Returns:
            dict: Métricas de rendimiento del backtest
        """
        # Configuración por defecto
        default_config = {
            "tickers": ["TSLA", "NFLX", "NVDA", "AMD", "META", "AMZN", "AAPL", "MSFT"],
            "capital_per_trade": 500,
            "entry_days_before": 1,
            "exit_days_after": 1,
            "min_expected_move": 0.03  # 3% mínimo movimiento esperado
        }
        
        # Combinar configuración personalizada con valores por defecto
        config = {**default_config, **(config or {})}
        
        self.logger.info(f"Iniciando backtest para Earnings Straddle con {len(config['tickers'])} tickers")
        
        # Cargar datos históricos
        historical_data = self.load_historical_data(config['tickers'])
        
        if not historical_data:
            self.logger.error("No se pudieron cargar datos históricos")
            return None
            
        # Cargar fechas de earnings históricas (archivo simulado)
        earnings_file = "data/historical_earnings.json"
        earnings_dates = {}
        
        if os.path.exists(earnings_file):
            try:
                with open(earnings_file, "r") as f:
                    earnings_dates = json.load(f)
            except Exception as e:
                self.logger.error(f"Error al cargar fechas de earnings: {e}")
        else:
            # Simulación de fechas de earnings
            self.logger.warning("Simulando fechas de earnings para el backtest")
            
            for ticker in config['tickers']:
                earnings_dates[ticker] = []
                
                # Generar fechas trimestrales aproximadas
                current_date = self.start_date
                while current_date <= self.end_date:
                    # Añadir una fecha cada ~90 días
                    earnings_dates[ticker].append(current_date.strftime('%Y-%m-%d'))
                    current_date += timedelta(days=90)
        
        # Inicializar resultados
        self.trades = []
        self.equity_curve = [self.initial_capital]
        current_capital = self.initial_capital
        
        # Iterar por cada día
        current_date = self.start_date
        active_straddles = {}
        
        while current_date <= self.end_date:
            # Saltar fines de semana
            if current_date.weekday() >= 5:  # 5=Sábado, 6=Domingo
                current_date += timedelta(days=1)
                continue
                
            date_str = current_date.strftime('%Y-%m-%d')
            self.logger.info(f"Procesando fecha: {date_str}")
            
            daily_pnl = 0
            
            # Verificar straddles para abrir (día antes de earnings)
            for ticker in config['tickers']:
                # Verificar si hay earnings
                ticker_earnings = earnings_dates.get(ticker, [])
                upcoming_earnings = []
                
                for earnings_date in ticker_earnings:
                    earnings_day = datetime.strptime(earnings_date, '%Y-%m-%d').date()
                    days_until = (earnings_day - current_date).days
                    
                    if days_until == config['entry_days_before']:
                        upcoming_earnings.append(earnings_date)
                
                # Abrir straddles para próximos earnings
                for earnings_date in upcoming_earnings:
                    if ticker not in historical_data:
                        continue
                        
                    ticker_data = historical_data[ticker]
                    
                    # Datos del día actual
                    day_data = ticker_data[ticker_data.index.strftime('%Y-%m-%d') == date_str]
                    
                    if day_data.empty:
                        continue
                        
                    # Precio actual para el straddle ATM
                    current_price = day_data.iloc[0]['close']
                    
                    # Estimación simplificada de prima de opciones
                    # En un modelo completo, usaríamos volatilidad implícita
                    call_premium = current_price * 0.03  # 3% del precio
                    put_premium = current_price * 0.03
                    
                    total_cost = call_premium + put_premium
                    qty = int(config['capital_per_trade'] / total_cost) if total_cost > 0 else 0
                    
                    if qty < 1:
                        self.logger.info(f"Capital insuficiente para {ticker} straddle")
                        continue
                        
                    # Abrir straddle
                    straddle = {
                        "ticker": ticker,
                        "entry_date": date_str,
                        "earnings_date": earnings_date,
                        "entry_price": current_price,
                        "call_premium": call_premium,
                        "put_premium": put_premium,
                        "quantity": qty,
                        "status": "OPEN"
                    }
                    
                    active_straddles[f"{ticker}_{earnings_date}"] = straddle
                    self.logger.info(f"Straddle abierto: {ticker} para earnings del {earnings_date}")
            
            # Verificar straddles para cerrar
            for key, straddle in list(active_straddles.items()):
                if straddle["status"] != "OPEN":
                    continue
                    
                ticker = straddle["ticker"]
                earnings_date = straddle["earnings_date"]
                entry_date = straddle["entry_date"]
                
                earnings_day = datetime.strptime(earnings_date, '%Y-%m-%d').date()
                days_after = (current_date - earnings_day).days
                
                # Cerrar después de los días configurados post-earnings
                if days_after >= config['exit_days_after']:
                    if ticker not in historical_data:
                        continue
                        
                    ticker_data = historical_data[ticker]
                    
                    # Datos del día actual
                    day_data = ticker_data[ticker_data.index.strftime('%Y-%m-%d') == date_str]
                    
                    if day_data.empty:
                        continue
                        
                    # Precio actual para calcular valor del straddle
                    current_price = day_data.iloc[0]['close']
                    entry_price = straddle["entry_price"]
                    
                    # Calcular movimiento desde earnings
                    price_change_pct = abs(current_price - entry_price) / entry_price
                    
                    # Modelado muy simplificado del valor de la opción
                    # En un modelo real consideraríamos volatilidad implícita, tiempo, etc.
                    if price_change_pct >= config['min_expected_move']:
                        # Las opciones ganan valor con el movimiento
                        option_value = (straddle["call_premium"] + straddle["put_premium"]) * (1 + price_change_pct)
                    else:
                        # Decay de las opciones si no hay movimiento suficiente
                        option_value = (straddle["call_premium"] + straddle["put_premium"]) * 0.5
                    
                    entry_cost = straddle["call_premium"] + straddle["put_premium"]
                    qty = straddle["quantity"]
                    
                    # Calcular P&L
                    pnl = (option_value - entry_cost) * qty
                    pnl_pct = (option_value / entry_cost - 1) * 100
                    
                    # Actualizar straddle
                    straddle["exit_date"] = date_str
                    straddle["exit_price"] = current_price
                    straddle["price_change_pct"] = price_change_pct * 100
                    straddle["option_value"] = option_value
                    straddle["pnl"] = pnl
                    straddle["pnl_pct"] = pnl_pct
                    straddle["status"] = "CLOSED"
                    
                    # Registrar trade
                    trade = {
                        "date": entry_date,
                        "ticker": ticker,
                        "strategy": "STRADDLE",
                        "entry_date": entry_date,
                        "exit_date": date_str,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "price_change_pct": price_change_pct * 100,
                        "premium": entry_cost,
                        "quantity": qty,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct
                    }
                    
                    self.trades.append(trade)
                    daily_pnl += pnl
                    
                    self.logger.info(f"Straddle cerrado: {ticker} - P&L: ${pnl:.2f} ({pnl_pct:.2f}%)")
                    
                    # Eliminar de activos
                    active_straddles.pop(key)
            
            # Actualizar capital y curva de equidad
            current_capital += daily_pnl
            self.equity_curve.append(current_capital)
            
            current_date += timedelta(days=1)
        
        # Calcular métricas de rendimiento
        self.calculate_performance_metrics()
        
        # Generar reportes
        self.generate_reports()
        
        return self.performance_metrics
    
    def calculate_performance_metrics(self):
        """Calcula métricas de rendimiento del backtest."""
        if not self.trades:
            self.logger.warning("No hay trades para calcular métricas")
            return
            
        # Convertir a DataFrame para análisis
        trades_df = pd.DataFrame(self.trades)
        equity_curve = np.array(self.equity_curve)
        
        # Métricas básicas
        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['pnl'] > 0])
        losing_trades = len(trades_df[trades_df['pnl'] <= 0])
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        total_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
        total_loss = trades_df[trades_df['pnl'] <= 0]['pnl'].sum()
        
        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float('inf')
        
        # Retorno total y anualizado
        total_return = (equity_curve[-1] / equity_curve[0] - 1) * 100
        days = (self.end_date - self.start_date).days
        annual_return = (1 + total_return/100) ** (365/days) - 1 if days > 0 else 0
        annual_return *= 100  # Convertir a porcentaje
        
        # Drawdown
        running_max = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - running_max) / running_max * 100
        max_drawdown = abs(min(drawdown))
        
        # Volatilidad
        daily_returns = np.diff(equity_curve) / equity_curve[:-1]
        volatility = np.std(daily_returns) * np.sqrt(252) * 100  # Anualizada
        
        # Ratio de Sharpe (simplificado)
        sharpe_ratio = (annual_return / 100) / (volatility / 100) if volatility > 0 else 0
        
        # Guardar métricas
        self.performance_metrics = {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_profit": total_profit,
            "total_loss": total_loss,
            "net_profit": total_profit + total_loss,
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "volatility": volatility,
            "sharpe_ratio": sharpe_ratio
        }
        
        self.logger.info(f"Métricas calculadas: {self.performance_metrics}")
    
    def generate_reports(self):
        """Genera reportes y gráficos del backtest."""
        if not self.trades or not self.equity_curve:
            self.logger.warning("No hay datos para generar reportes")
            return
            
        # Crear directorio para reportes
        os.makedirs(self.results_dir, exist_ok=True)
        
        # Guardar trades
        trades_df = pd.DataFrame(self.trades)
        trades_df.to_csv(f"{self.results_dir}/trades.csv", index=False)
        
        # Guardar métricas
        with open(f"{self.results_dir}/metrics.json", "w") as f:
            json.dump(self.performance_metrics, f, indent=2)
            
        # Generar curva de equidad
        self.plot_equity_curve()
        
        # Generar distribución de trades
        if len(self.trades) > 0:
            self.plot_trade_distribution()
            
        # Informe de rendimiento
        self.generate_performance_report()
        
        self.logger.info(f"Reportes generados en {self.results_dir}")
    
    def plot_equity_curve(self):
        """Genera gráfico de curva de equidad."""
        plt.figure(figsize=(12, 6))
        plt.plot(self.equity_curve)
        plt.title('Curva de Equidad')
        plt.xlabel('Días de Trading')
        plt.ylabel('Capital ($)')
        plt.grid(True)
        plt.savefig(f"{self.results_dir}/equity_curve.png")
        plt.close()
    
    def plot_trade_distribution(self):
        """Genera gráfico de distribución de P&L por trade."""
        trades_df = pd.DataFrame(self.trades)
        
        plt.figure(figsize=(12, 6))
        plt.hist(trades_df['pnl'], bins=20, alpha=0.75)
        plt.axvline(x=0, color='r', linestyle='--')
        plt.title('Distribución de P&L por Trade')
        plt.xlabel('P&L ($)')
        plt.ylabel('Frecuencia')
        plt.grid(True)
        plt.savefig(f"{self.results_dir}/pnl_distribution.png")
        plt.close()
        
        # Gráfico de P&L acumulado por ticker
        if 'ticker' in trades_df.columns:
            plt.figure(figsize=(12, 6))
            ticker_pnl = trades_df.groupby('ticker')['pnl'].sum().sort_values()
            ticker_pnl.plot(kind='bar')
            plt.title('P&L Acumulado por Ticker')
            plt.xlabel('Ticker')
            plt.ylabel('P&L Acumulado ($)')
            plt.grid(True)
            plt.savefig(f"{self.results_dir}/ticker_pnl.png")
            plt.close()
    
    def generate_performance_report(self):
        """Genera informe de rendimiento detallado."""
        if not self.performance_metrics:
            return
            
        report = []
        report.append("=" * 50)
        report.append(f"INFORME DE BACKTEST: {self.strategy_name}")
        report.append("=" * 50)
        report.append(f"Período: {self.start_date} a {self.end_date}")
        report.append(f"Capital inicial: ${self.initial_capital}")
        report.append(f"Capital final: ${self.equity_curve[-1]:.2f}")
        report.append("")
        
        report.append("MÉTRICAS DE RENDIMIENTO:")
        report.append(f"Retorno total: {self.performance_metrics['total_return']:.2f}%")
        report.append(f"Retorno anualizado: {self.performance_metrics['annual_return']:.2f}%")
        report.append(f"Máximo drawdown: {self.performance_metrics['max_drawdown']:.2f}%")
        report.append(f"Volatilidad anualizada: {self.performance_metrics['volatility']:.2f}%")
        report.append(f"Ratio de Sharpe: {self.performance_metrics['sharpe_ratio']:.2f}")
        report.append("")
        
        report.append("ESTADÍSTICAS DE TRADING:")
        report.append(f"Total de trades: {self.performance_metrics['total_trades']}")
        report.append(f"Trades ganadores: {self.performance_metrics['winning_trades']} ({self.performance_metrics['win_rate']*100:.2f}%)")
        report.append(f"Trades perdedores: {self.performance_metrics['losing_trades']}")
        report.append(f"Factor de beneficio: {self.performance_metrics['profit_factor']:.2f}")
        report.append(f"Beneficio neto: ${self.performance_metrics['net_profit']:.2f}")
        report.append("")
        
        # Añadir resumen de trades por ticker
        trades_df = pd.DataFrame(self.trades)
        if 'ticker' in trades_df.columns:
            report.append("RENDIMIENTO POR TICKER:")
            ticker_summary = trades_df.groupby('ticker').agg({
                'pnl': ['sum', 'mean', 'count'],
                'pnl_pct': ['mean']
            })
            
            for ticker, data in ticker_summary.iterrows():
                total_pnl = data[('pnl', 'sum')]
                avg_pnl = data[('pnl', 'mean')]
                count = data[('pnl', 'count')]
                avg_pct = data[('pnl_pct', 'mean')] if ('pnl_pct', 'mean') in data else 0
                
                report.append(f"{ticker}: {count} trades, P&L total: ${total_pnl:.2f}, P&L promedio: ${avg_pnl:.2f} ({avg_pct:.2f}%)")
            
            report.append("")
        
        # Escribir informe
        with open(f"{self.results_dir}/performance_report.txt", "w") as f:
            f.write("\n".join(report))
        
        return "\n".join(report)
import requests
import logging
import pandas as pd
from datetime import datetime, timedelta
import os
from .ibkr_connection import IBKRConnection

class MarketData:
    """Clase para obtener y gestionar datos de mercado de diversas fuentes."""
    
    def __init__(self, polygon_api_key=None, cache_dir="cache"):
        self.polygon_api_key = polygon_api_key
        self.cache_dir = cache_dir
        self.logger = logging.getLogger('MarketData')
        self.ibkr = IBKRConnection()
        
        # Crear directorio de caché si no existe
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def get_last_bar(self, symbol, timeframe='minute'):
        """
        Obtiene la última barra de datos para un símbolo desde Polygon.io
        
        Args:
            symbol (str): Símbolo del instrumento
            timeframe (str): Intervalo de tiempo ('minute', 'hour', 'day')
            
        Returns:
            dict: Datos de la última barra o None si hay error
        """
        if not self.polygon_api_key:
            self.logger.error("Se requiere API key de Polygon para obtener datos de mercado")
            return None
            
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={self.polygon_api_key}"
        
        try:
            r = requests.get(url)
            data = r.json()
            
            if "results" in data and data["results"]:
                result = data["results"][0]
                return {
                    "open": result["o"],
                    "high": result["h"],
                    "low": result["l"],
                    "close": result["c"],
                    "volume": result["v"],
                    "timestamp": result["t"]
                }
            else:
                self.logger.warning(f"No hay datos disponibles para {symbol}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error al obtener datos para {symbol}: {e}")
            return None
    
    def get_historical_data(self, symbol, start_date, end_date=None, timeframe='day'):
        """
        Obtiene datos históricos para un símbolo desde Polygon.io
        
        Args:
            symbol (str): Símbolo del instrumento
            start_date (str): Fecha de inicio en formato 'YYYY-MM-DD'
            end_date (str): Fecha de fin en formato 'YYYY-MM-DD' (por defecto hoy)
            timeframe (str): Intervalo de tiempo ('minute', 'hour', 'day')
            
        Returns:
            pandas.DataFrame: DataFrame con datos históricos o None si hay error
        """
        if not self.polygon_api_key:
            self.logger.error("Se requiere API key de Polygon para obtener datos históricos")
            return None
            
        # Establecer fecha de fin si no se proporciona
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
            
        # Convertir fechas a timestamps de Unix (milisegundos)
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)
        
        # Construir URL para la API
        multiplier = 1
        if timeframe == 'minute':
            timespan = 'minute'
        elif timeframe == 'hour':
            timespan = 'hour'
        else:
            timespan = 'day'
            
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{start_date}/{end_date}?adjusted=true&sort=asc&limit=5000&apiKey={self.polygon_api_key}"
        
        # Intentar carga desde caché
        cache_file = f"{self.cache_dir}/{symbol}_{timeframe}_{start_date}_{end_date}.csv"
        if os.path.exists(cache_file):
            try:
                # Verificar frescura de caché (menos de 24 horas)
                file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))
                if file_age < timedelta(hours=24):
                    self.logger.info(f"Cargando datos desde caché para {symbol}")
                    return pd.read_csv(cache_file, index_col=0, parse_dates=True)
            except Exception as e:
                self.logger.warning(f"Error al cargar caché: {e}")
        
        # Realizar solicitud a la API
        try:
            r = requests.get(url)
            data = r.json()
            
            if "results" not in data or not data["results"]:
                self.logger.warning(f"No hay datos históricos disponibles para {symbol}")
                return None
                
            # Convertir a DataFrame
            results = data["results"]
            df = pd.DataFrame(results)
            
            # Renombrar columnas
            df = df.rename(columns={
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                't': 'timestamp'
            })
            
            # Convertir timestamp a datetime y establecer como índice
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.set_index('timestamp')
            
            # Guardar en caché
            df.to_csv(cache_file)
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error al obtener datos históricos para {symbol}: {e}")
            return None
    
    def get_earnings_calendar(self, days_ahead=7):
        """
        Obtiene el calendario de earnings próximos desde Polygon.io
        
        Args:
            days_ahead (int): Número de días hacia adelante para buscar
            
        Returns:
            dict: Diccionario con fechas y símbolos de empresas con earnings
        """
        if not self.polygon_api_key:
            self.logger.error("Se requiere API key de Polygon para obtener calendario de earnings")
            return None
            
        url = f"https://api.polygon.io/v2/reference/financials/upcoming?apiKey={self.polygon_api_key}&limit=50"
        
        try:
            r = requests.get(url)
            data = r.json()
            
            if "results" not in data:
                self.logger.warning("No hay datos de earnings disponibles")
                return {}
                
            results = data["results"]
            earnings_calendar = {}
            
            today = datetime.now().date()
            max_date = today + timedelta(days=days_ahead)
            
            for item in results:
                if "reportingDate" in item:
                    date_str = item["reportingDate"]
                    try:
                        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        if today <= report_date <= max_date:
                            ticker = item["ticker"]
                            if date_str not in earnings_calendar:
                                earnings_calendar[date_str] = []
                            earnings_calendar[date_str].append(ticker)
                    except ValueError:
                        continue
            
            return earnings_calendar
            
        except Exception as e:
            self.logger.error(f"Error al obtener calendario de earnings: {e}")
            return {}
    
    def get_market_hours(self, date=None):
        """
        Obtiene las horas de mercado para una fecha específica
        
        Args:
            date (str): Fecha en formato 'YYYY-MM-DD' (por defecto hoy)
            
        Returns:
            dict: Diccionario con horas de apertura y cierre del mercado
        """
        # Valores por defecto para el mercado estadounidense
        # En una implementación completa se obtendría de una API
        market_hours = {
            "open": "09:30",
            "close": "16:00",
            "pre_market_open": "04:00",
            "post_market_close": "20:00"
        }
        
        return market_hours
    
    def is_market_open(self):
        """
        Determina si el mercado está abierto en este momento
        
        Returns:
            bool: True si el mercado está abierto, False en caso contrario
        """
        # Esta es una implementación simplificada
        # En producción, se recomienda usar una API para horarios de mercado
        now = datetime.utcnow()
        
        # Verificar si es fin de semana
        if now.weekday() >= 5:  # 5 = Sábado, 6 = Domingo
            return False
            
        # Horario de mercado regular (9:30 - 16:00 EST, que es UTC-5/UTC-4)
        # Asumimos UTC-4 para este cálculo simple
        market_open = 13  # 13:00 UTC = 9:00 EST
        market_close = 20  # 20:00 UTC = 16:00 EST
        
        return market_open <= now.hour < market_close
        
    def get_realtime_quote(self, symbol):
        """
        Obtiene cotización en tiempo real desde IBKR
        
        Args:
            symbol (str): Símbolo del instrumento
            
        Returns:
            dict: Datos de cotización o None si hay error
        """
        from ib_insync import Stock
        
        self.ibkr.ensure_connection()
        
        contract = Stock(symbol, 'SMART', 'USD')
        try:
            self.ibkr.ib.qualifyContracts(contract)
            ticker = self.ibkr.ib.reqMktData(contract, '', False, False)
            self.ibkr.ib.sleep(2)  # Esperar a que lleguen los datos
            
            # Verificar si tenemos datos válidos
            last_price = ticker.last if ticker.last else ticker.close
            if not last_price:
                self.logger.warning(f"No se pudo obtener precio para {symbol}")
                return None
                
            return {
                "symbol": symbol,
                "last": ticker.last,
                "bid": ticker.bid,
                "ask": ticker.ask,
                "close": ticker.close,
                "volume": ticker.volume,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error al obtener cotización para {symbol}: {e}")
            return None
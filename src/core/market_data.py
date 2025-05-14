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
        self.ibkr = None  # Inicializamos a None y lo creamos cuando sea necesario
        
        # Crear directorio de caché si no existe
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Imprimir API key para depuración (solo los primeros y últimos caracteres)
        if self.polygon_api_key:
            api_key_len = len(self.polygon_api_key)
            if api_key_len > 8:
                visible_part = self.polygon_api_key[:4] + "..." + self.polygon_api_key[-4:]
                self.logger.info(f"Polygon API key configurada: {visible_part}")
            else:
                self.logger.warning("Polygon API key parece ser demasiado corta")
        else:
            self.logger.warning("No se ha proporcionado Polygon API key")
    
    def get_ibkr_connection(self, client_id=1):
        """Obtiene la conexión a IBKR, inicializándola si es necesario."""
        if self.ibkr is None:
            self.ibkr = IBKRConnection(client_id=client_id)
        return self.ibkr
    
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
            self.logger.debug(f"Solicitando datos de {symbol} a Polygon.io")
            r = requests.get(url)
            data = r.json()
            
            # Para depuración
            if "resultsCount" in data:
                self.logger.debug(f"Recibidos {data['resultsCount']} resultados para {symbol}")
            
            if "results" in data and data["results"]:
                result = data["results"][0]
                self.logger.debug(f"Datos recibidos para {symbol}")
                return {
                    "open": result["o"],
                    "high": result["h"],
                    "low": result["l"],
                    "close": result["c"],
                    "volume": result["v"],
                    "timestamp": result["t"]
                }
            else:
                if "error" in data:
                    self.logger.warning(f"Error en respuesta de Polygon para {symbol}: {data['error']}")
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
            self.logger.debug(f"Solicitando datos históricos de {symbol} a Polygon.io")
            r = requests.get(url)
            data = r.json()
            
            if "resultsCount" in data:
                self.logger.debug(f"Recibidos {data['resultsCount']} resultados históricos para {symbol}")
            
            if "results" not in data or not data["results"]:
                if "error" in data:
                    self.logger.warning(f"Error en respuesta de Polygon para datos históricos de {symbol}: {data['error']}")
                else:
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
        
        # Para debugging, mostrar la URL completa que se está llamando
        self.logger.info(f"Debug - URL de earnings: {url}")
        
        try:
            # Mostrar información de la solicitud
            self.logger.info(f"Solicitando calendario de earnings a Polygon.io")
            
            # Realizar la solicitud HTTP
            r = requests.get(url)
            
            # Mostrar código de respuesta y encabezados
            self.logger.info(f"Debug - Código de respuesta: {r.status_code}")
            self.logger.info(f"Debug - Headers de respuesta: {dict(r.headers)}")
            
            # Verificar el contenido de la respuesta
            response_text = r.text
            self.logger.info(f"Debug - Respuesta completa: {response_text[:1000]}...")  # Mostrar los primeros 1000 caracteres
            
            # Intentar parsear el JSON
            try:
                data = r.json()
                self.logger.info(f"Debug - Claves en la respuesta JSON: {list(data.keys())}")
            except Exception as json_err:
                self.logger.error(f"Debug - Error al parsear JSON: {json_err}")
                return {}
            
            # Procesar los resultados si existen
            if "results" not in data:
                self.logger.warning("No hay datos de earnings disponibles en la respuesta")
                return {}
                
            results = data["results"]
            self.logger.info(f"Debug - Cantidad de resultados: {len(results)}")
            
            # Muestra una muestra de los primeros 2 resultados para depuración
            if results and len(results) > 0:
                self.logger.info(f"Debug - Muestra de resultado: {results[0]}")
                if len(results) > 1:
                    self.logger.info(f"Debug - Muestra de resultado 2: {results[1]}")
            
            earnings_calendar = {}
            
            today = datetime.now().date()
            max_date = today + timedelta(days=days_ahead)
            
            for item in results:
                if "reportingDate" in item:
                    date_str = item["reportingDate"]
                    self.logger.debug(f"Debug - Fecha de reporte encontrada: {date_str}")
                    try:
                        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        if today <= report_date <= max_date:
                            ticker = item["ticker"]
                            if date_str not in earnings_calendar:
                                earnings_calendar[date_str] = []
                            earnings_calendar[date_str].append(ticker)
                    except ValueError as ve:
                        self.logger.error(f"Debug - Error al parsear fecha {date_str}: {ve}")
                else:
                    self.logger.debug(f"Debug - Elemento sin reportingDate: {item}")
            
            self.logger.info(f"Calendario de earnings obtenido: {len(earnings_calendar)} fechas")
            if earnings_calendar:
                for date, tickers in earnings_calendar.items():
                    self.logger.info(f" - {date}: {len(tickers)} tickers")
            
            return earnings_calendar
            
        except requests.exceptions.RequestException as req_e:
            self.logger.error(f"Error de solicitud HTTP: {req_e}")
            return {}
        except Exception as e:
            self.logger.error(f"Error al obtener calendario de earnings: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
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
        
    def get_realtime_quote(self, symbol, client_id=1):
        """
        Obtiene cotización en tiempo real desde IBKR
        
        Args:
            symbol (str): Símbolo del instrumento
            client_id (int): ID de cliente para la conexión IBKR
            
        Returns:
            dict: Datos de cotización o None si hay error
        """
        from ib_insync import Stock
        
        # Obtener conexión IBKR
        if self.ibkr is None or self.ibkr.client_id != client_id:
            self.ibkr = self.get_ibkr_connection(client_id)
            
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
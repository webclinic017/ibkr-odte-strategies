from ib_insync import IB
import os
import logging
from datetime import datetime
import threading

class IBKRConnection:
    """Clase singleton para manejar la conexión con Interactive Brokers API."""
    
    _instances = {}
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        client_id = kwargs.get('client_id', 1)
        
        with cls._lock:
            if client_id not in cls._instances:
                instance = super(IBKRConnection, cls).__new__(cls)
                instance._initialized = False
                cls._instances[client_id] = instance
            return cls._instances[client_id]
        
    def __init__(self, host='127.0.0.1', port=7497, client_id=1, is_paper=True, timeout=30):
        if self._initialized:
            return
            
        self.host = host
        self.port = port
        self.client_id = client_id
        self.is_paper = is_paper
        self.timeout = timeout
        self.ib = IB()
        
        # Configuración para datos de mercado
        self.data_subscriptions = {}
        self.use_delayed_data = True
        
        self.logger = self._setup_logger()
        self._initialized = True
        
    def _setup_logger(self):
        """Configure el logger para la conexión IBKR."""
        logger = logging.getLogger(f'IBKRConnection.ID{self.client_id}')
        logger.setLevel(logging.DEBUG)
        
        os.makedirs("logs", exist_ok=True)
        
        # Handler para archivo
        log_file = f"logs/ibkr_{self.client_id}_{datetime.now().strftime('%Y%m%d')}.log"
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
    
    def connect(self):
        """Establece conexión con IBKR TWS o IB Gateway."""
        if not self.ib.isConnected():
            try:
                self.logger.info(f"Conectando a IBKR con client_id: {self.client_id}")
                self.ib.connect(
                    self.host, 
                    self.port, 
                    clientId=self.client_id, 
                    timeout=self.timeout,
                    readonly=self.is_paper  # Solo lectura para paper trading es seguro
                )
                account_type = "Paper Trading" if self.is_paper else "Live Trading"
                self.logger.info(f"Conectado a IBKR ({account_type}) con client_id: {self.client_id}")
                
                # Configurar el manejo de errores para datos de mercado
                self.ib.errorEvent += self.handle_ib_error
                
                return True
            except Exception as e:
                self.logger.error(f"Error de conexión a IBKR con client_id {self.client_id}: {e}")
                return False
        return True
        
    def handle_ib_error(self, reqId, errorCode, errorString, contract):
        """Maneja errores de la API de IB."""
        # Solo registrar errores relevantes (no los warnings)
        if errorCode >= 100 and errorCode not in [2104, 2106, 2158]:  # Ignorar mensajes de conexión OK
            symbol = contract.symbol if contract else "Unknown"
            self.logger.error(f"Error {errorCode}, reqId {reqId}: {errorString}{', contract: ' + str(contract) if contract else ''}")
            
            # Manejar errores específicos de datos de mercado
            if errorCode == 354:  # Datos de mercado no suscritos
                self.logger.warning(f"No hay suscripción a datos en tiempo real para {symbol}. Intentando datos retrasados.")
                if contract and symbol not in self.data_subscriptions:
                    # Registrar este contrato para usar datos retrasados
                    self.data_subscriptions[symbol] = {'use_delayed': True}
            
            elif errorCode == 200:  # Sin seguridad definida
                self.logger.error(f"El contrato para {symbol} no está bien definido")
                
            elif errorCode in [10, 322, 502]:  # Errores de contrato/datos
                self.logger.error(f"Problemas con el contrato para {symbol}: {errorString}")
    
    def disconnect(self):
        """Cierra la conexión con IBKR."""
        if self.ib.isConnected():
            self.ib.disconnect()
            self.logger.info(f"Desconectado de IBKR (client_id: {self.client_id})")
            
    def ensure_connection(self):
        """Asegura que hay una conexión activa a IBKR."""
        if not self.ib.isConnected():
            return self.connect()
        return True
    
    @classmethod
    def cleanup_all(cls):
        """Cierra todas las conexiones abiertas."""
        with cls._lock:
            for client_id, instance in cls._instances.items():
                if instance.ib.isConnected():
                    # Desuscribir de todos los datos de mercado
                    try:
                        instance.logger.info(f"Cancelando solicitudes de datos de mercado para client_id: {client_id}")
                        instance.ib.cancelMktData(None)  # Cancelar todas
                    except:
                        pass
                        
                    # Desconectar
                    instance.ib.disconnect()
                    instance.logger.info(f"Desconectado de IBKR (client_id: {client_id})")
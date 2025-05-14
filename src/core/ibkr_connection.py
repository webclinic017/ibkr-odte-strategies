from ib_insync import IB
import os
import logging
from datetime import datetime

class IBKRConnection:
    """Clase singleton para manejar la conexión con Interactive Brokers API."""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(IBKRConnection, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
        
    def __init__(self, host='127.0.0.1', port=7497, client_id=1, is_paper=True, timeout=30):
        if self._initialized:
            return
            
        self.host = host
        self.port = port
        self.client_id = client_id
        self.is_paper = is_paper
        self.timeout = timeout
        self.ib = IB()
        self.logger = self._setup_logger()
        self._initialized = True
        
    def _setup_logger(self):
        """Configure el logger para la conexión IBKR."""
        logger = logging.getLogger('IBKRConnection')
        logger.setLevel(logging.DEBUG)
        
        os.makedirs("logs", exist_ok=True)
        
        # Handler para archivo
        log_file = f"logs/ibkr_{datetime.now().strftime('%Y%m%d')}.log"
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
                self.ib.connect(
                    self.host, 
                    self.port, 
                    clientId=self.client_id, 
                    timeout=self.timeout
                )
                account_type = "Paper Trading" if self.is_paper else "Live Trading"
                self.logger.info(f"Conectado a IBKR ({account_type})")
                return True
            except Exception as e:
                self.logger.error(f"Error de conexión a IBKR: {e}")
                return False
        return True
    
    def disconnect(self):
        """Cierra la conexión con IBKR."""
        if self.ib.isConnected():
            self.ib.disconnect()
            self.logger.info("Desconectado de IBKR")
            
    def ensure_connection(self):
        """Asegura que hay una conexión activa a IBKR."""
        if not self.ib.isConnected():
            return self.connect()
        return True
from abc import ABC, abstractmethod
import logging
import os
from datetime import datetime
from ..core.ibkr_connection import IBKRConnection
import colorama

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

class StrategyBase(ABC):
    """Clase base abstracta para todas las estrategias de trading."""
    
    def __init__(self, name, config=None):
        self.name = name
        self.config = config or {}
        self.logger = self._setup_logger()
        
        # Obtener client_id de la configuración o usar valor por defecto (1)
        client_id = int(self.config.get('ibkr_client_id', 1))
        self.logger.info(f"Usando client_id: {client_id} para estrategia {name}")
        
        # Inicializar conexión IBKR con el client_id correcto
        self.ibkr = IBKRConnection(
            host=self.config.get('ibkr_host', '127.0.0.1'),
            port=int(self.config.get('ibkr_port', 7497)),
            client_id=client_id
        )
        
        self.active = False
        self.trades = []
        
    def _setup_logger(self):
        """Configura el logger específico para esta estrategia."""
        logger = logging.getLogger(f'Strategy.{self.name}')
        logger.setLevel(logging.DEBUG)
        
        # Crear directorio de logs si no existe
        os.makedirs("logs", exist_ok=True)
        
        # Handler para archivo (sin colores)
        log_file = f"logs/{self.name}_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(f'[%(asctime)s] %(levelname)s [{self.name}] - %(message)s')
        file_handler.setFormatter(file_formatter)
        
        # Handler para consola (con colores)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        colored_formatter = ColoredFormatter(f'[%(asctime)s] %(levelname)s [{self.name}] - %(message)s')
        console_handler.setFormatter(colored_formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def start(self):
        """Inicia la ejecución de la estrategia."""
        if self.active:
            self.logger.warning("La estrategia ya está activa")
            return False
            
        self.logger.info(f"Iniciando estrategia: {self.name}")
        self.active = True
        self.setup()
        return True
        
    def stop(self):
        """Detiene la ejecución de la estrategia."""
        if not self.active:
            self.logger.warning("La estrategia no está activa")
            return False
            
        self.logger.info(f"Deteniendo estrategia: {self.name}")
        self.active = False
        self.teardown()
        return True
    
    def setup(self):
        """Configuración inicial antes de ejecutar la estrategia."""
        self.ibkr.connect()
    
    def teardown(self):
        """Limpieza final después de detener la estrategia."""
        pass
    
    @abstractmethod
    def scan_for_opportunities(self):
        """Busca oportunidades de trading según la estrategia."""
        pass
    
    @abstractmethod
    def execute_trade(self, opportunity):
        """Ejecuta una operación basada en una oportunidad detectada."""
        pass
    
    @abstractmethod
    def manage_positions(self):
        """Gestiona las posiciones abiertas (stop loss, take profit, etc)."""
        pass
    
    def get_account_summary(self):
        """Obtiene un resumen de la cuenta de trading."""
        self.ibkr.ensure_connection()
        try:
            account_values = self.ibkr.ib.accountSummary()
            summary = {}
            for av in account_values:
                if av.tag in ['NetLiquidation', 'AvailableFunds', 'BuyingPower']:
                    summary[av.tag] = float(av.value)
            return summary
        except Exception as e:
            self.logger.error(f"Error al obtener resumen de cuenta: {e}")
            return None
            
    def get_performance_metrics(self):
        """Calcula métricas de rendimiento de la estrategia."""
        # Base simple - se puede extender en cada estrategia específica
        total_trades = len(self.trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "avg_profit": 0
            }
            
        winning_trades = sum(1 for t in self.trades if t.get('pnl', 0) > 0)
        losing_trades = total_trades - winning_trades
        total_profit = sum(t.get('pnl', 0) for t in self.trades if t.get('pnl', 0) > 0)
        total_loss = sum(t.get('pnl', 0) for t in self.trades if t.get('pnl', 0) < 0)
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float('inf') 
        avg_profit = sum(t.get('pnl', 0) for t in self.trades) / total_trades
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_profit": total_profit,
            "total_loss": total_loss,
            "net_profit": total_profit + total_loss,
            "avg_profit": avg_profit
        }
from ib_insync import Option, Stock, MarketOrder, LimitOrder, StopOrder
from datetime import datetime, timedelta
import logging

logger = logging.getLogger('OptionsUtils')

def get_nearest_strike(price, strikes, direction='nearest'):
    """
    Obtiene el strike más cercano a un precio dado.
    
    Args:
        price (float): Precio de referencia
        strikes (list): Lista de strikes disponibles
        direction (str): 'nearest', 'above', 'below'
        
    Returns:
        float: El strike más cercano
    """
    if not strikes:
        return None
        
    strikes = sorted(strikes)
    
    if direction == 'above':
        for strike in strikes:
            if strike >= price:
                return strike
        return strikes[-1]  # Si ninguno es mayor, devuelve el más alto
                
    elif direction == 'below':
        for strike in reversed(strikes):
            if strike <= price:
                return strike
        return strikes[0]  # Si ninguno es menor, devuelve el más bajo
    
    else:  # nearest
        return min(strikes, key=lambda x: abs(x - price))

def get_option_expiry(days_to_expiry=0):
    """
    Obtiene la fecha de expiración para opciones con los días especificados.
    
    Args:
        days_to_expiry (int): Días hasta la expiración (0 para ODTE)
        
    Returns:
        str: Fecha de expiración en formato YYYYMMDD
    """
    expiry_date = datetime.now() + timedelta(days=days_to_expiry)
    return expiry_date.strftime('%Y%m%d')

def filter_option_chain(chain, min_volume=10, min_open_interest=10, max_spread_pct=0.15):
    """
    Filtra una cadena de opciones según criterios de liquidez.
    
    Args:
        chain (list): Lista de contratos de opciones
        min_volume (int): Volumen mínimo
        min_open_interest (int): Interés abierto mínimo
        max_spread_pct (float): Spread máximo permitido como porcentaje del precio medio
        
    Returns:
        list: Contratos filtrados
    """
    filtered = []
    
    for contract in chain:
        if not hasattr(contract, 'lastGreeks'):
            continue
            
        # Comprobar volumen e interés abierto
        volume = getattr(contract, 'volume', 0) or 0
        open_interest = getattr(contract, 'openInterest', 0) or 0
        
        if volume < min_volume or open_interest < min_open_interest:
            continue
            
        # Comprobar spread
        bid = getattr(contract, 'bid', 0) or 0
        ask = getattr(contract, 'ask', 0) or 0
        
        if bid <= 0 or ask <= 0:
            continue
            
        mid_price = (bid + ask) / 2
        spread_pct = (ask - bid) / mid_price if mid_price > 0 else float('inf')
        
        if spread_pct > max_spread_pct:
            continue
            
        filtered.append(contract)
        
    return filtered

def create_option_contract(ib, symbol, expiry, strike, right, exchange='SMART', currency='USD'):
    """
    Crea y califica un contrato de opciones.
    
    Args:
        ib: Instancia de IB
        symbol (str): Símbolo del subyacente
        expiry (str): Fecha de expiración (YYYYMMDD)
        strike (float): Precio de ejercicio
        right (str): 'C' para call, 'P' para put
        exchange (str): Bolsa (por defecto 'SMART')
        currency (str): Divisa (por defecto 'USD')
        
    Returns:
        Option: Contrato de opciones calificado
    """
    contract = Option(symbol, expiry, strike, right, exchange, currency)
    try:
        ib.qualifyContracts(contract)
        return contract
    except Exception as e:
        logger.error(f"Error al calificar contrato: {symbol} {expiry} {strike} {right}: {e}")
        return None

def get_atm_straddle(ib, symbol, expiry, exchange='SMART', currency='USD'):
    """
    Obtiene un straddle at-the-money para un símbolo y expiración.
    
    Args:
        ib: Instancia de IB
        symbol (str): Símbolo del subyacente
        expiry (str): Fecha de expiración (YYYYMMDD)
        exchange (str): Bolsa (por defecto 'SMART')
        currency (str): Divisa (por defecto 'USD')
        
    Returns:
        tuple: (call_contract, put_contract, current_price)
    """
    # Obtener precio actual
    stock = Stock(symbol, exchange, currency)
    ib.qualifyContracts(stock)
    
    ticker = ib.reqMktData(stock, '', False, False)
    ib.sleep(2)
    
    current_price = ticker.last if ticker.last else ticker.close
    if not current_price:
        logger.error(f"No se pudo obtener precio para {symbol}")
        return None, None, None
        
    # Obtener cadena de opciones
    chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
    if not chains:
        logger.error(f"No se encontraron opciones para {symbol}")
        return None, None, None
        
    # Buscar strikes disponibles para la expiración
    chain = next((c for c in chains if c.exchange == exchange and c.expirations), None)
    if not chain or expiry not in chain.expirations:
        logger.error(f"Expiración {expiry} no disponible para {symbol}")
        return None, None, None
        
    # Encontrar strike ATM
    strikes = chain.strikes
    atm_strike = get_nearest_strike(current_price, strikes)
    
    # Crear contratos
    call = create_option_contract(ib, symbol, expiry, atm_strike, 'C', exchange, currency)
    put = create_option_contract(ib, symbol, expiry, atm_strike, 'P', exchange, currency)
    
    return call, put, current_price
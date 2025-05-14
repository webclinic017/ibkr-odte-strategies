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
        # Verificar disponibilidad de expiraciones
        stock = Stock(symbol, exchange, currency)
        ib.qualifyContracts(stock)
        expiry_params = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        
        # Log detallado de expiraciones disponibles
        if expiry_params:
            available_expirations = []
            available_strikes = []
            for param in expiry_params:
                if param.exchange == exchange:
                    available_expirations.extend(param.expirations)
                    available_strikes.extend(param.strikes)
                    
            logger.debug(f"Expiraciones disponibles para {symbol}: {available_expirations}")
            logger.debug(f"Strikes disponibles para {symbol}: {sorted(available_strikes)[:10]}...")
            
            # Verificar si la fecha solicitada está disponible
            if expiry not in available_expirations:
                closest_expiry = find_closest_expiry(expiry, available_expirations)
                if closest_expiry:
                    logger.warning(f"Expiración {expiry} no disponible para {symbol}. La más cercana es {closest_expiry}")
                    if closest_expiry != expiry:
                        expiry = closest_expiry
                        contract.lastTradeDateOrContractMonth = expiry
                        logger.info(f"Usando expiración alternativa: {expiry} para {symbol}")
                else:
                    logger.error(f"No hay expiraciones disponibles para {symbol}")
                    return None
                    
            # Verificar si el strike solicitado está disponible o encontrar el más cercano
            if available_strikes and strike not in available_strikes:
                closest_strike = min(available_strikes, key=lambda x: abs(x - strike))
                logger.warning(f"Strike {strike} no disponible para {symbol}. El más cercano es {closest_strike}")
                strike = closest_strike
                contract.strike = strike
        else:
            logger.error(f"No se pudieron obtener parámetros de opciones para {symbol}")
            return None
            
        # Intentar calificar el contrato
        ib.qualifyContracts(contract)
        logger.info(f"Contrato calificado: {symbol} {expiry} {strike} {right}")
        return contract
    except Exception as e:
        import traceback
        logger.error(f"Error al calificar contrato: {symbol} {expiry} {strike} {right}: {e}")
        logger.debug(traceback.format_exc())
        return None

def find_closest_expiry(target_expiry, available_expirations):
    """Encuentra la fecha de expiración más cercana a la objetivo."""
    if not available_expirations:
        return None
        
    try:
        # Convertir fechas a objetos datetime para comparación
        target_date = datetime.strptime(target_expiry, '%Y%m%d')
        
        # Convertir todas las expiraciones disponibles a objetos datetime
        expiry_dates = []
        for exp in available_expirations:
            try:
                expiry_dates.append((datetime.strptime(exp, '%Y%m%d'), exp))
            except ValueError:
                continue
                
        if not expiry_dates:
            return None
            
        # Encontrar la más cercana
        closest = min(expiry_dates, key=lambda x: abs((x[0] - target_date).days))
        return closest[1]  # Devolver el string original
    except Exception as e:
        logger.error(f"Error al buscar expiración cercana: {e}")
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
    logger.info(f"Buscando straddle ATM para {symbol} expiración {expiry}")
    
    try:
        # Obtener precio actual
        stock = Stock(symbol, exchange, currency)
        logger.debug(f"Calificando contrato de stock para {symbol}")
        ib.qualifyContracts(stock)
        
        ticker = ib.reqMktData(stock, '', False, False)
        ib.sleep(2)
        
        current_price = ticker.last if ticker.last else ticker.close
        if not current_price:
            logger.error(f"No se pudo obtener precio para {symbol}. last: {ticker.last}, close: {ticker.close}")
            return None, None, None
            
        logger.debug(f"Precio actual de {symbol}: {current_price}")
        
        # Obtener cadena de opciones
        logger.debug(f"Solicitando parámetros de opciones para {symbol}")
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        if not chains:
            logger.error(f"No se encontraron opciones para {symbol}")
            return None, None, None
            
        # Mostrar todas las expiraciones disponibles para diagnóstico
        all_expirations = set()
        all_exchanges = set()
        for c in chains:
            all_exchanges.add(c.exchange)
            all_expirations.update(c.expirations)
            
        logger.debug(f"Exchanges disponibles para {symbol}: {all_exchanges}")
        logger.debug(f"Expiraciones disponibles para {symbol}: {sorted(list(all_expirations))[:10]}...")
        
        # Buscar strikes disponibles para la expiración
        target_chain = None
        for c in chains:
            if c.exchange == exchange and expiry in c.expirations and c.strikes:
                target_chain = c
                break
                
        if not target_chain:
            # Intentar encontrar una expiración cercana si la exacta no está disponible
            closest_expiry = find_closest_expiry(expiry, list(all_expirations))
            if closest_expiry and closest_expiry != expiry:
                logger.warning(f"Expiración {expiry} no disponible para {symbol}. Intentando con {closest_expiry}")
                expiry = closest_expiry
                
                # Buscar de nuevo con la nueva expiración
                for c in chains:
                    if c.exchange == exchange and expiry in c.expirations and c.strikes:
                        target_chain = c
                        break
            
            if not target_chain:
                logger.error(f"No se encontró cadena de opciones válida para {symbol} con expiración {expiry}")
                return None, None, None
        
        # Encontrar strike ATM
        strikes = sorted(target_chain.strikes)
        if not strikes:
            logger.error(f"No hay strikes disponibles para {symbol} con expiración {expiry}")
            return None, None, None
            
        logger.debug(f"Strikes disponibles para {symbol}: {strikes[:10]}...")
        
        atm_strike = get_nearest_strike(current_price, strikes)
        logger.info(f"Strike ATM seleccionado para {symbol}: {atm_strike} (precio actual: {current_price})")
        
        # Crear contratos
        call = create_option_contract(ib, symbol, expiry, atm_strike, 'C', exchange, currency)
        put = create_option_contract(ib, symbol, expiry, atm_strike, 'P', exchange, currency)
        
        if not call or not put:
            logger.error(f"No se pudo crear al menos uno de los contratos para el straddle de {symbol}")
            return None, None, None
            
        logger.info(f"Straddle creado exitosamente para {symbol}: {call.strike} {call.lastTradeDateOrContractMonth}")
        return call, put, current_price
        
    except Exception as e:
        import traceback
        logger.error(f"Error al obtener straddle para {symbol}: {e}")
        logger.debug(traceback.format_exc())
        return None, None, None
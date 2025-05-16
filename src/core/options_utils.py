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
    from datetime import time
    import pytz
    
    # Obtener la hora actual en ET
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    
    # Si es después de las 4 PM ET, considerar el siguiente día hábil para 0DTE
    market_close = time(16, 0)  # 4:00 PM ET
    
    if days_to_expiry == 0 and now_et.time() > market_close:
        # Después del cierre, usar el siguiente día hábil
        next_day = now_et + timedelta(days=1)
        # Si es viernes después del cierre, ir al lunes
        while next_day.weekday() >= 5:  # 5=Sábado, 6=Domingo
            next_day += timedelta(days=1)
        expiry_date = next_day
    else:
        expiry_date = now_et + timedelta(days=days_to_expiry)
        # Asegurar que no caiga en fin de semana
        while expiry_date.weekday() >= 5:
            expiry_date += timedelta(days=1)
    
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
    try:
        # Verificar disponibilidad de expiraciones
        stock = Stock(symbol, exchange, currency)
        ib.qualifyContracts(stock)
        
        # Obtener el precio actual para asegurarnos de que el strike tiene sentido
        try:
            ib.reqMarketDataType(3)  # Usar datos retrasados si real-time no está disponible
            ticker = ib.reqMktData(stock, '', False, False)
            ib.sleep(1)
            
            # Obtener precio, asegurándose de que no sea nan
            prices = [ticker.last, ticker.close, ticker.bid, ticker.ask]
            valid_prices = [p for p in prices if p is not None and p > 0 and not (isinstance(p, float) and (p != p or p == float('inf') or p == float('-inf')))]
            
            if valid_prices:
                current_price = valid_prices[0]
            else:
                # Intentar con datos retrasados
                ib.cancelMktData(stock)
                ib.sleep(0.5)
                ticker = ib.reqMktData(stock, '', True, False)  # True = datos retrasados
                ib.sleep(1)
                
                delayed_prices = [ticker.last, ticker.close, ticker.bid, ticker.ask]
                valid_delayed_prices = [p for p in delayed_prices if p is not None and p > 0 and not (isinstance(p, float) and (p != p or p == float('inf') or p == float('-inf')))]
                
                if valid_delayed_prices:
                    current_price = valid_delayed_prices[0]
                else:
                    current_price = None
                
            if current_price:
                logger.info(f"Precio actual de {symbol}: {current_price}")
                # Si el strike está muy lejos del precio actual, podría ser un problema
                if abs(strike - current_price) / current_price > 0.5:  # Más del 50% de diferencia
                    logger.warning(f"Strike {strike} está demasiado lejos del precio actual {current_price} para {symbol}")
        except Exception as e:
            logger.warning(f"No se pudo obtener el precio actual para {symbol}: {e}")

        expiry_params = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        
        # Log detallado de expiraciones disponibles
        if expiry_params:
            available_expirations = []
            available_strikes = []
            for param in expiry_params:
                if param.exchange == exchange:
                    available_expirations.extend(param.expirations)
                    available_strikes.extend(param.strikes)
            
            # Ordenar para mostrar de forma más clara
            available_expirations = sorted(available_expirations)
            available_strikes = sorted(available_strikes)
                    
            logger.debug(f"Expiraciones disponibles para {symbol}: {available_expirations[:5]}...")
            if available_strikes:
                logger.debug(f"Strikes disponibles para {symbol}: {available_strikes[:5]}...")
                logger.debug(f"Rango de strikes: {min(available_strikes)} - {max(available_strikes)}")
            
            # Verificar si la fecha solicitada está disponible
            if not available_expirations:
                logger.error(f"No hay fechas de expiración disponibles para {symbol}")
                return None
                
            if expiry not in available_expirations:
                closest_expiry = find_closest_expiry(expiry, available_expirations)
                if closest_expiry:
                    logger.warning(f"Expiración {expiry} no disponible para {symbol}. La más cercana es {closest_expiry}")
                    expiry = closest_expiry
                else:
                    logger.error(f"No hay expiraciones cercanas disponibles para {symbol}")
                    return None
                    
            # Verificar si el strike solicitado está disponible o encontrar el más cercano
            if not available_strikes:
                logger.error(f"No hay strikes disponibles para {symbol} con expiración {expiry}")
                return None
                
            if strike not in available_strikes:
                closest_strike = min(available_strikes, key=lambda x: abs(x - strike))
                logger.warning(f"Strike {strike} no disponible para {symbol}. El más cercano es {closest_strike}")
                strike = closest_strike
        else:
            logger.error(f"No se pudieron obtener parámetros de opciones para {symbol}")
            return None
            
        # Crear contrato con los valores ajustados
        contract = Option(symbol, expiry, strike, right, multiplier='100', exchange=exchange, currency=currency)
            
        # Intentar calificar el contrato
        try:
            ib.qualifyContracts(contract)
            logger.info(f"Contrato calificado: {symbol} {expiry} {strike} {right}")
            
            # Configurar para usar datos retrasados si se detectan problemas de suscripción
            has_subscription_error = False
            if hasattr(ib, '_events'):
                for event in ib._events.get('errorEvent', []):
                    if '10091' in str(event) or '10089' in str(event):
                        has_subscription_error = True
                        break
                        
            if has_subscription_error:
                logger.warning(f"Detectado problema de suscripción de datos para {symbol}. Configurando para usar datos retrasados.")
                try:
                    ib.reqMarketDataType(3)  # 3 = Usar delayed data cuando real-time no está disponible
                except Exception as e:
                    logger.warning(f"No se pudo configurar datos retrasados: {e}")
                    
            return contract
        except Exception as qual_e:
            no_security_def = "No security definition has been found" in str(qual_e)
            if no_security_def:
                logger.error(f"No existe definición de seguridad para {symbol} {expiry} {strike} {right}")
                
                # Intentar con otro strike cercano
                if available_strikes and len(available_strikes) > 1:
                    # Filtrar strikes cercanos al original
                    nearby_strikes = [s for s in available_strikes if abs(s - strike) / strike < 0.2]  # Dentro del 20%
                    if nearby_strikes:
                        alt_strike = nearby_strikes[len(nearby_strikes) // 2]  # Tomar uno del medio
                        logger.warning(f"Intentando con strike alternativo: {alt_strike} para {symbol}")
                        alt_contract = Option(symbol, expiry, alt_strike, right, multiplier='100', exchange=exchange, currency=currency)
                        try:
                            ib.qualifyContracts(alt_contract)
                            logger.info(f"Contrato alternativo calificado: {symbol} {expiry} {alt_strike} {right}")
                            return alt_contract
                        except:
                            pass
            
            # Si llegamos aquí, no pudimos calificar ningún contrato
            logger.error(f"Error al calificar contrato: {symbol} {expiry} {strike} {right}: {qual_e}")
            return None
            
    except Exception as e:
        import traceback
        logger.error(f"Error al crear contrato: {symbol} {expiry} {strike} {right}: {e}")
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
        
        current_price = None
        
        # Intento 1: Usar reqMktData con datos en tiempo real
        try:
            logger.info(f"Solicitando precio en tiempo real para {symbol}")
            # Primero configurar para datos retrasados si es necesario
            ib.reqMarketDataType(3)  # 3 = usar datos retrasados cuando real-time no esté disponible
            ticker = ib.reqMktData(stock, '', False, False)
            ib.sleep(2)
            
            # Obtener precio, asegurándose de que no sea nan
            prices = [ticker.last, ticker.close, ticker.bid, ticker.ask, ticker.high, ticker.low]
            valid_prices = [p for p in prices if p is not None and p > 0 and not (isinstance(p, float) and (p != p or p == float('inf') or p == float('-inf')))]
            
            if valid_prices:
                current_price = valid_prices[0]
                logger.info(f"Precio en tiempo real de {symbol}: {current_price}")
        except Exception as e:
            logger.warning(f"Error al obtener datos en tiempo real para {symbol}: {e}")
            
        # Intento 2: Usar reqMktData con datos retrasados
        if not current_price:
            try:
                logger.info(f"Solicitando datos retrasados para {symbol}")
                
                try:
                    ib.cancelMktData(stock)  # Cancelar solicitud anterior
                    ib.sleep(0.5)
                except:
                    pass
                
                # Solicitar datos retrasados con genericTickList=233 (para datos RTVolume)
                delayed_ticker = ib.reqMktData(stock, '233', True, False)
                ib.sleep(3)
                
                # Obtener precio, asegurándose de que no sea nan
                delayed_prices = [delayed_ticker.last, delayed_ticker.close, delayed_ticker.bid, delayed_ticker.ask]
                valid_delayed_prices = [p for p in delayed_prices if p is not None and p > 0 and not (isinstance(p, float) and (p != p or p == float('inf') or p == float('-inf')))]
                
                if valid_delayed_prices:
                    current_price = valid_delayed_prices[0]
                    logger.info(f"Precio retrasado de {symbol}: {current_price}")
            except Exception as delayed_e:
                logger.warning(f"Error al obtener datos retrasados para {symbol}: {delayed_e}")
        
        # Intento 3: Usar reqHistoricalData para obtener el precio de cierre más reciente
        if not current_price:
            try:
                logger.info(f"Obteniendo datos históricos recientes para {symbol}")
                from datetime import datetime, timedelta
                end_time = datetime.now().strftime('%Y%m%d %H:%M:%S')
                bars = ib.reqHistoricalData(
                    stock,
                    end_time,
                    '1 D',  # 1 día
                    '1 day',  # Barras diarias
                    'TRADES',
                    useRTH=True,
                    formatDate=1
                )
                
                if bars and len(bars) > 0:
                    latest_bar = bars[-1]
                    current_price = latest_bar.close
                    logger.info(f"Precio histórico reciente para {symbol}: {current_price}")
            except Exception as hist_e:
                logger.warning(f"Error al obtener datos históricos para {symbol}: {hist_e}")
        
        # Intento 4: Obtener precio de ticker predefinido (hardcoded para tickers comunes y agregar RBLX)
        if not current_price:
            default_prices = {
                "SPY": 580.0,
                "QQQ": 515.0,
                "AAPL": 185.0,
                "MSFT": 400.0,
                "NVDA": 950.0,
                "GOOGL": 180.0,
                "AMZN": 185.0,
                "META": 480.0,
                "TSLA": 180.0,
                "AMD": 160.0,
                "NFLX": 640.0,
                "COIN": 250.0,
                "ROKU": 65.0,
                "RBLX": 75.0,
                "SNAP": 15.0,
                "UBER": 75.0,
                "DIS": 110.0,
                "V": 285.0,
                "JPM": 205.0
            }
            
            if symbol in default_prices:
                current_price = default_prices[symbol]
                logger.info(f"Usando precio predefinido para {symbol}: {current_price}")
        
        # Intento 5: Usar los detalles del contrato para estimar un precio
        if not current_price:
            try:
                details = ib.reqContractDetails(stock)
                if details and len(details) > 0:
                    # Intentar obtener el último precio negociado reportado
                    summary_details = details[0]
                    if hasattr(summary_details, 'marketName') and summary_details.marketName:
                        logger.info(f"Mercado para {symbol}: {summary_details.marketName}")
                    
                    # Estimar un precio (no es ideal, pero es mejor que nada)
                    if hasattr(summary_details, 'minTick') and summary_details.minTick > 0:
                        min_tick = float(summary_details.minTick)
                        # Estimar un precio basado en rangos típicos
                        estimated_price = min_tick * 1000  # 1000 veces el tick mínimo como estimación
                        logger.info(f"Precio estimado para {symbol} (basado en tick mínimo): {estimated_price}")
                        current_price = estimated_price
                        
                    # Alternativa: buscar un precio en los campos disponibles
                    if not current_price and hasattr(summary_details, 'stockType') and hasattr(summary_details, 'industry'):
                        logger.info(f"Tipo de stock: {summary_details.stockType}, Industria: {summary_details.industry}")
                        current_price = 100.0  # Precio genérico
                        logger.info(f"Usando precio genérico para {symbol}: {current_price}")
            except Exception as e:
                logger.error(f"Error al obtener detalles del contrato para {symbol}: {e}")
        
        # Si aún no tenemos precio, usar un valor por defecto razonable como último recurso
        if not current_price:
            logger.warning(f"No se pudo obtener precio para {symbol} por ningún método. Usando precio por defecto.")
            current_price = 100.0  # Precio predeterminado
            
        logger.info(f"Precio final usado para {symbol}: {current_price}")
            
        logger.debug(f"Precio final usado para {symbol}: {current_price}")
        
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
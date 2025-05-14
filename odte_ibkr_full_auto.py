from ib_insync import *
import requests
import csv
import json
import time
import os
from datetime import datetime

# ========== CONFIG ==========
API_KEY = "TU_API_KEY_AQUI"
IBKR_HOST = '127.0.0.1'
IBKR_PORT = 7497
IBKR_CLIENT_ID = 1
CAPITAL_MAXIMO = 10000
RIESGO_POR_TRADE = 100
ORDERS_FILE = 'ibkr_odte_orders.json'
LOG_FILE = 'odte_trades_exec.csv'
TICKERS = ["SPY", "QQQ", "TSLA", "NVDA", "META", "AMD", "AMZN", "AAPL"]

# ========== INIT ==========
LOG_DIARIO = f"logs_odte/odte_log_{datetime.now().strftime('%Y%m%d')}.log"

def log_debug(msg):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    linea = f"{timestamp} {msg}"
    print(linea)
    os.makedirs("logs_odte", exist_ok=True)
    with open(LOG_DIARIO, "a") as f:
        f.write(linea + "\n")

ib = IB()
rango_inicial = {}
trades_activos = {}

# ========== CONEXIÓN ==========
def conectar_ibkr():
    if not ib.isConnected():
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID)
        log_debug("[IBKR] Conectado.")

def desconectar_ibkr():
    if ib.isConnected():
        ib.disconnect()
        log_debug("[IBKR] Desconectado.")

# ========== API POLYGON ==========
def get_last_minute_data(ticker):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev?adjusted=true&apiKey={API_KEY}"
    try:
        r = requests.get(url)
        data = r.json()
        if "results" in data and data["results"]:
            d = data["results"][0]
            return {"open": d["o"], "high": d["h"], "low": d["l"], "close": d["c"], "volume": d["v"]}
    except Exception as e:
        print(f"[ERROR] API {ticker}: {e}")
    return None

# ========== DETECCIÓN SETUP ==========
def detectar_breakout(ticker, precio, volumen):
    r = rango_inicial.get(ticker)
    if not r:
        return None
    if precio > r["high"] and volumen > r["volumen"]:
        return "CALL"
    elif precio < r["low"] and volumen > r["volumen"]:
        return "PUT"
    return None

def calcular_trade(tipo, precio):
    premium = precio * 0.015
    qty = max(1, int(RIESGO_POR_TRADE / premium))
    sl = premium * 0.6
    tp = premium * 1.2
    return round(premium, 2), qty, round(sl, 2), round(tp, 2)

# ========== ORDEN IBKR ==========
def enviar_orden_ibkr(ticker, tipo, strike, expiry, qty):
    conectar_ibkr()
    contract = Option(ticker, expiry, strike, 'C' if tipo == 'CALL' else 'P', 'SMART', 'USD')
    ib.qualifyContracts(contract)
    order = MarketOrder('BUY', qty)
    trade = ib.placeOrder(contract, order)
    ib.sleep(2)
    return trade.order.orderId

def guardar_orden_json(data):
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, 'r') as f:
            store = json.load(f)
    else:
        store = {}
    store[data['orderId']] = data
    with open(ORDERS_FILE, 'w') as f:
        json.dump(store, f, indent=2)

# ========== LOG Y TRADE ==========
def registrar_trade(ticker, tipo, precio, premium, qty, sl, tp, orden_id, estado="ENVIADA"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = {
        "fecha": ts, "ticker": ticker, "tipo": tipo, "precio_subyacente": precio,
        "premium_est": premium, "cantidad": qty, "SL": sl, "TP": tp,
        "orden_id": orden_id, "resultado": estado
    }
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(row)
    guardar_orden_json(row)
    print(f"[TRADE] {ticker} {tipo} {qty}c SL:{sl} TP:{tp} ORDEN:{orden_id}")

# ========== LOOP ==========
def mercado_abierto():
    now = datetime.utcnow()
    return 13 <= now.hour <= 15

def main():
    print(">> SISTEMA ODTE AUTO CON IBKR ONLINE <<")
    while True:
        if not mercado_abierto():
            log_debug("[INFO] Fuera de horario. Esperando...")
            time.sleep(60)
            continue

        for ticker in TICKERS:
            datos = get_last_minute_data(ticker)
            if not datos:
                continue

            if ticker not in rango_inicial:
                rango_inicial[ticker] = {"high": datos["high"], "low": datos["low"], "volumen": datos["volume"]}
                print(f"[INIT] {ticker} rango inicial cargado")
                continue

            señal = detectar_breakout(ticker, datos["close"], datos["volume"])
            if señal:
                premium, qty, sl, tp = calcular_trade(señal, datos["close"])
                strike = round(datos["close"])
                expiry = datetime.now().strftime('%Y%m%d')
                orden_id = enviar_orden_ibkr(ticker, señal, strike, expiry, qty)
                registrar_trade(ticker, señal, datos["close"], premium, qty, sl, tp, orden_id)
            else:
                print(f"[CHECK] {ticker} sin señal.")
        time.sleep(60)

if __name__ == "__main__":
    main()

def verificar_ordenes_previas():
    if not os.path.exists(ORDERS_FILE):
        return
    conectar_ibkr()
    with open(ORDERS_FILE, 'r') as f:
        ordenes = json.load(f)

    for orden_id, datos in ordenes.items():
        estado_actual = "DESCONOCIDO"
        try:
            ordenes_abiertas = ib.reqOpenOrders()
            match = next((o for o in ordenes_abiertas if o.orderId == int(orden_id)), None)
            if match:
                estado_actual = "ABIERTA"
            else:
                ejecuciones = ib.reqExecutions()
                ejec = [e for e in ejecuciones if e.orderId == int(orden_id)]
                estado_actual = "EJECUTADA" if ejec else "NO_ENCONTRADA"
        except Exception as e:
            print(f"[ERROR] Verificando orden {orden_id}: {e}")
            continue

        print(f"[RECUPERACIÓN] Orden {orden_id} - {datos['ticker']} está {estado_actual}")
        datos["resultado"] = estado_actual

        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=datos.keys())
            if f.tell() == 0:
                writer.writeheader()
            writer.writerow(datos)

verificar_ordenes_previas()

def cerrar_posicion_ibkr(ticker, tipo, strike, expiry, qty):
    conectar_ibkr()
    contract = Option(ticker, expiry, strike, 'C' if tipo == 'CALL' else 'P', 'SMART', 'USD')
    ib.qualifyContracts(contract)
    orden = MarketOrder('SELL', qty)
    trade = ib.placeOrder(contract, orden)
    ib.sleep(2)
    print(f"[CERRADA] {ticker} posición cerrada - {qty}c {tipo} @ Strike {strike}")
    return trade.order.orderId

def seguimiento_activo():
    if not os.path.exists(ORDERS_FILE):
        return
    conectar_ibkr()
    with open(ORDERS_FILE, 'r') as f:
        ordenes = json.load(f)

    for orden_id, datos in ordenes.items():
        if datos.get("resultado") not in ["ENVIADA", "ABIERTA"]:
            continue

        contrato = Option(
            symbol=datos["ticker"],
            lastTradeDateOrContractMonth=datos["expiry"],
            strike=datos["strike"],
            right='C' if datos["tipo"] == 'CALL' else 'P',
            exchange='SMART',
            currency='USD'
        )
        ib.qualifyContracts(contrato)
        md = ib.reqMktData(contrato, "", False, False)
        ib.sleep(2)

        premium_actual = md.last if md.last else md.close
        if not premium_actual:
            continue

        if premium_actual <= datos["SL"]:
            print(f"[SL HIT] {datos['ticker']} SL alcanzado: {premium_actual:.2f} <= {datos['SL']:.2f}")
            cerrar_posicion_ibkr(datos["ticker"], datos["tipo"], datos["strike"], datos["expiry"], datos["cantidad"])
            datos["resultado"] = "STOP"
        elif premium_actual >= datos["TP"]:
            print(f"[TP HIT] {datos['ticker']} TP alcanzado: {premium_actual:.2f} >= {datos['TP']:.2f}")
            cerrar_posicion_ibkr(datos["ticker"], datos["tipo"], datos["strike"], datos["expiry"], datos["cantidad"])
            datos["resultado"] = "TP"

        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=datos.keys())
            if f.tell() == 0:
                writer.writeheader()
            writer.writerow(datos)

    with open(ORDERS_FILE, 'w') as f:
        json.dump(ordenes, f, indent=2)

seguimiento_activo()

def tiene_expiracion_hoy(ticker):
    conectar_ibkr()
    contract = Stock(ticker, 'SMART', 'USD')
    params = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
    if not params:
        return False

    expiraciones = params[0].expirations
    hoy = datetime.now().strftime('%Y%m%d')
    return hoy in expiraciones


# Filtro de expiración ODTE por ticker
tickers_filtrados = [t for t in TICKERS if tiene_expiracion_hoy(t)]
print(f"[CHECK] Tickers con expiración ODTE hoy: {tickers_filtrados}")

for ticker in tickers_filtrados:
    datos = get_last_minute_data(ticker)
    if not datos:
        continue

    if ticker not in rango_inicial:
        rango_inicial[ticker] = {"high": datos["high"], "low": datos["low"], "volumen": datos["volume"]}
        print(f"[INIT] {ticker} rango inicial cargado")
        continue

    señal = detectar_breakout(ticker, datos["close"], datos["volume"])
    if señal:
        premium, qty, sl, tp = calcular_trade(señal, datos["close"])
        strike = round(datos["close"])
        expiry = datetime.now().strftime('%Y%m%d')
        orden_id = enviar_orden_ibkr(ticker, señal, strike, expiry, qty)
        registrar_trade(ticker, señal, datos["close"], premium, qty, sl, tp, orden_id)
    else:
        print(f"[CHECK] {ticker} sin señal.")

def notificar_macos(titulo, mensaje):
    import os
    mensaje_limpio = mensaje.replace('"', '\"')
    os.system(f'''osascript -e 'display notification "{mensaje_limpio}" with title "{titulo}"' ''')


# Llamadas automáticas dentro del flujo del script
# Por ejemplo, después de enviar una orden
def notificar_orden(ticker, tipo, strike, premium):
    notificar_macos("Orden Ejecutada", f"{ticker} {tipo} strike {strike} @ {premium:.2f}")

# Después de cerrar por SL o TP
def notificar_cierre(ticker, tipo, resultado):
    notificar_macos("Cierre de Posición", f"{ticker} {tipo} cerrado por {resultado}")

import subprocess

def notificar_macos(titulo, mensaje, tipo="info"):
    import os
    mensaje_limpio = mensaje.replace('"', '\"')
    os.system(f'''osascript -e 'display notification "{mensaje_limpio}" with title "{titulo}"' ''')

    # Reproducir sonido distinto según tipo
    if tipo == "orden":
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
    elif tipo == "tp":
        subprocess.run(["afplay", "/System/Library/Sounds/Submarine.aiff"])
    elif tipo == "sl":
        subprocess.run(["afplay", "/System/Library/Sounds/Funk.aiff"])
    elif tipo == "error":
        subprocess.run(["afplay", "/System/Library/Sounds/Basso.aiff"])
    else:
        subprocess.run(["afplay", "/System/Library/Sounds/Pop.aiff"])

def notificar_orden(ticker, tipo, strike, premium):
    notificar_macos("Orden Ejecutada", f"{ticker} {tipo} strike {strike} @ {premium:.2f}", tipo="orden")

def notificar_cierre(ticker, tipo, resultado):
    notificar_macos("Cierre de Posición", f"{ticker} {tipo} cerrado por {resultado}", tipo="tp" if resultado == "TP" else "sl")


def resumen_final():
    if not os.path.exists(LOG_FILE):
        return

    hoy = datetime.now().strftime('%Y-%m-%d')
    trades_hoy = []
    with open(LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["fecha"].startswith(hoy):
                trades_hoy.append(row)

    total = len(trades_hoy)
    tp = sum(1 for t in trades_hoy if t["resultado"] == "TP")
    sl = sum(1 for t in trades_hoy if t["resultado"] == "STOP")
    pendientes = sum(1 for t in trades_hoy if t["resultado"] in ["ENVIADA", "ABIERTA"])
    cerradas = total - pendientes

    mensaje = f"Total: {total}, TP: {tp}, SL: {sl}, Cerradas: {cerradas}, Pendientes: {pendientes}"
    notificar_macos("Resumen Diario ODTE", mensaje, tipo="info")


if not mercado_abierto():
    resumen_final()

def cerrar_operaciones_abiertas():
    if not os.path.exists(ORDERS_FILE):
        return

    conectar_ibkr()
    with open(ORDERS_FILE, 'r') as f:
        ordenes = json.load(f)

    modificadas = 0
    for orden_id, datos in ordenes.items():
        if datos.get("resultado") in ["TP", "STOP", "EXPIRADA"]:
            continue

        contrato = Option(
            symbol=datos["ticker"],
            lastTradeDateOrContractMonth=datos["expiry"],
            strike=datos["strike"],
            right='C' if datos["tipo"] == 'CALL' else 'P',
            exchange='SMART',
            currency='USD'
        )
        ib.qualifyContracts(contrato)
        md = ib.reqMktData(contrato, "", False, False)
        ib.sleep(2)

        precio = md.last if md.last else md.close
        if precio:
            cerrar_posicion_ibkr(datos["ticker"], datos["tipo"], datos["strike"], datos["expiry"], datos["cantidad"])
            datos["resultado"] = "CERRADA_FORZADA"
            notificar_cierre(datos["ticker"], datos["tipo"], "CERRADA_FORZADA")
        else:
            datos["resultado"] = "EXPIRADA"
            notificar_cierre(datos["ticker"], datos["tipo"], "EXPIRADA")

        modificadas += 1

        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=datos.keys())
            if f.tell() == 0:
                writer.writeheader()
            writer.writerow(datos)

    with open(ORDERS_FILE, 'w') as f:
        json.dump(ordenes, f, indent=2)

    log_debug(f"[CIERRE AUTO] {modificadas} operaciones finalizadas o marcadas como expiradas.")


hora_actual = datetime.utcnow().strftime('%H:%M')
if hora_actual == "16:45":
    cerrar_operaciones_abiertas()

def horario_apertura_valido():
    ahora = datetime.utcnow().strftime('%H:%M')
    return "13:00" <= ahora <= "16:30"

def obtener_saldo_estimado():
    if not os.path.exists(LOG_FILE):
        return 0, 0
    hoy = datetime.now().strftime('%Y-%m-%d')
    saldo_inicial = 0
    saldo_final = 0
    with open(LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row["fecha"].startswith(hoy):
                continue
            premium = float(row["premium_est"])
            qty = int(row["cantidad"])
            sl = float(row["SL"])
            tp = float(row["TP"])
            if row["resultado"] == "TP":
                saldo_final += (tp - premium) * qty
            elif row["resultado"] == "STOP":
                saldo_final += (sl - premium) * qty
            elif row["resultado"] in ["CERRADA_FORZADA", "EXPIRADA"]:
                saldo_final += (-premium) * qty
            else:
                saldo_final += 0
            saldo_inicial -= premium * qty
    return round(saldo_inicial, 2), round(saldo_inicial + saldo_final, 2)

def resumen_final():
    if not os.path.exists(LOG_FILE):
        return

    hoy = datetime.now().strftime('%Y-%m-%d')
    trades_hoy = []
    with open(LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["fecha"].startswith(hoy):
                trades_hoy.append(row)

    total = len(trades_hoy)
    tp = sum(1 for t in trades_hoy if t["resultado"] == "TP")
    sl = sum(1 for t in trades_hoy if t["resultado"] == "STOP")
    pendientes = sum(1 for t in trades_hoy if t["resultado"] in ["ENVIADA", "ABIERTA"])
    forzadas = sum(1 for t in trades_hoy if t["resultado"] == "CERRADA_FORZADA")
    expiradas = sum(1 for t in trades_hoy if t["resultado"] == "EXPIRADA")
    cerradas = total - pendientes

    saldo_ini, saldo_fin = obtener_saldo_estimado()
    mensaje = f"Trades: {total} | TP: {tp} | SL: {sl} | Forzadas: {forzadas} | Expiradas: {expiradas} | $Inicio: {saldo_ini} | $Final: {saldo_fin}"
    notificar_macos("Resumen Diario ODTE", mensaje, tipo="info")


if not horario_apertura_valido():
    log_debug("[RESTRICCIÓN] Fuera de horario válido para nuevas entradas.")
    resumen_final()
    exit()

def exportar_resumen_txt(mensaje):
    os.makedirs("resumenes", exist_ok=True)
    filename = f"resumenes/resumen_odte_{datetime.now().strftime('%Y%m%d')}.txt"
    with open(filename, "w") as f:
        f.write(f"Resumen Diario ODTE - {datetime.now().strftime('%Y-%m-%d')}
")
        f.write("="*40 + "\n")
        f.write(mensaje + "\n")
    log_debug(f"[EXPORT] Resumen diario guardado en {filename}")


    exportar_resumen_txt(mensaje)

def opcion_valida(ticker, tipo, strike, expiry, min_vol=500, min_oi=1000):
    conectar_ibkr()
    contract = Option(ticker, expiry, strike, 'C' if tipo == 'CALL' else 'P', 'SMART', 'USD')
    ib.qualifyContracts(contract)
    snapshot = ib.reqMktData(contract, "", False, False)
    ib.sleep(2)

    details = ib.reqContractDetails(contract)
    if not details:
        log_debug(f"[FILTRO] {ticker} {tipo} NO tiene detalles de contrato.")
        return False

    vol = snapshot.volume if snapshot.volume else 0
    oi = details[0].contract.lastTradeDateOrContractMonth if details else 0  # Fallback

    try:
        oi = details[0].minTick if hasattr(details[0], "minTick") else 0
    except:
        oi = 0

    if vol < min_vol:
        log_debug(f"[FILTRO] {ticker} {tipo} rechazado por bajo volumen: {vol}")
        return False
    if oi < min_oi:
        log_debug(f"[FILTRO] {ticker} {tipo} rechazado por bajo Open Interest: {oi}")
        return False

    return True


if not opcion_valida(ticker, señal, strike, expiry):
        # Validar contrato y datos de mercado
        contrato = Option(ticker, expiry, strike, 'C' if señal == 'CALL' else 'P', 'SMART', 'USD')
        ib.qualifyContracts(contrato)
        market_data = ib.reqMktData(contrato, "", False, False)
        ib.sleep(2)

        score = score_senal(ticker, señal, datos["close"], rango_inicial.get(ticker), contrato, market_data)

        if score < 70:
            log_debug(f"[DESCARTADA] {ticker} {señal} por score insuficiente: {score}")
            continue

    log_debug(f"[DESCARTADA] {ticker} {señal} no cumple filtros de liquidez de opciones.")
    continue

def score_senal(ticker, tipo, precio_actual, datos_rango, contrato_opcion, market_data, trend_5m=None):
    score = 0

    # Volumen actual vs inicial
    if datos_rango and market_data.volume > datos_rango["volumen"] * 1.5:
        score += 20
        log_debug(f"[SCORE] {ticker} +20 por volumen alto.")

    # Cierre de vela fuerte (último close > 75% del rango high-low)
    try:
        rango_vela = datos_rango["high"] - datos_rango["low"]
        if rango_vela > 0 and (precio_actual - datos_rango["low"]) / rango_vela >= 0.75:
            score += 20
            log_debug(f"[SCORE] {ticker} +20 por vela sólida.")
    except:
        pass

    # Tendencia positiva en 5m
    if trend_5m == "alcista" and tipo == "CALL":
        score += 20
        log_debug(f"[SCORE] {ticker} +20 por tendencia alcista.")
    elif trend_5m == "bajista" and tipo == "PUT":
        score += 20
        log_debug(f"[SCORE] {ticker} +20 por tendencia bajista.")

    # Spread del contrato
    if market_data.bid and market_data.ask:
        spread = market_data.ask - market_data.bid
        if spread / market_data.ask <= 0.10:
            score += 20
            log_debug(f"[SCORE] {ticker} +20 por spread bajo.")

    # Open interest del strike
    details = ib.reqContractDetails(contrato_opcion)
    if details and hasattr(details[0], "minTick"):  # Usamos como placeholder
        oi_aprox = details[0].minTick  # Puede cambiarse si se encuentra mejor valor
        if oi_aprox > 2000:
            score += 20
            log_debug(f"[SCORE] {ticker} +20 por OI alto.")

    log_debug(f"[SCORE] {ticker} score total: {score}")
    return score


# Antes de enviar la orden:
# if score_senal(...) >= 70:
#    ejecutar orden
# else:
#    descartar señal

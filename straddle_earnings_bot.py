# STRADDLE EARNINGS BOT (esqueleto inicial)
# Objetivo: comprar CALL + PUT ATM el día anterior a earnings y cerrar post-movimiento

from ib_insync import *
from datetime import datetime, timedelta
import requests
import os
import json

API_KEY_POLYGON = "TU_API_KEY_POLYGON"
IBKR_HOST = '127.0.0.1'
IBKR_PORT = 7497
IBKR_CLIENT_ID = 2

ib = IB()

# Paso 1: conectar a IBKR
def conectar_ibkr():
    if not ib.isConnected():
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID)
        print("[IBKR] Conectado al Paper Trading.")

# Paso 2: obtener próximos earnings (Polygon)
def obtener_earnings_para_fecha(fecha_str):
    url = f"https://api.polygon.io/v2/reference/financials/upcoming?apiKey={API_KEY_POLYGON}&limit=50"
    try:
        r = requests.get(url)
        data = r.json()
        tickers = []
        for x in data.get("results", []):
            if x.get("reportingDate") == fecha_str:
                tickers.append(x["ticker"])
        return tickers
    except Exception as e:
        print("[ERROR] Obteniendo earnings:", e)
        return []

# Paso 3: ejecutar straddle para un ticker específico
def ejecutar_straddle(ticker, capital_maximo=500):
    conectar_ibkr()
    fecha_hoy = datetime.now()
    fecha_exp = (fecha_hoy + timedelta(days=2)).strftime("%Y%m%d")

    stock = Stock(ticker, 'SMART', 'USD')
    ib.qualifyContracts(stock)

    market_data = ib.reqMktData(stock, "", False, False)
    ib.sleep(2)
    precio = market_data.last if market_data.last else market_data.close
    strike = round(precio)

    call = Option(ticker, fecha_exp, strike, 'C', 'SMART', 'USD')
    put = Option(ticker, fecha_exp, strike, 'P', 'SMART', 'USD')
    ib.qualifyContracts(call, put)

    mkt_call = ib.reqMktData(call, "", False, False)
    mkt_put = ib.reqMktData(put, "", False, False)
    ib.sleep(2)

    p_call = mkt_call.ask if mkt_call.ask else mkt_call.close
    p_put = mkt_put.ask if mkt_put.ask else mkt_put.close

    total_cost = p_call + p_put
    qty = int(capital_maximo / total_cost) if total_cost else 0

    if qty < 1:
        print(f"[SKIP] {ticker} muy caro. Costo: {total_cost:.2f}")
        return

    print(f"[EJECUTA] {ticker} STRADDLE x{qty} @ {strike} | CALL: {p_call:.2f}, PUT: {p_put:.2f}")

    ib.placeOrder(call, MarketOrder('BUY', qty))
    ib.placeOrder(put, MarketOrder('BUY', qty))

# Main
if __name__ == "__main__":
    
hoy = datetime.now().strftime('%Y-%m-%d')
earnings_tickers = obtener_earnings_para_fecha(hoy)
tickers_validos = [t for t in earnings_tickers if t in ['TSLA', 'NFLX', 'NVDA', 'AMD', 'META', 'AMZN', 'BABA', 'SHOP', 'ROKU', 'COIN']]
print(f"[EARNINGS FILTRADOS] Candidatos con alta volatilidad: {tickers_validos}")
for t in tickers_validos:
    ejecutar_straddle(t)


from datetime import date

ORDENES_STRADDLE = "ordenes_straddle.json"

def registrar_straddle(ticker, strike, expiry, qty, p_call, p_put):
    os.makedirs("ordenes", exist_ok=True)
    orden = {
        "fecha": date.today().strftime('%Y-%m-%d'),
        "ticker": ticker,
        "strike": strike,
        "expiry": expiry,
        "qty": qty,
        "p_call": p_call,
        "p_put": p_put
    }
    archivo = f"ordenes/{ticker}_straddle.json"
    with open(archivo, "w") as f:
        json.dump(orden, f, indent=2)
    print(f"[LOG] Straddle registrado: {archivo}")

def cerrar_straddle(ticker):
    archivo = f"ordenes/{ticker}_straddle.json"
    if not os.path.exists(archivo):
        print(f"[SKIP] No hay orden previa para {ticker}")
        return

    with open(archivo, "r") as f:
        orden = json.load(f)

    conectar_ibkr()

    call = Option(ticker, orden["expiry"], orden["strike"], 'C', 'SMART', 'USD')
    put = Option(ticker, orden["expiry"], orden["strike"], 'P', 'SMART', 'USD')
    ib.qualifyContracts(call, put)

    ib.placeOrder(call, MarketOrder('SELL', orden["qty"]))
    ib.placeOrder(put, MarketOrder('SELL', orden["qty"]))
    print(f"[CIERRE] Straddle cerrado para {ticker}")
    notificar_cierre_straddle(ticker)


def cierre_automatico_programado():
    ahora = datetime.utcnow().strftime('%H:%M')
    if ahora != "14:35":
        return
    print("[AUTO-CIERRE] Ejecutando cierre programado post-earnings.")
    for archivo in os.listdir("ordenes"):
        if archivo.endswith("_straddle.json"):
            ticker = archivo.split("_")[0]
            cerrar_straddle(ticker)

cierre_automatico_programado()

def notificar_macos(titulo, mensaje):
    import os
    mensaje = mensaje.replace('"', '\"')
    os.system(f'''osascript -e 'display notification "{mensaje}" with title "{titulo}"''' + ")")

def notificar_cierre_straddle(ticker):
    notificar_macos("Cierre Automático", f"Straddle cerrado para {ticker} post-earnings")


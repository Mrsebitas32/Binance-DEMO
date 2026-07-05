from flask import Flask, request, jsonify
from binance.um_futures import UMFutures
from binance.error import ClientError
import config
import logging
import requests
import hmac
import hashlib
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

client = UMFutures(
    key      = config.API_KEY,
    secret   = config.API_SECRET,
    base_url = config.BASE_URL
)

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════
def get_precision(symbol):
    info = client.exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            return s["quantityPrecision"], s["pricePrecision"]
    return 3, 2

def get_equity():
    account = client.account()
    for asset in account["assets"]:
        if asset["asset"] == "USDT":
            return float(asset["availableBalance"])
    return 0.0

def get_qty(symbol):
    equity   = get_equity()
    margen   = equity * (config.POS_PCT / 100)
    nocional = margen * config.LEVERAGE
    price    = float(client.ticker_price(symbol=symbol)["price"])
    qty_p, _ = get_precision(symbol)
    qty      = round(nocional / price, qty_p)
    log.info(f"Equity: ${equity:.2f} | Margen: ${margen:.2f} | Nocional: ${nocional:.2f} | Qty: {qty}")
    return qty

def set_leverage(symbol):
    try:
        client.change_leverage(symbol=symbol, leverage=config.LEVERAGE)
        log.info(f"Apalancamiento {config.LEVERAGE}x en {symbol}")
    except ClientError as e:
        log.warning(f"Leverage: {e}")

def set_margin_isolated(symbol):
    try:
        client.change_margin_type(symbol=symbol, marginType="ISOLATED")
        log.info(f"Margen ISOLATED en {symbol}")
    except ClientError as e:
        log.warning(f"Margin type: {e}")

def close_position(symbol):
    try:
        positions = client.get_position_risk(symbol=symbol)
        for pos in positions:
            amt = float(pos["positionAmt"])
            if amt == 0:
                continue
            side     = "SELL" if amt > 0 else "BUY"
            qty_p, _ = get_precision(symbol)
            qty      = round(abs(amt), qty_p)
            client.new_order(symbol=symbol, side=side, type="MARKET",
                             quantity=qty, reduceOnly=True)
            log.info(f"Posición cerrada: {side} {qty} {symbol}")
    except ClientError as e:
        log.error(f"Error cerrando: {e}")

def place_algo_sltp(symbol, side, order_type, stop_price, price_p):
    """Coloca SL o TP usando el endpoint correcto: POST /fapi/v1/algoOrder"""
    timestamp  = int(time.time() * 1000)
    stop_str   = f"{stop_price:.{price_p}f}"

    params = (
        f"symbol={symbol}"
        f"&side={side}"
        f"&type={order_type}"
        f"&algoType=CONDITIONAL"
        f"&closePosition=true"
        f"&triggerPrice={stop_str}"
        f"&workingType=MARK_PRICE"
        f"&timestamp={timestamp}"
    )
    signature = hmac.new(
        config.API_SECRET.encode(),
        params.encode(),
        hashlib.sha256
    ).hexdigest()

    url     = f"{config.BASE_URL}/fapi/v1/algoOrder"
    headers = {"X-MBX-APIKEY": config.API_KEY}
    resp    = requests.post(f"{url}?{params}&signature={signature}", headers=headers)
    data    = resp.json()
    log.info(f"AlgoOrder {order_type} @ {stop_str}: {data}")
    return data

# ══════════════════════════════════════════════════════
# WEBHOOK
# ══════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON inválido"}), 400

    log.info(f"Señal recibida: {data}")

    action = data.get("action", "").lower()
    symbol = data.get("symbol", config.DEFAULT_SYMBOL).upper().replace(".P", "").replace("-PERP", "")

    if action not in ("long", "short", "close"):
        return jsonify({"error": f"Acción desconocida: {action}"}), 400

    if action == "close":
        close_position(symbol)
        return jsonify({"status": "cerrado", "symbol": symbol})

    # ── Entrada ──
    close_position(symbol)
    set_margin_isolated(symbol)
    set_leverage(symbol)

    qty = get_qty(symbol)
    if qty <= 0:
        return jsonify({"error": "Cantidad es 0"}), 400

    side = "BUY" if action == "long" else "SELL"

    try:
        order = client.new_order(symbol=symbol, side=side, type="MARKET", quantity=qty)
        log.info(f"Orden: {side} {qty} {symbol} | ID: {order['orderId']}")

        entry    = float(client.ticker_price(symbol=symbol)["price"])
        _, price_p = get_precision(symbol)

        sl_pct = config.SL_PCT / 100
        tp_pct = config.TP_PCT / 100

        if action == "long":
            sl_price = round(entry * (1 - sl_pct), price_p)
            tp_price = round(entry * (1 + tp_pct), price_p)
            exit_side = "SELL"
        else:
            sl_price = round(entry * (1 + sl_pct), price_p)
            tp_price = round(entry * (1 - tp_pct), price_p)
            exit_side = "BUY"

        place_algo_sltp(symbol, exit_side, "STOP_MARKET",        sl_price, price_p)
        place_algo_sltp(symbol, exit_side, "TAKE_PROFIT_MARKET", tp_price, price_p)

        return jsonify({
            "status": "ok", "action": action, "symbol": symbol,
            "qty": qty, "entry": entry, "sl": sl_price, "tp": tp_price,
            "order_id": order["orderId"]
        })

    except ClientError as e:
        log.error(f"Error Binance: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "bot activo ✅"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

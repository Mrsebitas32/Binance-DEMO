from flask import Flask, request, jsonify
from binance.um_futures import UMFutures
from binance.error import ClientError
import config
import logging
import requests
import hmac
import hashlib
import time

# ══════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

client = UMFutures(
    key     = config.API_KEY,
    secret  = config.API_SECRET,
    base_url = config.BASE_URL
)

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════
def get_precision(symbol: str) -> tuple:
    info = client.exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            return s["quantityPrecision"], s["pricePrecision"]
    return 3, 2


def get_equity() -> float:
    account = client.account()
    for asset in account["assets"]:
        if asset["asset"] == "USDT":
            return float(asset["availableBalance"])
    return 0.0


def get_qty(symbol: str) -> float:
    equity   = get_equity()
    margen   = equity * (config.POS_PCT / 100)
    nocional = margen * config.LEVERAGE
    ticker   = client.ticker_price(symbol=symbol)
    price    = float(ticker["price"])
    qty_p, _ = get_precision(symbol)
    qty      = round(nocional / price, qty_p)
    log.info(f"Equity: ${equity:.2f} | Margen: ${margen:.2f} | Nocional: ${nocional:.2f} | Qty: {qty}")
    return qty


def set_leverage(symbol: str, leverage: int):
    try:
        client.change_leverage(symbol=symbol, leverage=leverage)
        log.info(f"Apalancamiento {leverage}x en {symbol}")
    except ClientError as e:
        log.warning(f"Apalancamiento: {e}")


def set_margin_type(symbol: str):
    try:
        client.change_margin_type(symbol=symbol, marginType="ISOLATED")
        log.info(f"Margen ISOLATED en {symbol}")
    except ClientError as e:
        log.warning(f"Margen type: {e}")  # puede fallar si ya está en ISOLATED


def close_position(symbol: str):
    try:
        positions = client.get_position_risk(symbol=symbol)
        for pos in positions:
            amt = float(pos["positionAmt"])
            if amt == 0:
                continue
            side     = "SELL" if amt > 0 else "BUY"
            qty_p, _ = get_precision(symbol)
            qty      = round(abs(amt), qty_p)
            client.new_order(
                symbol     = symbol,
                side       = side,
                type       = "MARKET",
                quantity   = qty,
                reduceOnly = True
            )
            log.info(f"Posición cerrada: {side} {qty} {symbol}")
    except ClientError as e:
        log.error(f"Error cerrando posición: {e}")


def place_algo_order(symbol: str, side: str, order_type: str,
                     stop_price: float, qty: float, price_p: int):
    """Coloca SL o TP usando el endpoint de Algo Orders (requerido por Binance Demo)."""
    timestamp = int(time.time() * 1000)
    stop_str  = f"{stop_price:.{price_p}f}"

    params = (
        f"symbol={symbol}"
        f"&side={side}"
        f"&algoType=CONDITIONAL"
        f"&orderType={order_type}"
        f"&quantity={qty}"
        f"&triggerPrice={stop_str}"
        f"&closePosition=true"
        f"&workingType=MARK_PRICE"
        f"&timestamp={timestamp}"
    )
    signature = hmac.new(
        config.API_SECRET.encode(),
        params.encode(),
        hashlib.sha256
    ).hexdigest()

    url = f"{config.BASE_URL}/sapi/v1/algo/futures/newOrderVp"
    headers = {"X-MBX-APIKEY": config.API_KEY}
    resp = requests.post(url, params=params + f"&signature={signature}", headers=headers)
    data = resp.json()
    log.info(f"Algo order {order_type} @ {stop_str}: {data}")
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
    symbol = data.get("symbol", config.DEFAULT_SYMBOL).upper()

    if action not in ("long", "short", "close"):
        return jsonify({"error": f"Acción desconocida: {action}"}), 400

    # ── Cierre ──
    if action == "close":
        close_position(symbol)
        return jsonify({"status": "cerrado", "symbol": symbol})

    # ── Entrada ──
    close_position(symbol)
    set_margin_type(symbol)
    set_leverage(symbol, config.LEVERAGE)

    qty = get_qty(symbol)
    if qty <= 0:
        return jsonify({"error": "Cantidad calculada es 0"}), 400

    side = "BUY" if action == "long" else "SELL"

    try:
        order = client.new_order(
            symbol   = symbol,
            side     = side,
            type     = "MARKET",
            quantity = qty
        )
        log.info(f"Orden ejecutada: {side} {qty} {symbol} | ID: {order['orderId']}")

        ticker   = client.ticker_price(symbol=symbol)
        entry    = float(ticker["price"])
        _, price_p = get_precision(symbol)

        sl_pct = config.SL_PCT / 100
        tp_pct = config.TP_PCT / 100

        if action == "long":
            sl_price = round(entry * (1 - sl_pct), price_p)
            tp_price = round(entry * (1 + tp_pct), price_p)
            sl_side  = "SELL"
        else:
            sl_price = round(entry * (1 + sl_pct), price_p)
            tp_price = round(entry * (1 - tp_pct), price_p)
            sl_side  = "BUY"

        # SL y TP via Algo Orders
        place_algo_order(symbol, sl_side, "STOP_MARKET",       sl_price, qty, price_p)
        place_algo_order(symbol, sl_side, "TAKE_PROFIT_MARKET", tp_price, qty, price_p)

        return jsonify({
            "status"  : "ok",
            "action"  : action,
            "symbol"  : symbol,
            "qty"     : qty,
            "entry"   : entry,
            "sl"      : sl_price,
            "tp"      : tp_price,
            "order_id": order["orderId"]
        })

    except ClientError as e:
        log.error(f"Error Binance: {e}")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "bot activo ✅"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

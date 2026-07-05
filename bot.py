from flask import Flask, request, jsonify
from binance.um_futures import UMFutures
from binance.error import ClientError
import config
import logging

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
    key    = config.API_KEY,
    secret = config.API_SECRET,
    base_url = config.BASE_URL  # Testnet URL
)

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════
def get_precision(symbol: str) -> tuple[int, int]:
    """Retorna (qty_precision, price_precision) para el símbolo."""
    info = client.exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            qty_p   = s["quantityPrecision"]
            price_p = s["pricePrecision"]
            return qty_p, price_p
    return 3, 2


def get_qty(symbol: str, usdt_amount: float) -> float:
    """Calcula cantidad de monedas dado un monto en USDT."""
    ticker    = client.ticker_price(symbol=symbol)
    price     = float(ticker["price"])
    qty_p, _  = get_precision(symbol)
    qty       = round(usdt_amount / price, qty_p)
    return qty


def set_leverage(symbol: str, leverage: int):
    try:
        client.change_leverage(symbol=symbol, leverage=leverage)
        log.info(f"Apalancamiento {leverage}x configurado en {symbol}")
    except ClientError as e:
        log.warning(f"No se pudo cambiar apalancamiento: {e}")


def close_position(symbol: str):
    """Cierra cualquier posición abierta en el símbolo."""
    try:
        positions = client.get_position_risk(symbol=symbol)
        for pos in positions:
            amt = float(pos["positionAmt"])
            if amt == 0:
                continue
            side = "SELL" if amt > 0 else "BUY"
            qty_p, _ = get_precision(symbol)
            qty = round(abs(amt), qty_p)
            client.new_order(
                symbol   = symbol,
                side     = side,
                type     = "MARKET",
                quantity = qty,
                reduceOnly = True
            )
            log.info(f"Posición cerrada: {side} {qty} {symbol}")
    except ClientError as e:
        log.error(f"Error cerrando posición: {e}")


# ══════════════════════════════════════════════════════
# WEBHOOK
# ══════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON inválido"}), 400

    log.info(f"Señal recibida: {data}")

    # Campos esperados del mensaje de TradingView:
    # { "action": "long" | "short" | "close", "symbol": "BTCUSDT" }
    action = data.get("action", "").lower()
    symbol = data.get("symbol", config.DEFAULT_SYMBOL).upper()

    if action not in ("long", "short", "close"):
        return jsonify({"error": f"Acción desconocida: {action}"}), 400

    # ── Cierre ──────────────────────────────────────
    if action == "close":
        close_position(symbol)
        return jsonify({"status": "cerrado", "symbol": symbol})

    # ── Entrada ─────────────────────────────────────
    # 1. Cerrar cualquier posición contraria primero
    close_position(symbol)

    # 2. Configurar apalancamiento
    set_leverage(symbol, config.LEVERAGE)

    # 3. Calcular cantidad
    qty = get_qty(symbol, config.USDT_PER_TRADE)
    if qty <= 0:
        return jsonify({"error": "Cantidad calculada es 0"}), 400

    # 4. Definir lado
    side = "BUY" if action == "long" else "SELL"

    # 5. Enviar orden de mercado
    try:
        order = client.new_order(
            symbol   = symbol,
            side     = side,
            type     = "MARKET",
            quantity = qty
        )
        log.info(f"Orden ejecutada: {side} {qty} {symbol} | ID: {order['orderId']}")

        # 6. Calcular y colocar SL y TP
        ticker    = client.ticker_price(symbol=symbol)
        entry     = float(ticker["price"])
        _, price_p = get_precision(symbol)

        sl_pct  = config.SL_PCT  / 100
        tp_pct  = config.TP_PCT  / 100

        if action == "long":
            sl_price = round(entry * (1 - sl_pct), price_p)
            tp_price = round(entry * (1 + tp_pct), price_p)
            sl_side  = "SELL"
        else:
            sl_price = round(entry * (1 + sl_pct), price_p)
            tp_price = round(entry * (1 - tp_pct), price_p)
            sl_side  = "BUY"

        # Stop Loss
        client.new_order(
            symbol        = symbol,
            side          = sl_side,
            type          = "STOP_MARKET",
            stopPrice     = sl_price,
            closePosition = True
        )
        log.info(f"SL colocado en {sl_price}")

        # Take Profit
        client.new_order(
            symbol        = symbol,
            side          = sl_side,
            type          = "TAKE_PROFIT_MARKET",
            stopPrice     = tp_price,
            closePosition = True
        )
        log.info(f"TP colocado en {tp_price}")

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
# HEALTH CHECK (Railway lo necesita)
# ══════════════════════════════════════════════════════
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "bot activo ✅"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

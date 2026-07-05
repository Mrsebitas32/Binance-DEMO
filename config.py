# ══════════════════════════════════════════════════════
# CONFIG — FBB MTF Bot
# ══════════════════════════════════════════════════════

# Binance Testnet Futures
# Obtén tus keys en: https://testnet.binancefuture.com
API_KEY    = "TU_API_KEY_TESTNET"
API_SECRET = "TU_API_SECRET_TESTNET"
BASE_URL   = "https://testnet.binancefuture.com"  # Cambiar a https://fapi.binance.com para real

# Par por defecto (se puede sobreescribir desde el webhook)
DEFAULT_SYMBOL = "BTCUSDT"

# Apalancamiento
LEVERAGE = 10  # igual que en TradingView

# Tamaño de posición en USDT (nocional)
# Ejemplo: con $100 de margen y 10x → $1000 nocional
USDT_PER_TRADE = 1000

# Gestión de riesgo — TP único 100%
# Estos deben coincidir con lo que tiene el script de TradingView
SL_PCT = 0.5   # Stop Loss en %   (riesgo_pct del script)
TP_PCT = 1.0   # Take Profit en % (riesgo_pct × 2 = tp1_pct del script)

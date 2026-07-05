# ══════════════════════════════════════════════════════
# CONFIG — FBB MTF Bot
# ══════════════════════════════════════════════════════

# Binance Testnet Futures
# Obtén tus keys en: https://testnet.binancefuture.com
API_KEY    = "JcDMMDPpa6vVOa93vfsca4MjKUBhJwHRIhdQy7xp5KCgEmyXIYzZ1O9uhqBqVpx3"
API_SECRET = "hn3GGtm0n33GDDWHa4IcXvbNU6Kmp2WAflNyF9FOFLDNQfcncNZcOCTgfsEwVgRU"

BASE_URL   = "https://demo-fapi.binance.com"  # Cambiar a https://fapi.binance.com para real

# Par por defecto (se puede sobreescribir desde el webhook)
DEFAULT_SYMBOL = "BTCUSDT"

# Apalancamiento
LEVERAGE = 20  # igual que en TradingView

# Tamaño de posición — igual que TradingView (% del equity, dinámico)
POS_PCT = 10   # % del equity por trade (igual que en TradingView)

# Gestión de riesgo — TP único 100%
# Estos deben coincidir con lo que tiene el script de TradingView
SL_PCT = 1.41   # Stop Loss en %   (riesgo_pct del script)
TP_PCT = 2.82   # Take Profit en % (riesgo_pct × 2 = tp1_pct del script)

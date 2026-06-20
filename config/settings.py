"""
============================================================================
ORB Trading System — Configuración central
============================================================================
Todas las constantes y parámetros del sistema en un solo lugar.
Modifica este archivo para ajustar API keys, rutas, o parámetros de trading.
============================================================================
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────
# RUTAS
# ──────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(os.path.abspath(__file__)).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

DUCKDB_PATH = DATA_DIR / "market_data.duckdb"
SQLITE_PATH = DATA_DIR / "orb_live.db"

# ──────────────────────────────────────────────────────────────────────────
# API — Massive.com (ex Polygon.io)
# ──────────────────────────────────────────────────────────────────────────
# Pon tu API key aquí o como variable de entorno MASSIVE_API_KEY
MASSIVE_API_KEY = "B4NuvKm6wV729CbWR23iUNX8X6YizuSW"

# Limites de la API (plan Starter $29/mes)
API_RATE_LIMIT_PER_MIN = 0       # Unlimited en plan Starter
API_MAX_RESULTS_PER_CALL = 50000 # Maximo de barras por peticion
API_PAUSE_SECONDS = 0.5          # Pausa minima entre llamadas (Unlimited = sin limite estricto)

# ----------------------------------------------------------------------
# DATOS HISTORICOS
# ----------------------------------------------------------------------
HISTORICAL_YEARS = 5             # Anios de datos a descargar
DOWNLOAD_START_DATE = "2021-04-01"  # Plan Starter = 5 anios desde hoy (mar 2026)
DOWNLOAD_END_DATE = "2026-03-21"

# Tamaño del chunk para descarga (días por petición)
# 1 minuto × 390 barras/día × 30 días = ~11.700 barras (bien dentro del límite)
DOWNLOAD_CHUNK_DAYS = 30

# ──────────────────────────────────────────────────────────────────────────
# UNIVERSO DE ACCIONES
# ──────────────────────────────────────────────────────────────────────────
SP500_UNIVERSE_SIZE = 503        # Tickers totales del S&P 500
FILTERED_UNIVERSE_SIZE = 50      # Top 50 por volumen + volatilidad

# Criterios de filtrado para el universo reducido
# NOTA: Los volumenes de Massive API (agregados desde 1min) son menores que
# los volumenes "oficiales" de mercado. Estos umbrales estan calibrados
# para los datos reales descargados.
MIN_AVG_DAILY_VOLUME = 10_000       # Volumen minimo diario promedio (acciones)
MIN_AVG_DAILY_DOLLAR_VOL = 1_000_000   # Volumen minimo en dolares
MIN_PRICE = 5.0                      # Precio minimo (evitar penny stocks)
MAX_PRICE = 2000.0                   # Precio maximo

# ──────────────────────────────────────────────────────────────────────────
# ESTRATEGIA ORB (Opening Range Breakout)
# ──────────────────────────────────────────────────────────────────────────
ORB_TIMEFRAME_MINUTES = 30       # Rango de apertura: primeros 30 minutos
MARKET_OPEN_TIME = "09:30"       # Hora apertura NYSE (ET)
MARKET_CLOSE_TIME = "16:00"      # Hora cierre NYSE (ET)

# ──────────────────────────────────────────────────────────────────────────
# GESTIÓN DE RIESGO
# ──────────────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 10_000         # Capital inicial en EUR
RISK_PER_TRADE_PCT = 0.01       # Riesgo por operación: 1% del capital
MAX_RISK_PER_TRADE_PCT = 0.02   # Máximo riesgo por operación: 2%
MAX_DAILY_LOSS_PCT = 0.03       # Máxima pérdida diaria: 3%
MAX_POSITIONS = 3                # Máximo de posiciones simultáneas

# ──────────────────────────────────────────────────────────────────────────
# COSTES
# ──────────────────────────────────────────────────────────────────────────
IBKR_COMMISSION_PER_SHARE = 0.005   # IBKR comisión por acción (USD)
IBKR_MIN_COMMISSION = 1.00          # Comisión mínima por orden
SLIPPAGE_PCT = 0.0005               # Slippage estimado: 0.05%

# ──────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

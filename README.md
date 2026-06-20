# ORB Trading System — Fase 1: Datos

## Sistema de Trading Opening Range Breakout (ORB) sobre S&P 500

### Arquitectura

```
orb_trading/
├── config/
│   ├── settings.py          # Configuración central (API key, rutas, parámetros)
│   └── sp500_tickers.py     # Lista completa de tickers S&P 500
├── scripts/
│   ├── 01_init_database.py  # Crea las tablas en DuckDB
│   ├── 02_download_data.py  # Descarga datos desde Massive.com API
│   ├── 03_select_universe.py # Selecciona top 50 por volumen + volatilidad
│   └── 04_verify_data.py    # Verificación y calidad de datos
├── data/
│   └── market_data.duckdb   # Base de datos (se genera automáticamente)
└── logs/
    └── download.log         # Log de descargas
```

### Requisitos

```bash
pip install duckdb pandas massive --break-system-packages
```

### Configuración

1. Obtén tu API key de [massive.com](https://massive.com) (Plan Starter $29/mes)
2. Configura la key:
   ```bash
   export MASSIVE_API_KEY="tu_api_key_aquí"
   ```
   O edita `config/settings.py` directamente.

### Ejecución (en orden)

```bash
cd orb_trading/

# Paso 1: Crear base de datos
python scripts/01_init_database.py

# Paso 2: Descargar datos (⚠️ puede tardar horas/días para 500 tickers a 1min)
python scripts/02_download_data.py                     # Todo el S&P 500
python scripts/02_download_data.py --ticker AAPL        # Solo un ticker (test)
python scripts/02_download_data.py --tickers AAPL MSFT  # Varios tickers
python scripts/02_download_data.py --daily-only         # Solo datos diarios (rápido)
python scripts/02_download_data.py --resume             # Reanudar si se interrumpió

# Paso 3: Verificar datos descargados
python scripts/04_verify_data.py
python scripts/04_verify_data.py --ticker AAPL --detailed

# Paso 4: Seleccionar universo de trading (top 50)
python scripts/03_select_universe.py
python scripts/03_select_universe.py --top 30           # Top 30 en vez de 50
```

### Estimación de tiempos de descarga

| Escenario | Tickers | Timespan | Chunks/ticker | Total calls | Tiempo estimado |
|-----------|---------|----------|---------------|-------------|-----------------|
| Test      | 1       | 1min     | ~61           | 61          | ~13 min         |
| Reducido  | 50      | 1min     | ~61           | 3.050       | ~11 horas       |
| Completo  | 500     | 1min     | ~61           | 30.500      | ~4.5 días       |
| Diario    | 500     | day      | ~61           | 30.500      | ~4.5 días       |

> **Recomendación**: Descarga primero datos diarios (`--daily-only`) para seleccionar
> el universo, y luego descarga datos a 1 minuto solo para las top 50 seleccionadas.

### Estrategia de descarga eficiente

```bash
# 1. Crear base de datos
python scripts/01_init_database.py

# 2. Descargar datos diarios de todo el S&P 500 (más rápido)
python scripts/02_download_data.py --daily-only

# 3. Seleccionar top 50 con los datos diarios
python scripts/03_select_universe.py

# 4. Descargar datos a 1 minuto SOLO de las top 50
#    (ver los tickers seleccionados y pasarlos como argumento)
python scripts/02_download_data.py --tickers AAPL MSFT NVDA TSLA ...
```

### Esquema de la Base de Datos

| Tabla | Descripción | Tamaño estimado |
|-------|-------------|-----------------|
| `prices_1min` | OHLCV 1 minuto (50 tickers × 5 años) | ~50M filas |
| `prices_daily` | OHLCV diario | ~625K filas |
| `universe` | Metadatos y selección top 50 | ~500 filas |
| `download_log` | Control de descargas | ~30K filas |
| `bt_trades_orb` | Trades backtest (fase 2) | Variable |
| `bt_metrics` | Métricas backtest (fase 2) | Variable |

### Próximos pasos (Fase 2)

- Motor de backtest ORB 30 minutos
- Gestión de riesgo (1-2% por operación)
- Análisis de resultados y optimización
- Conexión live a IBKR via ib_insync

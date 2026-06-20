"""
============================================================================
ORB Trading System — Inicialización de Base de Datos DuckDB
============================================================================
Crea las tablas necesarias en market_data.duckdb:
  - prices_1min:   Datos OHLCV a 1 minuto
  - prices_daily:  Datos OHLCV diarios (agregados desde 1min)
  - universe:      Metadatos de cada ticker (sector, volumen, volatilidad)
  - bt_trades_orb: Trades del backtest ORB
  - bt_metrics:    Métricas globales del backtest
============================================================================
"""

import duckdb
import os
import sys
from pathlib import Path

# ── Fix imports: añadir raíz del proyecto al sys.path ──
# Funciona desde cualquier directorio en Windows, Mac y Linux
_THIS_FILE = Path(os.path.abspath(__file__))
_PROJECT_ROOT = str(_THIS_FILE.parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from config.settings import DUCKDB_PATH, DATA_DIR


def create_database():
    """Crea la base de datos DuckDB con todas las tablas necesarias."""
    
    # Asegurar que el directorio existe
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    con = duckdb.connect(str(DUCKDB_PATH))
    
    # ──────────────────────────────────────────────────────────────────────
    # Tabla: prices_1min — Datos OHLCV a 1 minuto
    # ──────────────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices_1min (
            ticker      VARCHAR NOT NULL,
            ts          TIMESTAMP NOT NULL,    -- Timestamp UTC de la barra
            open        DOUBLE NOT NULL,
            high        DOUBLE NOT NULL,
            low         DOUBLE NOT NULL,
            close       DOUBLE NOT NULL,
            volume      BIGINT NOT NULL,
            vwap        DOUBLE,                -- Volume Weighted Avg Price
            num_trades  INTEGER,               -- Nº de transacciones en la barra
            
            PRIMARY KEY (ticker, ts)
        )
    """)
    
    # ──────────────────────────────────────────────────────────────────────
    # Tabla: prices_daily — Datos diarios (se calculan desde 1min)
    # ──────────────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices_daily (
            ticker      VARCHAR NOT NULL,
            date        DATE NOT NULL,
            open        DOUBLE NOT NULL,
            high        DOUBLE NOT NULL,
            low         DOUBLE NOT NULL,
            close       DOUBLE NOT NULL,
            volume      BIGINT NOT NULL,
            vwap        DOUBLE,
            
            PRIMARY KEY (ticker, date)
        )
    """)
    
    # ──────────────────────────────────────────────────────────────────────
    # Tabla: universe — Metadatos de cada ticker
    # ──────────────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS universe (
            ticker              VARCHAR PRIMARY KEY,
            name                VARCHAR,
            sector              VARCHAR,
            market_cap          DOUBLE,
            avg_daily_volume    DOUBLE,          -- Volumen medio diario (acciones)
            avg_dollar_volume   DOUBLE,          -- Volumen medio en USD
            avg_atr_pct         DOUBLE,          -- ATR % medio (volatilidad)
            avg_spread_pct      DOUBLE,          -- Spread medio %
            avg_price           DOUBLE,          -- Precio medio del periodo
            in_top50            BOOLEAN DEFAULT FALSE,  -- ¿Seleccionada para trading?
            last_updated        TIMESTAMP
        )
    """)
    
    # ──────────────────────────────────────────────────────────────────────
    # Tabla: download_log — Control de descargas realizadas
    # ──────────────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS download_log (
            ticker          VARCHAR NOT NULL,
            chunk_start     DATE NOT NULL,
            chunk_end       DATE NOT NULL,
            rows_downloaded INTEGER,
            status          VARCHAR,           -- 'ok', 'error', 'no_data'
            error_msg       VARCHAR,
            downloaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            PRIMARY KEY (ticker, chunk_start)
        )
    """)
    
    # ──────────────────────────────────────────────────────────────────────
    # Tabla: bt_trades_orb — Trades del backtest (se crean en fase 2)
    # ──────────────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS bt_trades_orb (
            trade_id        INTEGER PRIMARY KEY,
            ticker          VARCHAR NOT NULL,
            date            DATE NOT NULL,
            direction       VARCHAR NOT NULL,      -- 'LONG' o 'SHORT'
            entry_time      TIMESTAMP NOT NULL,
            entry_price     DOUBLE NOT NULL,
            exit_time       TIMESTAMP,
            exit_price      DOUBLE,
            shares          INTEGER NOT NULL,
            pnl_gross       DOUBLE,                -- P&L bruto
            pnl_net         DOUBLE,                -- P&L neto (con comisiones)
            commission      DOUBLE,
            slippage        DOUBLE,
            orb_high        DOUBLE,                -- High del rango de apertura
            orb_low         DOUBLE,                -- Low del rango de apertura
            stop_loss       DOUBLE,
            reason_exit     VARCHAR                -- 'target', 'stop', 'eod', 'trailing'
        )
    """)
    
    # ──────────────────────────────────────────────────────────────────────
    # Tabla: bt_metrics — Métricas globales del backtest
    # ──────────────────────────────────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS bt_metrics (
            run_id              INTEGER PRIMARY KEY,
            run_date            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            strategy            VARCHAR DEFAULT 'ORB_30min',
            period_start        DATE,
            period_end          DATE,
            total_trades        INTEGER,
            winning_trades      INTEGER,
            losing_trades       INTEGER,
            win_rate            DOUBLE,
            avg_win             DOUBLE,
            avg_loss            DOUBLE,
            profit_factor       DOUBLE,
            total_pnl_net       DOUBLE,
            max_drawdown_pct    DOUBLE,
            sharpe_ratio        DOUBLE,
            sortino_ratio       DOUBLE,
            calmar_ratio        DOUBLE,
            avg_trade_duration  DOUBLE,            -- Minutos promedio
            params_json         VARCHAR             -- Parámetros usados (JSON)
        )
    """)
    
    con.close()
    print(f"✅ Base de datos creada: {DUCKDB_PATH}")
    print("   Tablas: prices_1min, prices_daily, universe, download_log,")
    print("           bt_trades_orb, bt_metrics")


if __name__ == "__main__":
    create_database()

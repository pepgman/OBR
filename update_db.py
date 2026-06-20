"""
============================================================================
ACTUALIZAR BD — Rellena el hueco desde la última fecha hasta hoy
============================================================================
Detecta la última fecha en prices_1min y descarga desde ahí hasta hoy.
Usa el mismo pipeline que 02_download_data.py.

USO:
    Ejecutar desde el directorio raíz del proyecto ORB:
    python update_db.py

    O especificar la ruta a la BD si ejecutas desde otro directorio:
    python update_db.py --db "C:\OBR\data\market_data.duckdb"
============================================================================
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path

import duckdb
import pandas as pd


# ──────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN (ajustar si es necesario)
# ──────────────────────────────────────────────────────────────────────────

# Intentar importar desde config/settings.py si existe
try:
    _THIS_FILE = Path(os.path.abspath(__file__))
    _PROJECT_ROOT = str(_THIS_FILE.parent)
    sys.path.insert(0, _PROJECT_ROOT)
    from config.settings import (
        DUCKDB_PATH, MASSIVE_API_KEY, API_PAUSE_SECONDS,
        API_MAX_RESULTS_PER_CALL,
    )
    from config.sp500_tickers import get_active_sp500_tickers
    DB_PATH = str(DUCKDB_PATH)
    USE_CONFIG = True
    print(f"[OK] Configuración cargada desde config/settings.py")
    print(f"     BD: {DB_PATH}")
except ImportError:
    # Fallback: configuración manual
    DB_PATH = r"C:\OBR\data\market_data.duckdb"
    MASSIVE_API_KEY = "B4NuvKm6wV729CbWR23iUNX8X6YizuSW"
    API_PAUSE_SECONDS = 0.5
    API_MAX_RESULTS_PER_CALL = 50000
    USE_CONFIG = False
    print(f"[!] config/settings.py no encontrado, usando valores por defecto")
    print(f"    BD: {DB_PATH}")


# ──────────────────────────────────────────────────────────────────────────
# FUNCIONES
# ──────────────────────────────────────────────────────────────────────────

def get_last_date(con):
    """Obtiene la última fecha con datos en prices_1min."""
    result = con.execute("""
        SELECT MAX(CAST(ts AS DATE)) FROM prices_1min
    """).fetchone()
    return result[0] if result[0] else None


def get_tickers_in_db(con):
    """Obtiene la lista de tickers que ya están en la BD."""
    result = con.execute("""
        SELECT DISTINCT ticker FROM prices_1min ORDER BY ticker
    """).fetchall()
    return [r[0] for r in result]


def download_chunk(client, ticker, start_date, end_date,
                   timespan="minute", multiplier=1):
    """Descarga un chunk de datos desde Massive."""
    try:
        aggs = []
        for a in client.list_aggs(
            ticker=ticker,
            multiplier=multiplier,
            timespan=timespan,
            from_=start_date,
            to=end_date,
            limit=API_MAX_RESULTS_PER_CALL,
        ):
            aggs.append({
                "ticker": ticker,
                "ts": pd.Timestamp(a.timestamp, unit="ms", tz="UTC"),
                "open": a.open,
                "high": a.high,
                "low": a.low,
                "close": a.close,
                "volume": a.volume or 0,
                "vwap": getattr(a, "vwap", None),
                "num_trades": getattr(a, "transactions", None),
            })
        if not aggs:
            return None
        df = pd.DataFrame(aggs)
        df["ts"] = df["ts"].dt.tz_localize(None)
        return df
    except Exception as e:
        print(f"  [ERROR] {ticker}: {e}")
        return None


def insert_1min_data(con, df):
    """Inserta datos de 1 minuto en la BD."""
    if df is None or df.empty:
        return 0
    con.register("tmp_insert", df)
    con.execute("""
        INSERT OR IGNORE INTO prices_1min
        (ticker, ts, open, high, low, close, volume, vwap, num_trades)
        SELECT ticker, ts, open, high, low, close, volume, vwap, num_trades
        FROM tmp_insert
    """)
    con.unregister("tmp_insert")
    return len(df)


def generate_daily_from_1min(con, ticker, start_date):
    """Regenera datos diarios para un ticker desde una fecha."""
    con.execute(f"""
        INSERT OR REPLACE INTO prices_daily
        (ticker, date, open, high, low, close, volume, vwap)
        SELECT
            ticker,
            CAST(ts AT TIME ZONE 'America/New_York' AS DATE) as date,
            FIRST(open ORDER BY ts) as open,
            MAX(high) as high,
            MIN(low) as low,
            LAST(close ORDER BY ts) as close,
            SUM(volume) as volume,
            CASE WHEN SUM(volume) > 0
                THEN SUM(vwap * volume) / SUM(volume) ELSE NULL
            END as vwap
        FROM prices_1min
        WHERE ticker = ?
            AND CAST(ts AS DATE) >= ?
            AND EXTRACT(HOUR FROM ts AT TIME ZONE 'America/New_York') * 60
                + EXTRACT(MINUTE FROM ts AT TIME ZONE 'America/New_York') >= 570
            AND EXTRACT(HOUR FROM ts AT TIME ZONE 'America/New_York') * 60
                + EXTRACT(MINUTE FROM ts AT TIME ZONE 'America/New_York') < 960
        GROUP BY ticker, CAST(ts AT TIME ZONE 'America/New_York' AS DATE)
        HAVING SUM(volume) > 0
    """, [ticker, start_date])


# ──────────────────────────────────────────────────────────────────────────
# PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Actualizar BD con datos recientes")
    parser.add_argument("--db", type=str, default=None,
                        help="Ruta a la BD DuckDB")
    parser.add_argument("--end-date", type=str, default=None,
                        help="Fecha final (default: hoy)")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    end_date = args.end_date or date.today().isoformat()

    # Verificar que la BD existe
    if not Path(db_path).exists():
        print(f"[ERROR] No se encuentra la BD: {db_path}")
        sys.exit(1)

    # Importar cliente de Massive
    try:
        from massive import RESTClient
    except ImportError:
        print("[ERROR] Instala massive: pip install massive")
        sys.exit(1)

    client = RESTClient(api_key=MASSIVE_API_KEY)
    con = duckdb.connect(str(db_path))

    # Detectar última fecha y tickers
    last_date = get_last_date(con)
    tickers = get_tickers_in_db(con)

    if last_date is None:
        print("[ERROR] La BD está vacía. Usa 02_download_data.py para la descarga inicial.")
        con.close()
        sys.exit(1)

    # Empezar desde el día siguiente a la última fecha
    start_date = (last_date + timedelta(days=1)).isoformat()

    print()
    print("=" * 60)
    print("  ACTUALIZACIÓN DE BASE DE DATOS")
    print("=" * 60)
    print(f"  BD:              {db_path}")
    print(f"  Última fecha:    {last_date}")
    print(f"  Descargar desde: {start_date}")
    print(f"  Hasta:           {end_date}")
    print(f"  Tickers:         {len(tickers)}")
    print("=" * 60)

    if start_date > end_date:
        print("\n  [OK] La BD ya está actualizada. No hay nada que descargar.")
        con.close()
        return

    # Descargar
    total_rows = 0
    errors = 0
    start_time = time.time()

    for i, ticker in enumerate(tickers, 1):
        print(f"\n  [{i:3d}/{len(tickers)}] {ticker}...", end=" ")

        df = download_chunk(client, ticker, start_date, end_date)

        if df is not None and not df.empty:
            rows = insert_1min_data(con, df)
            generate_daily_from_1min(con, ticker, start_date)
            total_rows += rows
            print(f"{rows:,} barras")
        else:
            print("sin datos")

        time.sleep(API_PAUSE_SECONDS)

    elapsed = time.time() - start_time

    # Verificación final
    new_last_date = get_last_date(con)
    count_1min = con.execute("SELECT COUNT(*) FROM prices_1min").fetchone()[0]
    count_daily = con.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]

    print()
    print("=" * 60)
    print("  ACTUALIZACIÓN COMPLETADA")
    print("=" * 60)
    print(f"  Barras descargadas: {total_rows:,}")
    print(f"  Tiempo:             {elapsed:.0f}s")
    print(f"  Nueva última fecha: {new_last_date}")
    print(f"  prices_1min:        {count_1min:,} filas")
    print(f"  prices_daily:       {count_daily:,} filas")
    print("=" * 60)

    con.close()


if __name__ == "__main__":
    main()

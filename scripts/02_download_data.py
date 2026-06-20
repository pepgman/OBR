"""
============================================================================
ORB Trading System -- Descarga de datos desde Massive.com API
============================================================================
Descarga datos OHLCV a 1 minuto para todas las acciones del S&P 500.

USO:
    python scripts/02_download_data.py                    # Descarga todo
    python scripts/02_download_data.py --ticker AAPL      # Solo un ticker
    python scripts/02_download_data.py --resume            # Reanudar descarga
    python scripts/02_download_data.py --daily-only        # Solo datos diarios
============================================================================
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path

import duckdb
import pandas as pd

# Anadir raiz del proyecto al path (Windows/Mac/Linux)
_THIS_FILE = Path(os.path.abspath(__file__))
_PROJECT_ROOT = str(_THIS_FILE.parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from config.settings import (
    DUCKDB_PATH, DATA_DIR, MASSIVE_API_KEY,
    API_PAUSE_SECONDS, API_MAX_RESULTS_PER_CALL,
    DOWNLOAD_START_DATE, DOWNLOAD_END_DATE, DOWNLOAD_CHUNK_DAYS,
    LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, LOGS_DIR,
)
from config.sp500_tickers import get_active_sp500_tickers

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "download.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("downloader")


# ----------------------------------------------------------------------
# Generador de chunks de fechas
# ----------------------------------------------------------------------
def generate_date_chunks(
    start: str, end: str, chunk_days: int = DOWNLOAD_CHUNK_DAYS
) -> list[tuple[str, str]]:
    chunks = []
    current = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        chunks.append((current.isoformat(), chunk_end.isoformat()))
        current = chunk_end + timedelta(days=1)
    return chunks


# ----------------------------------------------------------------------
# Descarga de un chunk
# ----------------------------------------------------------------------
def download_chunk(client, ticker, start_date, end_date, timespan="minute", multiplier=1):
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
        logger.error(f"Error descargando {ticker} ({start_date} -> {end_date}): {e}")
        return None


# ----------------------------------------------------------------------
# Verificar si un chunk ya esta descargado
# ----------------------------------------------------------------------
def is_chunk_downloaded(con, ticker, chunk_start):
    result = con.execute(
        "SELECT COUNT(*) FROM download_log WHERE ticker = ? AND chunk_start = ? AND status = 'ok'",
        [ticker, chunk_start]
    ).fetchone()
    return result[0] > 0


# ----------------------------------------------------------------------
# Registrar descarga en el log
# ----------------------------------------------------------------------
def log_download(con, ticker, chunk_start, chunk_end, rows, status, error_msg=None):
    con.execute("""
        INSERT OR REPLACE INTO download_log 
        (ticker, chunk_start, chunk_end, rows_downloaded, status, error_msg, downloaded_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, [ticker, chunk_start, chunk_end, rows, status, error_msg])


# ----------------------------------------------------------------------
# Insertar datos en DuckDB
# ----------------------------------------------------------------------
def insert_1min_data(con, df):
    if df is None or df.empty:
        return 0
    con.register("tmp_insert", df)
    con.execute("""
        INSERT OR IGNORE INTO prices_1min (ticker, ts, open, high, low, close, volume, vwap, num_trades)
        SELECT ticker, ts, open, high, low, close, volume, vwap, num_trades
        FROM tmp_insert
    """)
    con.unregister("tmp_insert")
    return len(df)


# ----------------------------------------------------------------------
# Generar datos diarios a partir de 1 minuto
# ----------------------------------------------------------------------
def generate_daily_from_1min(con, ticker=None):
    ticker_filter = f"AND ticker = '{ticker}'" if ticker else ""
    con.execute(f"""
        INSERT OR REPLACE INTO prices_daily (ticker, date, open, high, low, close, volume, vwap)
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
        WHERE 1=1 {ticker_filter}
            AND EXTRACT(HOUR FROM ts AT TIME ZONE 'America/New_York') * 60 
                + EXTRACT(MINUTE FROM ts AT TIME ZONE 'America/New_York') >= 570
            AND EXTRACT(HOUR FROM ts AT TIME ZONE 'America/New_York') * 60 
                + EXTRACT(MINUTE FROM ts AT TIME ZONE 'America/New_York') < 960
        GROUP BY ticker, CAST(ts AT TIME ZONE 'America/New_York' AS DATE)
        HAVING SUM(volume) > 0
    """)
    logger.info(f"Datos diarios generados para {ticker}" if ticker else "Datos diarios generados")


# ----------------------------------------------------------------------
# Funcion principal de descarga
# ----------------------------------------------------------------------
def run_download(tickers=None, resume=True, daily_only=False):

    # -- Validar API key --
    if MASSIVE_API_KEY == "TU_API_KEY_AQUI":
        logger.error("[ERROR] Configura tu API key en config/settings.py")
        sys.exit(1)
    
    # -- Importar cliente de Massive --
    try:
        from massive import RESTClient
    except ImportError:
        logger.error("[ERROR] Instala massive: pip install massive")
        sys.exit(1)
    
    client = RESTClient(api_key=MASSIVE_API_KEY)
    con = duckdb.connect(str(DUCKDB_PATH))
    
    if tickers is None:
        tickers = get_active_sp500_tickers()
    
    total_tickers = len(tickers)
    chunks = generate_date_chunks(DOWNLOAD_START_DATE, DOWNLOAD_END_DATE)
    total_chunks = len(chunks)
    
    logger.info("=" * 70)
    logger.info("ORB Trading System -- Descarga de datos")
    logger.info("=" * 70)
    logger.info(f"Tickers:     {total_tickers}")
    logger.info(f"Periodo:     {DOWNLOAD_START_DATE} -> {DOWNLOAD_END_DATE}")
    logger.info(f"Chunks:      {total_chunks} de {DOWNLOAD_CHUNK_DAYS} dias cada uno")
    logger.info(f"Total ops:   {total_tickers * total_chunks} descargas")
    logger.info(f"Timespan:    {'day' if daily_only else 'minute'}")
    logger.info(f"Reanudar:    {'Si' if resume else 'No'}")
    logger.info("=" * 70)
    
    downloaded = 0
    skipped = 0
    errors = 0
    total_rows = 0
    start_time = time.time()
    
    for i, ticker in enumerate(tickers, 1):
        ticker_start = time.time()
        ticker_rows = 0
        
        logger.info(f"")
        logger.info(f"--- [{i}/{total_tickers}] {ticker} ---")
        
        for j, (chunk_start, chunk_end) in enumerate(chunks, 1):
            
            if resume and is_chunk_downloaded(con, ticker, chunk_start):
                skipped += 1
                continue
            
            logger.info(f"  Chunk {j}/{total_chunks}: {chunk_start} -> {chunk_end}...")
            
            timespan = "day" if daily_only else "minute"
            df = download_chunk(client, ticker, chunk_start, chunk_end, timespan=timespan)
            
            if df is not None and not df.empty:
                if daily_only:
                    df_daily = df.rename(columns={"ts": "date"})
                    df_daily["date"] = df_daily["date"].dt.date
                    con.register("tmp_daily", df_daily)
                    con.execute("""
                        INSERT OR IGNORE INTO prices_daily 
                        (ticker, date, open, high, low, close, volume, vwap)
                        SELECT ticker, date, open, high, low, close, volume, vwap
                        FROM tmp_daily
                    """)
                    con.unregister("tmp_daily")
                    rows = len(df_daily)
                else:
                    rows = insert_1min_data(con, df)
                
                ticker_rows += rows
                total_rows += rows
                log_download(con, ticker, chunk_start, chunk_end, rows, "ok")
                logger.info(f"    >> {rows:,} barras guardadas")
            else:
                log_download(con, ticker, chunk_start, chunk_end, 0, "no_data")
                logger.info(f"    >> Sin datos")
            
            downloaded += 1
            time.sleep(API_PAUSE_SECONDS)
        
        if not daily_only and ticker_rows > 0:
            generate_daily_from_1min(con, ticker)
        
        ticker_elapsed = time.time() - ticker_start
        logger.info(f"  [OK] {ticker}: {ticker_rows:,} barras en {ticker_elapsed:.0f}s")
    
    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=" * 70)
    logger.info("DESCARGA COMPLETADA")
    logger.info("=" * 70)
    logger.info(f"Total barras:    {total_rows:,}")
    logger.info(f"Chunks OK:       {downloaded:,}")
    logger.info(f"Chunks saltados: {skipped:,}")
    logger.info(f"Errores:         {errors:,}")
    logger.info(f"Tiempo total:    {elapsed / 60:.1f} minutos")
    logger.info(f"Base de datos:   {DUCKDB_PATH}")
    logger.info("=" * 70)
    
    count_1min = con.execute("SELECT COUNT(*) FROM prices_1min").fetchone()[0]
    count_daily = con.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
    tickers_in_db = con.execute("SELECT COUNT(DISTINCT ticker) FROM prices_1min").fetchone()[0]
    
    logger.info(f"")
    logger.info(f"Estado de la BD:")
    logger.info(f"   prices_1min:  {count_1min:,} filas ({tickers_in_db} tickers)")
    logger.info(f"   prices_daily: {count_daily:,} filas")
    
    con.close()


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Descarga datos S&P 500 desde Massive.com")
    parser.add_argument("--ticker", "-t", type=str, default=None, help="Un ticker (ej: AAPL)")
    parser.add_argument("--tickers", "-T", type=str, nargs="+", default=None, help="Varios tickers")
    parser.add_argument("--resume", "-r", action="store_true", default=True, help="Reanudar (default)")
    parser.add_argument("--no-resume", action="store_true", help="Re-descargar todo")
    parser.add_argument("--daily-only", "-d", action="store_true", default=False, help="Solo datos diarios")
    
    args = parser.parse_args()
    
    tickers = None
    if args.ticker:
        tickers = [args.ticker.upper()]
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    
    resume = not args.no_resume
    run_download(tickers=tickers, resume=resume, daily_only=args.daily_only)


if __name__ == "__main__":
    main()

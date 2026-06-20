"""
============================================================================
ORB Trading System — Verificación de datos descargados
============================================================================
Ejecutar después de la descarga para verificar:
  - Completitud de los datos (gaps, días faltantes)
  - Calidad de los datos (outliers, volúmenes cero)
  - Cobertura temporal por ticker
  - Estadísticas generales de la base de datos

USO:
    python scripts/04_verify_data.py
    python scripts/04_verify_data.py --ticker AAPL
    python scripts/04_verify_data.py --detailed
============================================================================
"""

import os
import sys
import argparse
import logging
from pathlib import Path

import duckdb
import pandas as pd

# Añadir raíz del proyecto al path (Windows/Mac/Linux)
_THIS_FILE = Path(os.path.abspath(__file__))
_PROJECT_ROOT = str(_THIS_FILE.parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from config.settings import DUCKDB_PATH, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
)
logger = logging.getLogger("verify")


def verify_database(con: duckdb.DuckDBPyConnection, ticker: str = None, detailed: bool = False):
    """Ejecuta todas las verificaciones de datos."""
    
    print("\n" + "=" * 70)
    print("VERIFICACIÓN DE DATOS — market_data.duckdb")
    print("=" * 70)
    
    # ── 1. Estadísticas generales ──
    print("\n📊 ESTADÍSTICAS GENERALES")
    print("-" * 50)
    
    stats = con.execute("""
        SELECT 
            COUNT(*) AS total_rows,
            COUNT(DISTINCT ticker) AS num_tickers,
            MIN(ts) AS first_bar,
            MAX(ts) AS last_bar
        FROM prices_1min
    """).fetchdf()
    
    if stats["total_rows"].iloc[0] == 0:
        print("⚠️  No hay datos en prices_1min.")
        
        # Verificar si hay datos diarios directamente
        daily_count = con.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
        if daily_count > 0:
            print(f"   Pero hay {daily_count:,} filas en prices_daily")
        return
    
    print(f"  Filas totales (1min):    {stats['total_rows'].iloc[0]:,}")
    print(f"  Tickers únicos:          {stats['num_tickers'].iloc[0]}")
    print(f"  Primera barra:           {stats['first_bar'].iloc[0]}")
    print(f"  Última barra:            {stats['last_bar'].iloc[0]}")
    
    daily_stats = con.execute("""
        SELECT COUNT(*) AS rows, COUNT(DISTINCT ticker) AS tickers
        FROM prices_daily
    """).fetchdf()
    print(f"  Filas diarias:           {daily_stats['rows'].iloc[0]:,}")
    
    # ── 2. Cobertura por ticker ──
    print("\n📈 COBERTURA POR TICKER")
    print("-" * 50)
    
    ticker_filter = f"WHERE ticker = '{ticker}'" if ticker else ""
    
    coverage = con.execute(f"""
        SELECT 
            ticker,
            COUNT(*) AS bars_1min,
            MIN(ts) AS first_bar,
            MAX(ts) AS last_bar,
            COUNT(DISTINCT CAST(ts AS DATE)) AS trading_days,
            AVG(volume) AS avg_volume,
            SUM(CASE WHEN volume = 0 THEN 1 ELSE 0 END) AS zero_vol_bars,
            SUM(CASE WHEN close <= 0 THEN 1 ELSE 0 END) AS invalid_price_bars
        FROM prices_1min
        {ticker_filter}
        GROUP BY ticker
        ORDER BY bars_1min DESC
    """).fetchdf()
    
    if detailed or ticker:
        print(f"{'Ticker':<8} {'Barras':>10} {'Días':>6} {'Inicio':>12} "
              f"{'Fin':>12} {'VolMed':>12} {'Vol0':>6} {'BadPx':>6}")
        print("-" * 80)
        for _, row in coverage.iterrows():
            print(
                f"{row['ticker']:<8} {row['bars_1min']:>10,} {row['trading_days']:>6} "
                f"{str(row['first_bar'])[:10]:>12} {str(row['last_bar'])[:10]:>12} "
                f"{row['avg_volume']:>12,.0f} {row['zero_vol_bars']:>6} "
                f"{row['invalid_price_bars']:>6}"
            )
    else:
        # Resumen compacto
        print(f"  Tickers con >1000 días: {len(coverage[coverage['trading_days'] > 1000])}")
        print(f"  Tickers con >500 días:  {len(coverage[coverage['trading_days'] > 500])}")
        print(f"  Tickers con <100 días:  {len(coverage[coverage['trading_days'] < 100])}")
        print(f"  Media barras/ticker:    {coverage['bars_1min'].mean():,.0f}")
        print(f"  Mediana barras/ticker:  {coverage['bars_1min'].median():,.0f}")
    
    # ── 3. Calidad de datos ──
    print("\n🔍 CALIDAD DE DATOS")
    print("-" * 50)
    
    quality = con.execute(f"""
        SELECT
            SUM(CASE WHEN volume = 0 THEN 1 ELSE 0 END) AS zero_volume,
            SUM(CASE WHEN close <= 0 THEN 1 ELSE 0 END) AS bad_price,
            SUM(CASE WHEN high < low THEN 1 ELSE 0 END) AS high_lt_low,
            SUM(CASE WHEN open > high OR open < low THEN 1 ELSE 0 END) AS open_outside,
            SUM(CASE WHEN close > high OR close < low THEN 1 ELSE 0 END) AS close_outside,
            SUM(CASE WHEN vwap IS NULL THEN 1 ELSE 0 END) AS null_vwap,
            COUNT(*) AS total
        FROM prices_1min
        {ticker_filter}
    """).fetchdf()
    
    total = quality["total"].iloc[0]
    print(f"  Barras volumen = 0:      {quality['zero_volume'].iloc[0]:,} "
          f"({quality['zero_volume'].iloc[0]/total*100:.2f}%)")
    print(f"  Precio inválido (<=0):   {quality['bad_price'].iloc[0]:,}")
    print(f"  High < Low:              {quality['high_lt_low'].iloc[0]:,}")
    print(f"  Open fuera de rango:     {quality['open_outside'].iloc[0]:,}")
    print(f"  Close fuera de rango:    {quality['close_outside'].iloc[0]:,}")
    print(f"  VWAP nulo:               {quality['null_vwap'].iloc[0]:,}")
    
    # ── 4. Progreso de descarga ──
    print("\n📥 PROGRESO DE DESCARGA")
    print("-" * 50)
    
    download_stats = con.execute("""
        SELECT 
            status,
            COUNT(*) AS chunks,
            SUM(rows_downloaded) AS total_rows
        FROM download_log
        GROUP BY status
    """).fetchdf()
    
    for _, row in download_stats.iterrows():
        rows_str = f"{row['total_rows']:,}" if row['total_rows'] else "0"
        print(f"  {row['status']:<10}: {row['chunks']:>6} chunks ({rows_str} filas)")
    
    # ── 5. Tamaño de la base de datos ──
    print("\n💾 TAMAÑO")
    print("-" * 50)
    db_size = Path(DUCKDB_PATH).stat().st_size if Path(DUCKDB_PATH).exists() else 0
    print(f"  Archivo:                 {db_size / 1e6:.1f} MB")
    
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Verificación de datos descargados")
    parser.add_argument("--ticker", "-t", type=str, help="Verificar solo un ticker")
    parser.add_argument("--detailed", "-d", action="store_true", help="Reporte detallado")
    args = parser.parse_args()
    
    if not Path(DUCKDB_PATH).exists():
        logger.error(f"❌ Base de datos no encontrada: {DUCKDB_PATH}")
        logger.error("   Ejecuta primero: python scripts/01_init_database.py")
        sys.exit(1)
    
    con = duckdb.connect(str(DUCKDB_PATH))
    verify_database(con, ticker=args.ticker, detailed=args.detailed)
    con.close()


if __name__ == "__main__":
    main()

"""
============================================================================
ORB Trading System — Selección del Universo de Trading (Top 50)
============================================================================
Analiza los datos descargados y selecciona las 50 mejores acciones para
la estrategia ORB basándose en:
  1. Volumen diario promedio (liquidez)
  2. Volumen en dólares (capacidad de ejecución)
  3. Volatilidad (ATR % — necesaria para que ORB funcione)
  4. Precio en rango adecuado ($5 - $1000)

Un buen candidato para ORB tiene: alto volumen + volatilidad moderada-alta.

USO:
    python scripts/03_select_universe.py
    python scripts/03_select_universe.py --top 30     # Seleccionar top 30
    python scripts/03_select_universe.py --show-all    # Mostrar ranking completo
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

from config.settings import (
    DUCKDB_PATH, FILTERED_UNIVERSE_SIZE,
    MIN_AVG_DAILY_VOLUME, MIN_AVG_DAILY_DOLLAR_VOL,
    MIN_PRICE, MAX_PRICE,
    LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
)
logger = logging.getLogger("universe")


def calculate_universe_metrics(con: duckdb.DuckDBPyConnection, lookback_months: int = 6) -> pd.DataFrame:
    """
    Calcula metricas de volumen, volatilidad y liquidez para cada ticker
    usando los datos diarios de los ultimos N meses.
    """
    
    logger.info(f"Calculando metricas del universo (ultimos {lookback_months} meses)...")
    
    # ── Calcular metricas usando SQL sobre prices_daily ──
    df = con.execute(f"""
        WITH daily_with_prev AS (
            SELECT 
                ticker,
                date,
                open, high, low, close, volume,
                LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev_close
            FROM prices_daily
            WHERE volume > 0 AND close > 0
              AND date >= CURRENT_DATE - INTERVAL '{lookback_months}' MONTH
        ),
        daily_stats AS (
            SELECT 
                ticker,
                date,
                open, high, low, close, volume,
                prev_close,
                -- ATR: True Range
                GREATEST(
                    high - low,
                    ABS(high - COALESCE(prev_close, close)),
                    ABS(low - COALESCE(prev_close, close))
                ) AS true_range,
                -- Volumen en dolares
                volume * close AS dollar_volume,
                -- Rango intradia %
                CASE WHEN close > 0 
                    THEN (high - low) / close * 100 
                    ELSE 0 
                END AS intraday_range_pct,
                -- Daily return
                CASE WHEN prev_close > 0 
                    THEN close / prev_close - 1 
                    ELSE NULL 
                END AS daily_return
            FROM daily_with_prev
        ),
        ticker_metrics AS (
            SELECT
                ticker,
                COUNT(*) AS trading_days,
                AVG(close) AS avg_price,
                MIN(close) AS min_price,
                MAX(close) AS max_price,
                -- Volumen
                AVG(volume) AS avg_daily_volume,
                MEDIAN(volume) AS median_daily_volume,
                AVG(dollar_volume) AS avg_dollar_volume,
                -- Volatilidad
                AVG(true_range) AS avg_atr,
                CASE WHEN AVG(close) > 0 
                    THEN AVG(true_range) / AVG(close) * 100 
                    ELSE 0 
                END AS avg_atr_pct,
                AVG(intraday_range_pct) AS avg_range_pct,
                STDDEV(daily_return) AS daily_return_std,
                -- Ultimo precio
                LAST(close ORDER BY date) AS last_price,
                MAX(date) AS last_date
            FROM daily_stats
            GROUP BY ticker
            HAVING COUNT(*) >= 50
        )
        SELECT 
            *,
            -- Score combinado: normalizado volumen × volatilidad
            -- Un buen candidato ORB tiene alto volumen Y buena volatilidad
            (avg_dollar_volume / 1e8) * avg_atr_pct AS orb_score
        FROM ticker_metrics
        ORDER BY orb_score DESC
    """).fetchdf()
    
    return df


def select_top_universe(
    df: pd.DataFrame,
    top_n: int = FILTERED_UNIVERSE_SIZE,
) -> pd.DataFrame:
    """
    Selecciona las top N acciones para trading ORB.
    
    Sin umbrales hardcodeados. Solo:
    - Descarta tickers con precio <= $1 (penny stocks)
    - Descarta tickers con volumen 0
    - Rankea por orb_score (volumen_dolar x volatilidad)
    - Coge los top N
    
    Se adapta automaticamente a cualquier periodo o datos.
    """
    
    logger.info(f"Tickers con datos: {len(df)}")
    
    # Solo filtros de sanidad basicos
    filtered = df[
        (df["avg_price"] > 1.0) &
        (df["avg_daily_volume"] > 0) &
        (df["avg_atr_pct"] > 0)
    ].copy()
    
    logger.info(f"Tickers validos: {len(filtered)}")
    
    # Top N por orb_score
    top = filtered.nlargest(top_n, "orb_score").copy()
    top["rank"] = range(1, len(top) + 1)
    
    return top


def save_universe(con: duckdb.DuckDBPyConnection, top_df: pd.DataFrame):
    """Guarda la selección del universo en la tabla 'universe'."""
    
    # Resetear selecciones anteriores
    con.execute("UPDATE universe SET in_top50 = FALSE WHERE in_top50 = TRUE")
    
    for _, row in top_df.iterrows():
        con.execute("""
            INSERT OR REPLACE INTO universe 
            (ticker, avg_daily_volume, avg_dollar_volume, avg_atr_pct, 
             avg_price, in_top50, last_updated)
            VALUES (?, ?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP)
        """, [
            row["ticker"],
            row["avg_daily_volume"],
            row["avg_dollar_volume"],
            row["avg_atr_pct"],
            row["avg_price"],
        ])
    
    logger.info(f"✅ {len(top_df)} tickers guardados en tabla 'universe'")


def print_universe_report(top_df: pd.DataFrame, show_all: bool = False):
    """Imprime un reporte detallado del universo seleccionado."""
    
    display_df = top_df if show_all else top_df.head(50)
    
    print("\n" + "=" * 90)
    print("UNIVERSO DE TRADING ORB — TOP 50")
    print("=" * 90)
    print(
        f"{'#':>3}  {'Ticker':<8} {'Precio':>10} {'Vol.Diario':>14} "
        f"{'Vol.$':>14} {'ATR%':>8} {'Rango%':>8} {'Score':>10}"
    )
    print("-" * 90)
    
    for _, row in display_df.iterrows():
        print(
            f"{row['rank']:3d}  {row['ticker']:<8} "
            f"${row['avg_price']:>9.2f} "
            f"{row['avg_daily_volume']:>13,.0f} "
            f"${row['avg_dollar_volume']:>12,.0f} "
            f"{row['avg_atr_pct']:>7.2f}% "
            f"{row['avg_range_pct']:>7.2f}% "
            f"{row['orb_score']:>9.2f}"
        )
    
    print("-" * 90)
    print(f"\nResumen:")
    print(f"  Tickers seleccionados: {len(top_df)}")
    print(f"  Precio medio:          ${top_df['avg_price'].mean():.2f}")
    print(f"  ATR% medio:            {top_df['avg_atr_pct'].mean():.2f}%")
    print(f"  Vol. diario medio:     {top_df['avg_daily_volume'].mean():,.0f} acciones")
    print(f"  Vol. $ diario medio:   ${top_df['avg_dollar_volume'].mean():,.0f}")
    print("=" * 90)


def get_selected_tickers(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Devuelve la lista de tickers seleccionados en el universo."""
    result = con.execute(
        "SELECT ticker FROM universe WHERE in_top50 = TRUE ORDER BY avg_dollar_volume DESC"
    ).fetchall()
    return [r[0] for r in result]


def main():
    parser = argparse.ArgumentParser(description="Seleccion del universo de trading ORB")
    parser.add_argument("--top", type=int, default=FILTERED_UNIVERSE_SIZE, help="Num de tickers a seleccionar")
    parser.add_argument("--months", type=int, default=6, help="Meses de lookback para metricas (default: 6)")
    parser.add_argument("--show-all", action="store_true", help="Mostrar ranking completo")
    args = parser.parse_args()
    
    con = duckdb.connect(str(DUCKDB_PATH))
    
    # Verificar que hay datos
    count = con.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
    if count == 0:
        logger.error("[ERROR] No hay datos en prices_daily. Ejecuta primero 02_download_data.py")
        con.close()
        sys.exit(1)
    
    logger.info(f"Datos diarios disponibles: {count:,} filas")
    
    # Calcular metricas
    metrics_df = calculate_universe_metrics(con, lookback_months=args.months)
    
    # Seleccionar top N
    top_df = select_top_universe(metrics_df, top_n=args.top)
    
    # Guardar en DB
    save_universe(con, top_df)
    
    # Mostrar reporte
    print_universe_report(top_df, show_all=args.show_all)
    
    # Exportar lista de tickers seleccionados
    selected = get_selected_tickers(con)
    logger.info(f"\nTickers seleccionados: {', '.join(selected)}")
    
    con.close()


if __name__ == "__main__":
    main()

"""
============================================================================
ORB Trading System -- Analisis de criterios de seleccion (OPTIMIZADO)
============================================================================
Version optimizada: carga todos los datos en memoria y procesa con pandas.
No hace queries SQL individuales por dia/ticker.

USO:
    python scripts/07_analyze_criteria.py
============================================================================
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import numpy as np

_THIS_FILE = Path(os.path.abspath(__file__))
_PROJECT_ROOT = str(_THIS_FILE.parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from config.settings import (
    DUCKDB_PATH, LOGS_DIR,
    IBKR_COMMISSION_PER_SHARE, IBKR_MIN_COMMISSION, SLIPPAGE_PCT,
    LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
)

LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "analysis.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("analysis")

ORB_START_H, ORB_START_M = 13, 30
ORB_END_H, ORB_END_M = 14, 0
EOD_H, EOD_M = 19, 55


def load_all_data(con, tickers):
    """Carga todos los datos de 1min y daily en memoria de una vez."""
    ticker_list = "','".join(tickers)
    
    logger.info("Cargando datos de 1 minuto en memoria...")
    t0 = time.time()
    df_1min = con.execute(f"""
        SELECT ticker, ts, open, high, low, close, volume
        FROM prices_1min
        WHERE ticker IN ('{ticker_list}')
        ORDER BY ticker, ts
    """).fetchdf()
    logger.info(f"  {len(df_1min):,} barras cargadas en {time.time()-t0:.1f}s")
    
    logger.info("Cargando datos diarios en memoria...")
    df_daily = con.execute(f"""
        SELECT ticker, date, open, high, low, close, volume
        FROM prices_daily
        WHERE ticker IN ('{ticker_list}')
          AND volume > 0 AND close > 0
        ORDER BY ticker, date
    """).fetchdf()
    logger.info(f"  {len(df_daily):,} filas cargadas")
    
    # Pre-calcular columnas utiles
    df_1min["date"] = df_1min["ts"].dt.date
    df_1min["hour"] = df_1min["ts"].dt.hour
    df_1min["minute"] = df_1min["ts"].dt.minute
    df_1min["time_min"] = df_1min["hour"] * 60 + df_1min["minute"]
    
    return df_1min, df_daily


def backtest_all_tickers(df_1min, tickers):
    """
    Corre el backtest ORB para todos los tickers de una vez usando pandas.
    Devuelve DataFrame con todos los trades.
    """
    all_trades = []
    
    orb_start_min = ORB_START_H * 60 + ORB_START_M  # 810
    orb_end_min = ORB_END_H * 60 + ORB_END_M        # 840
    eod_min = EOD_H * 60 + EOD_M                     # 1195
    
    for ticker in tickers:
        tk_data = df_1min[df_1min["ticker"] == ticker]
        if tk_data.empty:
            continue
        
        dates = tk_data["date"].unique()
        
        for trade_date in dates:
            day = tk_data[tk_data["date"] == trade_date]
            if len(day) < 30:
                continue
            
            # ORB range
            orb = day[(day["time_min"] >= orb_start_min) & (day["time_min"] < orb_end_min)]
            if len(orb) < 5:
                continue
            
            orb_high = orb["high"].max()
            orb_low = orb["low"].min()
            orb_range = orb_high - orb_low
            if orb_range <= 0.01:
                continue
            
            orb_volume = orb["volume"].sum()
            
            # Post-ORB
            post = day[(day["time_min"] >= orb_end_min) & (day["time_min"] <= eod_min)]
            if post.empty:
                continue
            
            # Buscar breakout
            in_trade = False
            
            for idx, bar in post.iterrows():
                if not in_trade:
                    if bar["close"] > orb_high:
                        entry = bar["close"] * (1 + SLIPPAGE_PCT)
                        stop = orb_low
                        target = entry + (entry - stop) * 2.0
                        risk = entry - stop
                        if risk <= 0:
                            continue
                        shares = max(1, int(100 / risk))
                        direction = "LONG"
                        in_trade = True
                        entry_time = bar["ts"]
                        continue
                    
                    if bar["close"] < orb_low:
                        entry = bar["close"] * (1 - SLIPPAGE_PCT)
                        stop = orb_high
                        target = entry - (stop - entry) * 2.0
                        risk = stop - entry
                        if risk <= 0:
                            continue
                        shares = max(1, int(100 / risk))
                        direction = "SHORT"
                        in_trade = True
                        entry_time = bar["ts"]
                        continue
                else:
                    exit_p = None
                    reason = None
                    
                    if direction == "LONG":
                        if bar["low"] <= stop:
                            exit_p, reason = stop, "stop"
                        elif bar["high"] >= target:
                            exit_p, reason = target, "target"
                        elif bar["time_min"] >= eod_min:
                            exit_p, reason = bar["close"], "eod"
                    else:
                        if bar["high"] >= stop:
                            exit_p, reason = stop, "stop"
                        elif bar["low"] <= target:
                            exit_p, reason = target, "target"
                        elif bar["time_min"] >= eod_min:
                            exit_p, reason = bar["close"], "eod"
                    
                    if exit_p is not None:
                        if direction == "LONG":
                            pnl = (exit_p - entry) * shares
                        else:
                            pnl = (entry - exit_p) * shares
                        
                        comm = max(shares * IBKR_COMMISSION_PER_SHARE * 2, IBKR_MIN_COMMISSION * 2)
                        
                        all_trades.append({
                            "ticker": ticker,
                            "date": trade_date,
                            "month": str(trade_date)[:7],
                            "pnl": round(pnl - comm, 2),
                            "reason": reason,
                            "dir": direction,
                            "orb_range": orb_range,
                            "orb_volume": orb_volume,
                        })
                        break
    
    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


def compute_daily_metrics(df_daily, tickers, start_date, end_date):
    """Calcula metricas de precio/volumen para cada ticker en un periodo."""
    mask = (df_daily["date"] >= start_date) & (df_daily["date"] <= end_date)
    period = df_daily[mask]
    
    result = {}
    for ticker in tickers:
        tk = period[period["ticker"] == ticker]
        if tk.empty:
            result[ticker] = {"avg_vol": 0, "avg_dolvol": 0, "avg_atr_pct": 0}
            continue
        
        avg_vol = tk["volume"].mean()
        avg_dolvol = (tk["volume"] * tk["close"]).mean()
        avg_atr = ((tk["high"] - tk["low"]) / tk["close"].clip(lower=0.01) * 100).mean()
        
        result[ticker] = {
            "avg_vol": avg_vol,
            "avg_dolvol": avg_dolvol,
            "avg_atr_pct": avg_atr,
            "orb_score": (avg_dolvol / 1e8) * avg_atr,
        }
    
    return result


def compute_orb_metrics(trades_df, ticker, start_date, end_date):
    """Calcula metricas ORB para un ticker en un periodo."""
    mask = (trades_df["ticker"] == ticker) & (trades_df["date"] >= start_date) & (trades_df["date"] <= end_date)
    tk = trades_df[mask]
    
    if tk.empty or len(tk) < 3:
        return {"trades": 0, "pnl": 0, "wr": 0, "pf": 0}
    
    total = len(tk)
    wins = tk[tk["pnl"] > 0]
    losses = tk[tk["pnl"] <= 0]
    
    wr = len(wins) / total * 100
    gw = wins["pnl"].sum() if len(wins) > 0 else 0
    gl = abs(losses["pnl"].sum()) if len(losses) > 0 else 0
    pf = gw / gl if gl > 0 else 999
    
    return {
        "trades": total,
        "pnl": round(tk["pnl"].sum(), 2),
        "wr": round(wr, 1),
        "pf": round(pf, 2),
    }


def month_start_end(month_str):
    """Devuelve (start_date, end_date) como date para un mes 'YYYY-MM'."""
    dt = datetime.strptime(month_str + "-01", "%Y-%m-%d").date()
    if dt.month == 12:
        end = datetime(dt.year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end = datetime(dt.year, dt.month + 1, 1).date() - timedelta(days=1)
    return dt, end


def main():
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    
    # Obtener tickers del universo
    tickers = [r[0] for r in con.execute(
        "SELECT ticker FROM universe WHERE in_top50 = TRUE"
    ).fetchall()]
    
    if not tickers:
        logger.error("[ERROR] No hay tickers en el universo")
        con.close()
        return
    
    logger.info(f"Tickers: {len(tickers)}")
    
    # Cargar todo en memoria
    df_1min, df_daily = load_all_data(con, tickers)
    con.close()
    
    # Convertir dates
    df_daily["date"] = pd.to_datetime(df_daily["date"]).dt.date
    
    # Correr backtest completo de todos los tickers
    logger.info("")
    logger.info("Ejecutando backtest ORB para todos los tickers...")
    t0 = time.time()
    all_trades = backtest_all_tickers(df_1min, tickers)
    logger.info(f"  {len(all_trades)} trades generados en {time.time()-t0:.1f}s")
    
    if all_trades.empty:
        logger.error("[ERROR] No se generaron trades")
        return
    
    # Liberar memoria de 1min
    del df_1min
    
    # Obtener meses unicos
    all_months = sorted(all_trades["month"].unique())
    logger.info(f"Meses con trades: {len(all_months)} ({all_months[0]} -> {all_months[-1]})")
    
    LOOKBACK = 6
    start_idx = LOOKBACK
    
    if len(all_months) < start_idx + 2:
        logger.error("[ERROR] No hay suficientes meses")
        return
    
    criteria_names = [
        "mayor_dolvol",
        "mayor_atr",
        "mayor_orb_score",
        "mejor_winrate",
        "mejor_pf",
        "mejor_pnl",
    ]
    criteria_results = {c: [] for c in criteria_names}
    random_results = []
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("ANALISIS DE CRITERIOS DE SELECCION")
    logger.info(f"Lookback: {LOOKBACK} meses | Re-seleccion: mensual")
    logger.info(f"Periodo test: {all_months[start_idx]} -> {all_months[-1]}")
    logger.info("=" * 70)
    
    total_test = len(all_months) - start_idx
    t_start = time.time()
    
    for mi in range(start_idx, len(all_months)):
        test_month = all_months[mi]
        lb_months = all_months[mi - LOOKBACK:mi]
        
        lb_start, _ = month_start_end(lb_months[0])
        _, lb_end = month_start_end(lb_months[-1])
        test_start, test_end = month_start_end(test_month)
        
        progress = mi - start_idx + 1
        elapsed = time.time() - t_start
        eta = (elapsed / max(progress, 1)) * (total_test - progress)
        logger.info(f"  [{progress}/{total_test}] Test: {test_month} | LB: {lb_months[0]}-{lb_months[-1]} | ETA: {eta:.0f}s")
        
        # Metricas de precio/volumen del lookback
        daily_m = compute_daily_metrics(df_daily, tickers, lb_start, lb_end)
        
        # Metricas ORB del lookback
        orb_m = {}
        for ticker in tickers:
            orb_m[ticker] = compute_orb_metrics(all_trades, ticker, lb_start, lb_end)
        
        # Tickers validos (con suficientes trades en lookback)
        valid = [t for t in tickers if orb_m[t]["trades"] >= 5]
        if not valid:
            valid = [t for t in tickers if orb_m[t]["trades"] > 0]
        if not valid:
            continue
        
        # Seleccionar por cada criterio
        selected = {}
        selected["mayor_dolvol"] = max(tickers, key=lambda t: daily_m[t]["avg_dolvol"])
        selected["mayor_atr"] = max(tickers, key=lambda t: daily_m[t]["avg_atr_pct"])
        selected["mayor_orb_score"] = max(tickers, key=lambda t: daily_m[t].get("orb_score", 0))
        selected["mejor_winrate"] = max(valid, key=lambda t: orb_m[t]["wr"])
        selected["mejor_pf"] = max(valid, key=lambda t: orb_m[t]["pf"])
        selected["mejor_pnl"] = max(valid, key=lambda t: orb_m[t]["pnl"])
        
        # Testear cada seleccion en el mes test
        test_trades = all_trades[(all_trades["month"] == test_month)]
        
        for criterion, ticker in selected.items():
            tk_test = test_trades[test_trades["ticker"] == ticker]
            month_pnl = tk_test["pnl"].sum() if not tk_test.empty else 0
            
            criteria_results[criterion].append({
                "month": test_month,
                "ticker": ticker,
                "pnl": round(month_pnl, 2),
                "trades": len(tk_test),
            })
        
        # Random baseline
        all_pnls = []
        for ticker in tickers:
            tk_test = test_trades[test_trades["ticker"] == ticker]
            all_pnls.append(tk_test["pnl"].sum() if not tk_test.empty else 0)
        
        random_results.append({
            "month": test_month,
            "pnl": round(np.mean(all_pnls), 2),
        })
    
    # ── Resultados ──
    print("")
    print("=" * 80)
    print("RESULTADOS: COMPARACION DE CRITERIOS DE SELECCION")
    print("=" * 80)
    print(f"{'Criterio':<20} {'P&L Total':>12} {'P&L/Mes':>10} {'Meses+':>8} {'Meses-':>8} {'Win%':>8}")
    print("-" * 80)
    
    summary = []
    for criterion in criteria_names:
        results = criteria_results[criterion]
        if not results:
            continue
        
        total_pnl = sum(r["pnl"] for r in results)
        avg_pnl = total_pnl / len(results)
        months_pos = sum(1 for r in results if r["pnl"] > 0)
        months_neg = sum(1 for r in results if r["pnl"] <= 0)
        win_pct = months_pos / len(results) * 100
        
        summary.append({
            "criterion": criterion,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "months_pos": months_pos,
            "months_neg": months_neg,
            "win_pct": win_pct,
            "results": results,
        })
        
        print(f"{criterion:<20} ${total_pnl:>+10,.2f} ${avg_pnl:>+8,.2f} {months_pos:>8} {months_neg:>8} {win_pct:>7.1f}%")
    
    rand_pnl = sum(r["pnl"] for r in random_results)
    rand_avg = rand_pnl / len(random_results) if random_results else 0
    rand_pos = sum(1 for r in random_results if r["pnl"] > 0)
    rand_neg = sum(1 for r in random_results if r["pnl"] <= 0)
    rand_wp = rand_pos / len(random_results) * 100 if random_results else 0
    print("-" * 80)
    print(f"{'RANDOM (media)':<20} ${rand_pnl:>+10,.2f} ${rand_avg:>+8,.2f} {rand_pos:>8} {rand_neg:>8} {rand_wp:>7.1f}%")
    
    if summary:
        best = max(summary, key=lambda s: s["total_pnl"])
        worst = min(summary, key=lambda s: s["total_pnl"])
        
        print("")
        print(f">> MEJOR CRITERIO:  {best['criterion']} (${best['total_pnl']:+,.2f})")
        print(f">> PEOR CRITERIO:   {worst['criterion']} (${worst['total_pnl']:+,.2f})")
        print("")
        
        print(f"DETALLE MENSUAL: {best['criterion']}")
        print("-" * 60)
        for r in best["results"]:
            marker = "[+]" if r["pnl"] > 0 else "[-]"
            print(f"  {r['month']}  {r['ticker']:<6}  ${r['pnl']:>+8,.2f}  ({r['trades']} trades)  {marker}")
    
    print("")
    print("=" * 80)
    elapsed = time.time() - t_start
    print(f"Tiempo total: {elapsed/60:.1f} minutos")
    print("=" * 80)


if __name__ == "__main__":
    main()

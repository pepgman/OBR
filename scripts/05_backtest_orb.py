"""
============================================================================
ORB Trading System -- Backtest v4 (timezone corregida + optimización rápida)
============================================================================
CORRECCIONES vs v3:
  - Timestamps convertidos correctamente de UTC a US/Eastern (respeta DST)
  - Constantes ORB en hora ET
  - Scoring usa datos D-1 (sin look-ahead)

OPTIMIZACIÓN RÁPIDA:
  - Precarga datos y calcula ORB ranges UNA sola vez
  - La optimización solo itera SL/TP sobre datos en memoria
  - 120 combinaciones en segundos, no minutos

USO:
    python scripts/05_backtest_orb.py --sl 0.5 --tp 2.0 --start 2025-01-01 --end 2025-06-30
    python scripts/05_backtest_orb.py --optimize --start 2024-01-01 --end 2024-12-31
============================================================================
"""

import os
import sys
import json
import time
import logging
import argparse
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
    DUCKDB_PATH, LOGS_DIR, INITIAL_CAPITAL,
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
        logging.FileHandler(LOGS_DIR / "backtest.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("backtest")

# ======================================================================
# CONSTANTES ORB EN HORA ET
# ======================================================================
ORB_START_H, ORB_START_M = 9, 30
ORB_END_H, ORB_END_M = 10, 0
EOD_H, EOD_M = 15, 55
CUTOFF_H, CUTOFF_M = 14, 30

ORB_START_MIN = ORB_START_H * 60 + ORB_START_M
ORB_END_MIN = ORB_END_H * 60 + ORB_END_M
EOD_MIN = EOD_H * 60 + EOD_M
CUTOFF_MIN = CUTOFF_H * 60 + CUTOFF_M

LOOKBACK_MONTHS = 6


# ======================================================================
# FASE 1: PREPARAR DATOS (se ejecuta UNA sola vez)
# ======================================================================

def prepare_orb_data(start_date=None, end_date=None, max_daily_trades=1):
    """
    Carga datos, calcula scoring, convierte timezone, calcula ORB ranges.
    Devuelve lista de day_setups con todo precalculado.
    """
    con = duckdb.connect(str(DUCKDB_PATH))

    tickers = [r[0] for r in con.execute(
        "SELECT ticker FROM universe WHERE in_top50 = TRUE"
    ).fetchall()]

    if not tickers:
        logger.error("[ERROR] No hay tickers en el universo")
        con.close()
        return None

    ticker_list = "','".join(tickers)
    df_daily = con.execute(f"""
        SELECT ticker, date, open, high, low, close, volume
        FROM prices_daily
        WHERE ticker IN ('{ticker_list}') AND volume > 0 AND close > 0
        ORDER BY ticker, date
    """).fetchdf()
    df_daily["date"] = pd.to_datetime(df_daily["date"])

    date_filter = ""
    if start_date:
        date_filter += f" AND date >= '{start_date}'"
    if end_date:
        date_filter += f" AND date <= '{end_date}'"

    all_dates = con.execute(f"""
        SELECT DISTINCT date as d
        FROM prices_daily
        WHERE ticker IN ('{ticker_list}') {date_filter}
        ORDER BY d
    """).fetchdf()["d"].tolist()

    all_dates_str = [str(d)[:10] for d in all_dates]

    total_days = len(all_dates)
    logger.info(f"Preparando datos ORB | {total_days} dias | {len(tickers)} tickers")
    print(f"[PREP] Cargando {total_days} dias...", flush=True)
    t0 = time.time()

    day_setups = []

    for di, trade_date in enumerate(all_dates):
        if (di + 1) % 25 == 0 or di == 0:
            pct = int((di + 1) / total_days * 100)
            print(f"[PREP] {di+1}/{total_days} dias ({pct}%)", flush=True)
        trade_date_str = all_dates_str[di]
        trade_date_pd = pd.Timestamp(trade_date)

        # Scoring D-1
        cutoff_pd = trade_date_pd - pd.Timedelta(days=LOOKBACK_MONTHS * 30)
        period = df_daily[
            (df_daily["date"] >= cutoff_pd) & (df_daily["date"] < trade_date_pd)
        ]

        ticker_scores = []
        for ticker in tickers:
            tk = period[period["ticker"] == ticker]
            if len(tk) < 20:
                continue
            avg_dolvol = (tk["volume"] * tk["close"]).mean()
            avg_atr = (
                (tk["high"] - tk["low"]) / tk["close"].clip(lower=0.01) * 100
            ).mean()
            score = (avg_dolvol / 1e8) * avg_atr
            ticker_scores.append((ticker, score))

        if not ticker_scores:
            continue

        ticker_scores.sort(key=lambda x: x[1], reverse=True)
        candidates = [t[0] for t in ticker_scores[:max_daily_trades]]

        for best_ticker in candidates:
            bars = con.execute(f"""
                SELECT ts, open, high, low, close, volume
                FROM prices_1min
                WHERE ticker = '{best_ticker}'
                  AND CAST(ts AS DATE) >= '{trade_date_str}'
                  AND CAST(ts AS DATE) <= DATE '{trade_date_str}' + INTERVAL 1 DAY
                ORDER BY ts
            """).fetchdf()

            if len(bars) < 30:
                continue

            bars = bars.copy()
            bars['ts_utc'] = pd.to_datetime(bars['ts']).dt.tz_localize('UTC')
            bars['ts_et'] = bars['ts_utc'].dt.tz_convert('US/Eastern')
            bars['time_min_et'] = bars['ts_et'].dt.hour * 60 + bars['ts_et'].dt.minute
            bars['date_et'] = bars['ts_et'].dt.date

            trade_date_date = pd.Timestamp(trade_date_str).date()
            bars = bars[bars['date_et'] == trade_date_date]

            if len(bars) < 30:
                continue

            orb = bars[
                (bars["time_min_et"] >= ORB_START_MIN) &
                (bars["time_min_et"] < ORB_END_MIN)
            ]
            if len(orb) < 5:
                continue

            orb_high = float(orb["high"].max())
            orb_low = float(orb["low"].min())
            orb_range = orb_high - orb_low
            if orb_range <= 0.01:
                continue

            post = bars[
                (bars["time_min_et"] >= ORB_END_MIN) &
                (bars["time_min_et"] <= EOD_MIN)
            ]
            if post.empty:
                continue

            post_data = []
            for _, bar in post.iterrows():
                post_data.append((
                    int(bar["time_min_et"]),
                    float(bar["open"]),
                    float(bar["high"]),
                    float(bar["low"]),
                    float(bar["close"]),
                    bar["ts"],
                ))

            day_setups.append({
                "date": trade_date_str,
                "ticker": best_ticker,
                "orb_high": orb_high,
                "orb_low": orb_low,
                "post_bars": post_data,
            })

    con.close()
    elapsed = time.time() - t0
    logger.info(f"  Datos preparados: {len(day_setups)} dias con ORB valido en {elapsed:.1f}s")
    print(f"[PREP] Listo: {len(day_setups)} dias con ORB valido ({elapsed:.1f}s)", flush=True)

    return day_setups


# ======================================================================
# FASE 2: SIMULAR TRADES (rápido, solo depende de SL/TP)
# ======================================================================

def simulate_trades(day_setups, sl_pct=0.5, tp_mult=2.0):
    """Simula trades sobre datos ya preparados. Muy rápido."""
    all_trades = []
    capital = INITIAL_CAPITAL
    trade_id = 0

    for setup in day_setups:
        orb_high = setup["orb_high"]
        orb_low = setup["orb_low"]
        in_trade = False

        for time_min, o, h, l, c, ts in setup["post_bars"]:
            if not in_trade:
                if time_min >= CUTOFF_MIN:
                    break

                if c > orb_high:
                    entry = c * (1 + SLIPPAGE_PCT)
                    sl_dist = entry * (sl_pct / 100)
                    stop = entry - sl_dist
                    target = entry + sl_dist * tp_mult
                    direction = "LONG"
                elif c < orb_low:
                    entry = c * (1 - SLIPPAGE_PCT)
                    sl_dist = entry * (sl_pct / 100)
                    stop = entry + sl_dist
                    target = entry - sl_dist * tp_mult
                    direction = "SHORT"
                else:
                    continue

                if sl_dist <= 0:
                    continue
                risk_amount = capital * 0.01
                shares = max(1, int(risk_amount / sl_dist))
                max_shares = int(capital * 0.95 / entry) if entry > 0 else 0
                shares = min(shares, max(max_shares, 1))
                if shares <= 0:
                    continue

                in_trade = True
                entry_time = ts
                continue
            else:
                exit_p = None
                reason = None

                if direction == "LONG":
                    if l <= stop:
                        exit_p, reason = stop, "stop"
                    elif h >= target:
                        exit_p, reason = target, "target"
                    elif time_min >= EOD_MIN:
                        exit_p, reason = c, "eod"
                else:
                    if h >= stop:
                        exit_p, reason = stop, "stop"
                    elif l <= target:
                        exit_p, reason = target, "target"
                    elif time_min >= EOD_MIN:
                        exit_p, reason = c, "eod"

                if exit_p is not None:
                    if direction == "LONG":
                        pnl_gross = (exit_p - entry) * shares
                    else:
                        pnl_gross = (entry - exit_p) * shares

                    comm = max(
                        shares * IBKR_COMMISSION_PER_SHARE * 2,
                        IBKR_MIN_COMMISSION * 2,
                    )
                    pnl_net = pnl_gross - comm
                    capital += pnl_net
                    trade_id += 1

                    all_trades.append({
                        "trade_id": trade_id,
                        "ticker": setup["ticker"],
                        "date": setup["date"],
                        "direction": direction,
                        "entry_time": entry_time,
                        "exit_time": ts,
                        "entry_price": round(entry, 2),
                        "exit_price": round(exit_p, 2),
                        "shares": shares,
                        "pnl_gross": round(pnl_gross, 2),
                        "pnl_net": round(pnl_net, 2),
                        "commission": round(comm, 2),
                        "orb_high": round(orb_high, 2),
                        "orb_low": round(orb_low, 2),
                        "stop_loss": round(stop, 2),
                        "reason_exit": reason,
                    })
                    break

    return all_trades, capital


# ======================================================================
# MÉTRICAS
# ======================================================================

def calculate_metrics(all_trades):
    if not all_trades:
        return None

    trades_df = pd.DataFrame(all_trades)
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])
    trades_df["date"] = pd.to_datetime(trades_df["date"])

    wins = trades_df[trades_df["pnl_net"] > 0]
    losses = trades_df[trades_df["pnl_net"] <= 0]
    total = len(trades_df)
    n_w = len(wins)
    n_l = len(losses)
    wr = n_w / total * 100 if total > 0 else 0
    avg_w = wins["pnl_net"].mean() if n_w > 0 else 0
    avg_l = losses["pnl_net"].mean() if n_l > 0 else 0
    gw = wins["pnl_net"].sum() if n_w > 0 else 0
    gl = abs(losses["pnl_net"].sum()) if n_l > 0 else 0
    pf = gw / gl if gl > 0 else 999
    total_pnl = trades_df["pnl_net"].sum()

    eq = INITIAL_CAPITAL + trades_df["pnl_net"].cumsum()
    eq = pd.concat([pd.Series([INITIAL_CAPITAL]), eq]).reset_index(drop=True)
    peak = eq.cummax()
    max_dd = ((eq - peak) / peak * 100).min()

    daily_pnl = trades_df.groupby("date")["pnl_net"].sum()
    sharpe = (
        (daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252)
        if len(daily_pnl) > 1 and daily_pnl.std() > 0 else 0
    )
    ds = daily_pnl[daily_pnl < 0]
    sortino = (
        (daily_pnl.mean() / ds.std()) * np.sqrt(252)
        if len(ds) > 1 and ds.std() > 0 else 0
    )

    days_span = (trades_df["date"].max() - trades_df["date"].min()).days
    annual_ret = total_pnl / INITIAL_CAPITAL / max(1, days_span / 365) * 100
    calmar = annual_ret / abs(max_dd) if max_dd != 0 else 0

    durations = (trades_df["exit_time"] - trades_df["entry_time"]).dt.total_seconds() / 60
    avg_dur = durations.mean()

    return {
        "total_trades": total, "winning_trades": n_w, "losing_trades": n_l,
        "win_rate": round(wr, 2), "avg_win": round(avg_w, 2),
        "avg_loss": round(avg_l, 2), "profit_factor": round(pf, 2),
        "total_pnl_net": round(total_pnl, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2), "calmar_ratio": round(calmar, 2),
        "avg_trade_duration": round(avg_dur, 1),
    }


# ======================================================================
# GUARDAR EN DB
# ======================================================================

def save_results(all_trades, metrics, sl_pct, tp_mult, start_date, end_date,
                 max_daily_trades=1):
    if not all_trades or not metrics:
        return

    trades_df = pd.DataFrame(all_trades)
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])
    trades_df["date"] = pd.to_datetime(trades_df["date"])

    con = duckdb.connect(str(DUCKDB_PATH))

    con.execute("DELETE FROM bt_trades_orb")
    con.register("tmp_trades", trades_df)
    con.execute("""
        INSERT INTO bt_trades_orb
        (trade_id, ticker, date, direction, entry_time, entry_price,
         exit_time, exit_price, shares, pnl_gross, pnl_net, commission,
         slippage, orb_high, orb_low, stop_loss, reason_exit)
        SELECT trade_id, ticker, date, direction, entry_time, entry_price,
               exit_time, exit_price, shares, pnl_gross, pnl_net, commission,
               0, orb_high, orb_low, stop_loss, reason_exit
        FROM tmp_trades
    """)
    con.unregister("tmp_trades")

    run_id = con.execute(
        "SELECT COALESCE(MAX(run_id), 0) + 1 FROM bt_metrics"
    ).fetchone()[0]

    p_start = str(trades_df["date"].min().date())
    p_end = str(trades_df["date"].max().date())
    params = json.dumps({
        "v": "v4", "sl": sl_pct, "tp": tp_mult,
        "start": start_date, "end": end_date,
        "max_daily_trades": max_daily_trades,
    })

    m = metrics
    con.execute("""
        INSERT INTO bt_metrics
        (run_id, strategy, period_start, period_end, total_trades,
         winning_trades, losing_trades, win_rate, avg_win, avg_loss,
         profit_factor, total_pnl_net, max_drawdown_pct, sharpe_ratio,
         sortino_ratio, calmar_ratio, avg_trade_duration, params_json)
        VALUES (?, 'ORB_v4', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        run_id, p_start, p_end, m["total_trades"], m["winning_trades"],
        m["losing_trades"], m["win_rate"], m["avg_win"], m["avg_loss"],
        m["profit_factor"], m["total_pnl_net"], m["max_drawdown_pct"],
        m["sharpe_ratio"], m["sortino_ratio"], m["calmar_ratio"],
        m["avg_trade_duration"], params,
    ])

    con.close()


# ======================================================================
# FUNCIONES PÚBLICAS (compatibles con API server)
# ======================================================================

def run_backtest(sl_pct=0.5, tp_mult=2.0, start_date=None, end_date=None,
                 max_daily_trades=1, save_to_db=True):
    """Backtest ORB v4 completo. Compatible con API server."""
    day_setups = prepare_orb_data(start_date, end_date, max_daily_trades)
    if not day_setups:
        return None

    all_trades, capital = simulate_trades(day_setups, sl_pct, tp_mult)
    if not all_trades:
        logger.info("No se generaron trades")
        return None

    metrics = calculate_metrics(all_trades)

    if save_to_db:
        save_results(all_trades, metrics, sl_pct, tp_mult, start_date, end_date,
                     max_daily_trades)

    print()
    print(f"ORB v4 | SL:{sl_pct}% | TP:{tp_mult}x | "
          f"{all_trades[0]['date']} -> {all_trades[-1]['date']}")
    print(f"P&L: ${metrics['total_pnl_net']:+,.2f} "
          f"({(capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100:+.1f}%)")
    print(f"Trades: {metrics['total_trades']} "
          f"({metrics['winning_trades']}W/{metrics['losing_trades']}L) | "
          f"WR: {metrics['win_rate']:.1f}% | PF: {metrics['profit_factor']:.2f}")
    print(f"Sharpe: {metrics['sharpe_ratio']:.2f} | "
          f"MaxDD: {metrics['max_drawdown_pct']:.1f}% | "
          f"Duracion: {metrics['avg_trade_duration']:.0f}min")

    return metrics


def run_optimize(start_date=None, end_date=None):
    """Optimización rápida: precarga datos UNA vez, itera SL/TP en memoria."""
    logger.info("Preparando datos para optimizacion...")
    day_setups = prepare_orb_data(start_date, end_date, max_daily_trades=1)
    if not day_setups:
        logger.error("No hay datos para optimizar")
        return []

    logger.info(f"Datos listos: {len(day_setups)} dias. Probando combinaciones...")

    sl_values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    tp_values = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0, 50.0]

    results = []
    total_combos = len(sl_values) * len(tp_values)
    t0 = time.time()
    print(f"[OPT] Probando {total_combos} combinaciones...", flush=True)

    combo_idx = 0
    for sl in sl_values:
        for tp in tp_values:
            combo_idx += 1
            all_trades, capital = simulate_trades(day_setups, sl, tp)
            if all_trades:
                m = calculate_metrics(all_trades)
                if m:
                    results.append({"sl": sl, "tp": tp, **m})
            if combo_idx % 12 == 0:
                pct = int(combo_idx / total_combos * 100)
                print(f"[OPT] {combo_idx}/{total_combos} ({pct}%)", flush=True)

    elapsed = time.time() - t0
    logger.info(f"  {total_combos} combinaciones en {elapsed:.1f}s")
    print(f"[OPT] Completado: {total_combos} combos en {elapsed:.1f}s", flush=True)

    results.sort(key=lambda r: r["total_pnl_net"], reverse=True)

    print()
    print("=" * 95)
    print("OPTIMIZACION SL x TP")
    print("=" * 95)
    print(f"{'SL%':>6} {'TPx':>6} {'P&L':>12} {'WR%':>8} {'PF':>8} "
          f"{'Sharpe':>8} {'MaxDD':>8} {'Trades':>8}")
    print("-" * 95)
    for r in results[:20]:
        print(f"{r['sl']:>5.1f}% {r['tp']:>5.1f}x "
              f"${r['total_pnl_net']:>+10,.2f} {r['win_rate']:>7.1f}% "
              f"{r['profit_factor']:>7.02f} {r['sharpe_ratio']:>7.2f} "
              f"{r['max_drawdown_pct']:>7.1f}% {r['total_trades']:>7}")

    if results:
        b = results[0]
        print("-" * 95)
        print(f"MEJOR: SL:{b['sl']}% TP:{b['tp']}x -> "
              f"P&L ${b['total_pnl_net']:+,.2f} | Sharpe {b['sharpe_ratio']:.2f}")

        all_trades, _ = simulate_trades(day_setups, b["sl"], b["tp"])
        m = calculate_metrics(all_trades)
        save_results(all_trades, m, b["sl"], b["tp"], start_date, end_date)

    print("=" * 95)
    return results


def run_backtest_no_save(sl_pct=0.5, tp_mult=2.0, start_date=None, end_date=None,
                         save_to_db=True):
    return run_backtest(sl_pct=sl_pct, tp_mult=tp_mult, start_date=start_date,
                        end_date=end_date, save_to_db=save_to_db)


def main():
    parser = argparse.ArgumentParser(description="ORB Backtest v4")
    parser.add_argument("--sl", type=float, default=0.5)
    parser.add_argument("--tp", type=float, default=2.0)
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--max-trades", type=int, default=1)
    parser.add_argument("--optimize", action="store_true")
    args = parser.parse_args()

    if args.optimize:
        run_optimize(start_date=args.start, end_date=args.end)
    else:
        run_backtest(
            sl_pct=args.sl, tp_mult=args.tp,
            start_date=args.start, end_date=args.end,
            max_daily_trades=args.max_trades,
        )


if __name__ == "__main__":
    main()

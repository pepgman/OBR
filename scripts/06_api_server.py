"""
============================================================================
ORB Trading System -- API Server (Flask)
============================================================================
Servidor local que expone los datos de DuckDB como endpoints REST.
El dashboard React hace fetch a estos endpoints.

USO:
    pip install flask flask-cors
    python scripts/06_api_server.py

Endpoints:
    GET  /api/tickers          - Tickers del universo
    GET  /api/trades           - Trades del backtest (filtros: ticker, direction)
    GET  /api/metrics          - Metricas globales
    GET  /api/equity           - Curva de equity
    GET  /api/monthly          - P&L mensual
    GET  /api/universe         - Datos del universo completo
    POST /api/backtest/run     - Ejecutar backtest con parametros custom
============================================================================
"""

import os
import sys
import json
import subprocess
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
import duckdb
import pandas as pd
import numpy as np

# Path setup
_THIS_FILE = Path(os.path.abspath(__file__))
_PROJECT_ROOT = str(_THIS_FILE.parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from config.settings import DUCKDB_PATH, INITIAL_CAPITAL

app = Flask(__name__)
CORS(app)  # Permite llamadas desde el dashboard React


def get_db():
    """Abre conexion a DuckDB (read-only para queries)."""
    return duckdb.connect(str(DUCKDB_PATH), read_only=True)


# ======================================================================
# GET /api/tickers - Lista de tickers del universo
# ======================================================================
@app.route("/api/tickers", methods=["GET"])
def get_tickers():
    con = get_db()
    try:
        # Tickers seleccionados en el universo
        selected = con.execute("""
            SELECT ticker, avg_daily_volume, avg_dollar_volume, avg_atr_pct, avg_price, in_top50
            FROM universe
            ORDER BY avg_dollar_volume DESC
        """).fetchdf()
        
        # Todos los tickers con datos
        all_tickers = con.execute("""
            SELECT DISTINCT ticker FROM prices_1min ORDER BY ticker
        """).fetchdf()
        
        return jsonify({
            "universe": selected.to_dict(orient="records"),
            "all_tickers": all_tickers["ticker"].tolist(),
        })
    finally:
        con.close()


# ======================================================================
# GET /api/trades - Trades del backtest
# ======================================================================
@app.route("/api/trades", methods=["GET"])
def get_trades():
    con = get_db()
    try:
        # Filtros opcionales
        ticker = request.args.get("ticker")
        direction = request.args.get("direction")
        reason = request.args.get("reason")
        
        where_clauses = []
        if ticker:
            where_clauses.append(f"ticker = '{ticker}'")
        if direction:
            where_clauses.append(f"direction = '{direction.upper()}'")
        if reason:
            where_clauses.append(f"reason_exit = '{reason}'")
        
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        df = con.execute(f"""
            SELECT 
                trade_id, ticker, date, direction, 
                entry_time, entry_price, exit_time, exit_price,
                shares, pnl_gross, pnl_net, commission, slippage,
                orb_high, orb_low, stop_loss, reason_exit
            FROM bt_trades_orb
            {where_sql}
            ORDER BY entry_time
        """).fetchdf()
        
        # Convertir timestamps a strings para JSON
        for col in ["date", "entry_time", "exit_time"]:
            if col in df.columns:
                df[col] = df[col].astype(str)
        
        return jsonify({
            "trades": df.to_dict(orient="records"),
            "count": len(df),
        })
    finally:
        con.close()


# ======================================================================
# GET /api/metrics - Metricas globales del backtest
# ======================================================================
@app.route("/api/metrics", methods=["GET"])
def get_metrics():
    con = get_db()
    try:
        # Ultima ejecucion de metricas
        metrics = con.execute("""
            SELECT * FROM bt_metrics ORDER BY run_id DESC LIMIT 1
        """).fetchdf()
        
        if metrics.empty:
            return jsonify({"error": "No hay metricas. Ejecuta el backtest primero."}), 404
        
        row = metrics.iloc[0].to_dict()
        # Convertir timestamps
        for k, v in row.items():
            if hasattr(v, 'isoformat'):
                row[k] = str(v)
            elif isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = float(v)
        
        return jsonify(row)
    finally:
        con.close()


# ======================================================================
# GET /api/equity - Curva de equity
# ======================================================================
@app.route("/api/equity", methods=["GET"])
def get_equity():
    con = get_db()
    try:
        df = con.execute("""
            SELECT date, entry_time, pnl_net, ticker, direction, reason_exit
            FROM bt_trades_orb
            ORDER BY entry_time
        """).fetchdf()
        
        if df.empty:
            return jsonify({"equity": [], "drawdown": []})
        
        # Construir curva de equity
        equity = INITIAL_CAPITAL
        peak = equity
        equity_data = []
        dd_data = []
        
        for _, row in df.iterrows():
            equity += row["pnl_net"]
            peak = max(peak, equity)
            dd = (equity - peak) / peak * 100 if peak > 0 else 0
            
            equity_data.append({
                "date": str(row["date"]),
                "equity": round(equity, 2),
                "pnl": round(row["pnl_net"], 2),
                "ticker": row["ticker"],
            })
            dd_data.append({
                "date": str(row["date"]),
                "dd": round(dd, 2),
            })
        
        return jsonify({
            "equity": equity_data,
            "drawdown": dd_data,
            "initial_capital": INITIAL_CAPITAL,
            "final_capital": round(equity, 2),
        })
    finally:
        con.close()


# ======================================================================
# GET /api/monthly - P&L mensual
# ======================================================================
@app.route("/api/monthly", methods=["GET"])
def get_monthly():
    con = get_db()
    try:
        df = con.execute("""
            SELECT 
                STRFTIME(date, '%Y-%m') AS month,
                COUNT(*) AS trades,
                SUM(pnl_net) AS pnl,
                SUM(CASE WHEN pnl_net > 0 THEN 1 ELSE 0 END) AS wins,
                AVG(pnl_net) AS avg_pnl
            FROM bt_trades_orb
            GROUP BY STRFTIME(date, '%Y-%m')
            ORDER BY month
        """).fetchdf()
        
        df["pnl"] = df["pnl"].round(2)
        df["avg_pnl"] = df["avg_pnl"].round(2)
        df["wr"] = (df["wins"] / df["trades"] * 100).round(1)
        
        return jsonify({"monthly": df.to_dict(orient="records")})
    finally:
        con.close()


# ======================================================================
# GET /api/universe - Datos completos del universo
# ======================================================================
@app.route("/api/universe", methods=["GET"])
def get_universe():
    con = get_db()
    try:
        df = con.execute("""
            SELECT * FROM universe ORDER BY avg_dollar_volume DESC
        """).fetchdf()
        
        for col in df.columns:
            if df[col].dtype == 'datetime64[ns]':
                df[col] = df[col].astype(str)
        
        return jsonify({"universe": df.to_dict(orient="records")})
    finally:
        con.close()


# ======================================================================
# GET /api/stats/by_ticker - Desglose por ticker
# ======================================================================
@app.route("/api/stats/by_ticker", methods=["GET"])
def stats_by_ticker():
    con = get_db()
    try:
        df = con.execute("""
            SELECT 
                ticker,
                COUNT(*) AS trades,
                SUM(pnl_net) AS pnl,
                AVG(pnl_net) AS avg_pnl,
                SUM(CASE WHEN pnl_net > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl_net > 0 THEN pnl_net ELSE 0 END) AS gross_wins,
                SUM(CASE WHEN pnl_net <= 0 THEN pnl_net ELSE 0 END) AS gross_losses
            FROM bt_trades_orb
            GROUP BY ticker
            ORDER BY pnl DESC
        """).fetchdf()
        
        df["wr"] = (df["wins"] / df["trades"] * 100).round(1)
        df["pnl"] = df["pnl"].round(2)
        df["avg_pnl"] = df["avg_pnl"].round(2)
        df["pf"] = df.apply(
            lambda r: round(r["gross_wins"] / abs(r["gross_losses"]), 2) if r["gross_losses"] != 0 else 999, 
            axis=1
        )
        
        return jsonify({"by_ticker": df.to_dict(orient="records")})
    finally:
        con.close()


# ======================================================================
# GET /api/stats/by_reason - Desglose por razon de salida
# ======================================================================
@app.route("/api/stats/by_reason", methods=["GET"])
def stats_by_reason():
    con = get_db()
    try:
        df = con.execute("""
            SELECT 
                reason_exit AS reason,
                COUNT(*) AS count,
                SUM(pnl_net) AS pnl,
                AVG(pnl_net) AS avg_pnl
            FROM bt_trades_orb
            GROUP BY reason_exit
        """).fetchdf()
        
        df["pnl"] = df["pnl"].round(2)
        df["avg_pnl"] = df["avg_pnl"].round(2)
        
        return jsonify({"by_reason": df.to_dict(orient="records")})
    finally:
        con.close()


# ======================================================================
# GET /api/stats/by_direction - Desglose por direccion
# ======================================================================
@app.route("/api/stats/by_direction", methods=["GET"])
def stats_by_direction():
    con = get_db()
    try:
        df = con.execute("""
            SELECT 
                direction,
                COUNT(*) AS count,
                SUM(pnl_net) AS pnl,
                AVG(pnl_net) AS avg_pnl,
                SUM(CASE WHEN pnl_net > 0 THEN 1 ELSE 0 END) AS wins
            FROM bt_trades_orb
            GROUP BY direction
        """).fetchdf()
        
        df["wr"] = (df["wins"] / df["count"] * 100).round(1)
        df["pnl"] = df["pnl"].round(2)
        df["avg_pnl"] = df["avg_pnl"].round(2)
        
        return jsonify({"by_direction": df.to_dict(orient="records")})
    finally:
        con.close()


# ======================================================================
# GET /api/stats/by_dow - Desglose por dia de la semana
# ======================================================================
@app.route("/api/stats/by_dow", methods=["GET"])
def stats_by_dow():
    con = get_db()
    try:
        df = con.execute("""
            SELECT 
                DAYNAME(date) AS day,
                DAYOFWEEK(date) AS dow_num,
                COUNT(*) AS count,
                SUM(pnl_net) AS pnl,
                AVG(pnl_net) AS avg_pnl,
                SUM(CASE WHEN pnl_net > 0 THEN 1 ELSE 0 END) AS wins
            FROM bt_trades_orb
            GROUP BY DAYNAME(date), DAYOFWEEK(date)
            ORDER BY dow_num
        """).fetchdf()
        
        df["wr"] = (df["wins"] / df["count"] * 100).round(1)
        df["pnl"] = df["pnl"].round(2)
        df["avg_pnl"] = df["avg_pnl"].round(2)
        
        return jsonify({"by_dow": df.to_dict(orient="records")})
    finally:
        con.close()


# ======================================================================
# GET /api/stats/distribution - Distribucion de P&L
# ======================================================================
@app.route("/api/stats/distribution", methods=["GET"])
def stats_distribution():
    con = get_db()
    try:
        step = int(request.args.get("step", 20))
        
        df = con.execute(f"""
            SELECT 
                FLOOR(pnl_net / {step}) * {step} AS bucket,
                COUNT(*) AS count
            FROM bt_trades_orb
            GROUP BY bucket
            ORDER BY bucket
        """).fetchdf()
        
        df["bucket"] = df["bucket"].astype(int)
        
        return jsonify({"distribution": df.to_dict(orient="records")})
    finally:
        con.close()


# ======================================================================
# POST /api/backtest/run - Ejecutar backtest con parametros custom
# ======================================================================
@app.route("/api/backtest/run", methods=["POST"])
def run_backtest():
    data = request.get_json() or {}
    
    cmd = [sys.executable, "scripts/05_backtest_orb.py"]
    
    if "sl" in data:
        cmd.extend(["--sl", str(data["sl"])])
    if "tp" in data:
        cmd.extend(["--tp", str(data["tp"])])
    if "start" in data and data["start"]:
        cmd.extend(["--start", data["start"]])
    if "end" in data and data["end"]:
        cmd.extend(["--end", data["end"]])
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=600, cwd=_PROJECT_ROOT,
        )
        return jsonify({
            "status": "ok" if result.returncode == 0 else "error",
            "stdout": result.stdout[-3000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
            "returncode": result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "Timeout (>10 min)"}), 504
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ======================================================================
# POST /api/backtest/optimize - Optimizar SL x TP
# ======================================================================
@app.route("/api/backtest/optimize", methods=["POST"])
def run_optimize():
    data = request.get_json() or {}
    
    cmd = [sys.executable, "scripts/05_backtest_orb.py", "--optimize"]
    
    if "start" in data and data["start"]:
        cmd.extend(["--start", data["start"]])
    if "end" in data and data["end"]:
        cmd.extend(["--end", data["end"]])
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=3600, cwd=_PROJECT_ROOT,
        )
        return jsonify({
            "status": "ok" if result.returncode == 0 else "error",
            "stdout": result.stdout[-5000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
            "returncode": result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "Optimize timeout (>1h)"}), 504
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ======================================================================
# GET /api/health - Health check
# ======================================================================
@app.route("/api/health", methods=["GET"])
def health():
    try:
        con = get_db()
        count_1min = con.execute("SELECT COUNT(*) FROM prices_1min").fetchone()[0]
        count_trades = con.execute("SELECT COUNT(*) FROM bt_trades_orb").fetchone()[0]
        count_universe = con.execute("SELECT COUNT(*) FROM universe WHERE in_top50 = TRUE").fetchone()[0]
        con.close()
        
        return jsonify({
            "status": "ok",
            "db": str(DUCKDB_PATH),
            "prices_1min": count_1min,
            "bt_trades": count_trades,
            "universe_selected": count_universe,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ======================================================================
# MAIN
# ======================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("ORB Trading System -- API Server")
    print("=" * 60)
    print(f"Database: {DUCKDB_PATH}")
    print(f"URL:      http://localhost:5000")
    print(f"Docs:     http://localhost:5000/api/health")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=5000, debug=True)

import duckdb

con = duckdb.connect(r"C:\OBR\data\market_data.duckdb", read_only=True)

print("=== PRIMERAS 5 BARRAS DEL DIA ===")
r = con.execute("""
    SELECT ts, open, close, volume
    FROM prices_1min
    WHERE ticker = 'AAPL' AND CAST(ts AS DATE) = '2025-01-15'
    ORDER BY ts LIMIT 5
""").fetchdf()
print(r.to_string())

print()
print("=== ULTIMAS 5 BARRAS DEL DIA ===")
r2 = con.execute("""
    SELECT ts, open, close, volume
    FROM prices_1min
    WHERE ticker = 'AAPL' AND CAST(ts AS DATE) = '2025-01-15'
    ORDER BY ts DESC LIMIT 5
""").fetchdf()
print(r2.to_string())

con.close()

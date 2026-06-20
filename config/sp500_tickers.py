"""
============================================================================
Lista completa de tickers del S&P 500
============================================================================
Actualizada a marzo 2026. Incluye 503 tickers (algunas empresas tienen 
dos clases de acciones: GOOGL/GOOG, FOX/FOXA, NWS/NWSA).

Este archivo se usa como fuente para la descarga inicial de datos.
Después, el script de selección de universo filtrará a las top 50.
============================================================================
"""

SP500_TICKERS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE",
    "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM", "ALB", "ALGN", "ALK",
    "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP", "AMT", "AMZN",
    "ANET", "ANSS", "AON", "AOS", "APA", "APD", "APH", "APTV", "ARE", "ARES",
    "ATO", "ATVI", "AVB", "AVGO", "AVY", "AWK", "AXP", "AZO",
    "BA", "BAC", "BAX", "BBWI", "BBY", "BDX", "BEN", "BF.B", "BG", "BIIB",
    "BIO", "BK", "BKNG", "BKR", "BLDR", "BLK", "BMY", "BR", "BRK.B", "BRO",
    "BSX", "BWA", "BX", "BXP",
    "C", "CAG", "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE", "CCI", "CCL",
    "CDNS", "CDW", "CE", "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI",
    "CINF", "CL", "CLX", "CMA", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC",
    "CNP", "COF", "COO", "COP", "COR", "COST", "CPAY", "CPB", "CPRT", "CPT",
    "CRL", "CRM", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTLT", "CTRA",
    "CTSH", "CTVA", "CVS", "CVX",
    "D", "DAL", "DAY", "DD", "DE", "DECK", "DFS", "DG", "DGX", "DHI",
    "DHR", "DIS", "DISH", "DLR", "DLTR", "DOV", "DOW", "DPZ", "DRI", "DTE",
    "DUK", "DVA", "DVN",
    "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EIX", "EL", "EMN", "EMR",
    "ENPH", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ERIE", "ES", "ESS", "ETN",
    "ETR", "EVRG", "EW", "EXC", "EXPD", "EXPE", "EXR",
    "F", "FANG", "FAST", "FCNCA", "FCX", "FDS", "FDX", "FE", "FFIV", "FI",
    "FICO", "FIS", "FISV", "FITB", "FLT", "FMC", "FOX", "FOXA", "FRT",
    "FSLR", "FTNT", "FTV",
    "GD", "GDDY", "GE", "GEHC", "GEN", "GEV", "GILD", "GIS", "GL", "GLW",
    "GM", "GNRC", "GOOG", "GOOGL", "GPC", "GPN", "GRMN", "GS", "GWW",
    "HAL", "HAS", "HBAN", "HCA", "HD", "HOLX", "HON", "HPE", "HPQ", "HRL",
    "HSIC", "HST", "HSY", "HUBB", "HUM", "HWM", "HII",
    "IBM", "ICE", "IDXX", "IEX", "IFF", "ILMN", "INCY", "INTC", "INTU",
    "INVH", "IP", "IPG", "IQV", "IR", "IRM", "ISRG", "IT", "ITW",
    "J", "JBHT", "JBL", "JCI", "JKHY", "JNJ", "JNPR", "JPM",
    "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KLAC", "KMB", "KMI", "KMX",
    "KO", "KR",
    "L", "LDOS", "LEN", "LH", "LHX", "LIN", "LKQ", "LLY", "LMT", "LNT",
    "LOW", "LRCX", "LULU", "LUV", "LVS", "LW", "LYB", "LYV",
    "MA", "MAA", "MAR", "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT",
    "MET", "META", "MGM", "MHK", "MKC", "MKTX", "MLM", "MMC", "MMM", "MNST",
    "MO", "MOH", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MRO", "MS", "MSCI",
    "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU",
    "NCLH", "NDAQ", "NDSN", "NEE", "NEM", "NFLX", "NI", "NKE", "NOC",
    "NOW", "NRG", "NSC", "NTAP", "NTRS", "NUE", "NVDA", "NVR", "NWS", "NWSA",
    "NXPI",
    "O", "ODFL", "OGN", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY",
    "PANW", "PARA", "PAYC", "PAYX", "PCAR", "PCG", "PEG", "PEP", "PFE",
    "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD", "PLTR", "PM", "PNC",
    "PNR", "PNW", "PODD", "POOL", "PPG", "PPL", "PRU", "PSA", "PSX", "PTC",
    "PVH", "PWR", "PXD", "PYPL",
    "QCOM", "QRVO",
    "RCL", "REG", "REGN", "RF", "RHI", "RJF", "RL", "RMD", "ROK", "ROL",
    "ROP", "ROST", "RSG", "RTX",
    "SBAC", "SBUX", "SCHW", "SEE", "SHW", "SIVB", "SJM", "SLB", "SMCI",
    "SNA", "SNPS", "SO", "SOLV", "SPG", "SPGI", "SRE", "STE", "STLD",
    "STT", "STX", "STZ", "SWK", "SWKS", "SYF", "SYK", "SYY",
    "T", "TAP", "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TFX", "TGT",
    "TJX", "TMO", "TMUS", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO",
    "TSLA", "TSN", "TT", "TTWO", "TXN", "TXT", "TYL",
    "UDR", "UHS", "ULTA", "UNH", "UNP", "UPS", "URI", "USB",
    "V", "VICI", "VLO", "VLTO", "VMC", "VRSK", "VRSN", "VRTX", "VST",
    "VTR", "VTRS", "VZ",
    "WAB", "WAT", "WBA", "WBD", "WDC", "WEC", "WELL", "WFC", "WHR", "WM",
    "WMB", "WMT", "WRB", "WRK", "WST", "WTW", "WY", "WYNN",
    "XEL", "XOM", "XRAY", "XYL",
    "YUM",
    "ZBH", "ZBRA", "ZION", "ZTS",
]

# Tickers que han sido delisted o cambiaron — excluir de la descarga
EXCLUDED_TICKERS = [
    "ATVI",   # Adquirida por Microsoft (2023)
    "CTLT",   # Adquirida por Novo Nordisk (2024)
    "DISH",   # Fusionada con EchoStar
    "SIVB",   # Quiebra Silicon Valley Bank (2023)
    "PXD",    # Adquirida por Exxon (2024)
    "FRC",    # Quiebra First Republic (2023)
]

def get_active_sp500_tickers() -> list[str]:
    """Devuelve la lista de tickers activos del S&P 500."""
    return [t for t in SP500_TICKERS if t not in EXCLUDED_TICKERS]

def get_ticker_count() -> int:
    """Devuelve el número de tickers activos."""
    return len(get_active_sp500_tickers())

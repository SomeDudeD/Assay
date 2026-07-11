"""Stage 0 — download 2y daily candles + current spot for crypto. Store in assay.db."""
import sqlite3
import yfinance as yf

TICKERS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "AAPL", "NVDA", "TSLA", "MSFT"]
CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]
DB = "assay.db"


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            ticker TEXT NOT NULL,
            date   TEXT NOT NULL,
            open   REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    conn.commit()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def download_candles(conn):
    for t in TICKERS:
        print(f"Downloading {t} ...", flush=True)
        df = yf.download(t, period="2y", interval="1d", auto_adjust=False, progress=False)
        if df is None or df.empty:
            print(f"  !! no data for {t}")
            continue
        # yfinance can return a MultiIndex column frame for a single ticker
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        rows = 0
        for idx, r in df.iterrows():
            date = idx.strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO candles (ticker,date,open,high,low,close,volume) "
                "VALUES (?,?,?,?,?,?,?)",
                (t, date, _f(r.get("Open")), _f(r.get("High")), _f(r.get("Low")),
                 _f(r.get("Close")), _f(r.get("Volume"))),
            )
            rows += 1
        conn.commit()
        print(f"  {rows} candles stored")


def fetch_spot(t):
    """Try a 1m bar; fall back to daily close."""
    try:
        df = yf.download(t, period="1d", interval="1m", auto_adjust=False, progress=False)
        if df is not None and not df.empty:
            if df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)
            last = df.iloc[-1]
            return _f(last["Close"]), df.index[-1].strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        print(f"  (1m fetch failed for {t}: {e})")
    try:
        df = yf.download(t, period="5d", interval="1d", auto_adjust=False, progress=False)
        if df is not None and not df.empty:
            if df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)
            return _f(df["Close"].iloc[-1]), df.index[-1].strftime("%Y-%m-%d")
    except Exception:
        pass
    return None, None


def spot_prices(conn):
    """Most recent spot for each crypto ticker; store to a spot table for reuse."""
    conn.execute("CREATE TABLE IF NOT EXISTS spot (ticker TEXT PRIMARY KEY, price REAL, asof TEXT)")
    print("\n=== CURRENT SPOT PRICES (crypto) ===")
    for t in CRYPTO:
        price, asof = fetch_spot(t)
        if price is None:
            row = conn.execute(
                "SELECT date, close FROM candles WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)
            ).fetchone()
            if row:
                asof, price = row[0], row[1]
        conn.execute("INSERT OR REPLACE INTO spot (ticker,price,asof) VALUES (?,?,?)",
                     (t, price, asof))
        print(f"  {t:9s} {price:>14,.4f}   (asof {asof})")
    conn.commit()


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    init_db(conn)
    download_candles(conn)
    spot_prices(conn)
    n = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    print(f"\nTotal candles in assay.db: {n}")
    conn.close()

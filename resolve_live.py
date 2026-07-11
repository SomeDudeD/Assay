"""Stage 6 — resolve the 10 live questions to 1/0 using current prices. Idempotent + re-runnable.

Usage:  ./venv/bin/python resolve_live.py
Fetches the latest price for each crypto ticker, compares against the spot captured in
Stage 0 (stored in questions.json), writes outcomes to live_resolutions (INSERT OR REPLACE).
"""
import json
import sqlite3
from datetime import datetime, timezone

import yfinance as yf

DB = "assay.db"
CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_now(t):
    """Latest 1m close, falling back to latest daily close."""
    for period, interval in (("1d", "1m"), ("5d", "1d")):
        try:
            df = yf.download(t, period=period, interval=interval, auto_adjust=False, progress=False)
            if df is not None and not df.empty:
                if df.columns.nlevels > 1:
                    df.columns = df.columns.get_level_values(0)
                return _f(df["Close"].iloc[-1])
        except Exception:
            continue
    return None


def resolve(q, now, spot):
    """Return 1/0 for question q given current prices `now` and captured `spot` (both dicts)."""
    k = q["kind"]
    if k in ("above", "below", "within"):
        t = q["ticker"]
        cur, base = now[t], spot[t] if isinstance(spot, dict) else q["spot"]
        if k == "above":
            return 1 if cur > q["strike"] else 0
        if k == "below":
            return 1 if cur < q["strike"] else 0
        if k == "within":
            band = q["band"] * base
            return 1 if abs(cur - base) <= band else 0
    if k == "pct_gt":
        a, b = q["a"], q["b"]
        pa = now[a] / q["spot"][a] - 1
        pb = now[b] / q["spot"][b] - 1
        return 1 if pa > pb else 0
    if k == "any_move":
        thr = q["threshold"]
        moves = [abs(now[t] / q["spot"][t] - 1) for t in q["spot"]]
        return 1 if any(m > thr for m in moves) else 0
    if k == "all_same_dir":
        signs = [1 if now[t] > q["spot"][t] else (-1 if now[t] < q["spot"][t] else 0)
                 for t in q["spot"]]
        allup = all(s > 0 for s in signs)
        alldown = all(s < 0 for s in signs)
        return 1 if (allup or alldown) else 0
    raise ValueError(f"unknown kind {k}")


def main():
    with open("questions.json") as f:
        doc = json.load(f)
    questions = doc["questions"]

    print("Fetching current prices ...")
    now = {t: fetch_now(t) for t in CRYPTO}
    for t in CRYPTO:
        print(f"  {t:9s} now={now[t]}")
    if any(v is None for v in now.values()):
        print("!! missing a price — aborting so we don't write bad resolutions")
        return

    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS live_resolutions (
            question_id INTEGER PRIMARY KEY,
            outcome INTEGER NOT NULL,
            resolved_at TEXT NOT NULL,
            note TEXT
        )
    """)
    resolved_at = datetime.now(timezone.utc).isoformat()

    print("\n=== RESOLUTIONS ===")
    for q in questions:
        outcome = resolve(q, now, q.get("spot"))
        note = q["prompt"]
        conn.execute(
            "INSERT OR REPLACE INTO live_resolutions (question_id, outcome, resolved_at, note) "
            "VALUES (?,?,?,?)",
            (q["id"], outcome, resolved_at, note),
        )
        print(f"  Q{q['id']:2d} -> {outcome}   {note}")
    conn.commit()

    n = conn.execute("SELECT COUNT(*) FROM live_resolutions").fetchone()[0]
    conn.close()
    print(f"\n{n} live questions resolved. Scoring is computed on-demand by /results_data.")
    print("View: http://127.0.0.1:8000/results")


if __name__ == "__main__":
    main()

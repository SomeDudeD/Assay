"""Stage 1 — chart questions (rendered PNGs + ground truth) and live questions (questions.json)."""
import json
import os
import random
import sqlite3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DB = "assay.db"
CHART_DIR = "static/charts"
WINDOW = 60
SEED = 42
N_CHARTS = 10
TICKERS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "AAPL", "NVDA", "TSLA", "MSFT"]


def load_series(conn, ticker):
    rows = conn.execute(
        "SELECT date, close FROM candles WHERE ticker=? AND close IS NOT NULL ORDER BY date", (ticker,)
    ).fetchall()
    return rows  # list of (date, close)


def build_chart_questions(conn):
    os.makedirs(CHART_DIR, exist_ok=True)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chart_questions (
            question_id INTEGER PRIMARY KEY,
            ticker TEXT, start_date TEXT, end_date TEXT,
            last_close REAL, next_close REAL, ground_truth INTEGER
        )
    """)
    conn.execute("DELETE FROM chart_questions")

    rng = random.Random(SEED)
    series = {t: load_series(conn, t) for t in TICKERS}

    print("=== CHART QUESTIONS (fixed seed=%d) ===" % SEED)
    made = 0
    while made < N_CHARTS:
        t = rng.choice(TICKERS)
        s = series[t]
        # need WINDOW candles + 1 next candle to resolve
        if len(s) < WINDOW + 1:
            continue
        start = rng.randint(0, len(s) - WINDOW - 1)
        window = s[start:start + WINDOW]
        next_candle = s[start + WINDOW]
        closes = [c for _, c in window]
        last_close = closes[-1]
        next_close = next_candle[1]
        gt = 1 if next_close > last_close else 0
        qid = made + 1

        # render: shape only, no labels/ticks/legend
        fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
        ax.plot(range(WINDOW), closes, color="#1f77b4", linewidth=2)
        ax.axis("off")
        fig.tight_layout(pad=0.2)
        fig.savefig(os.path.join(CHART_DIR, f"q{qid}.png"), bbox_inches="tight")
        plt.close(fig)

        conn.execute(
            "INSERT INTO chart_questions VALUES (?,?,?,?,?,?,?)",
            (qid, t, window[0][0], window[-1][0], last_close, next_close, gt),
        )
        print(f"  q{qid}: {t:9s} {window[0][0]}..{window[-1][0]}  "
              f"last={last_close:,.2f} next={next_close:,.2f} -> gt={gt}")
        made += 1
    conn.commit()
    print(f"  {made} charts saved to {CHART_DIR}/q1.png..q{N_CHARTS}.png")


def build_live_questions(conn):
    spot = {t: p for t, p in conn.execute("SELECT ticker, price FROM spot").fetchall()}
    btc, eth, sol, xrp = spot["BTC-USD"], spot["ETH-USD"], spot["SOL-USD"], spot["XRP-USD"]

    # resolve_at: 5:00pm PT today. PT is UTC-7 in July (PDT) -> 00:00 UTC next day.
    resolve_at = "2026-07-11T17:00:00-07:00"

    questions = [
        {"id": 1,  "kind": "above",       "ticker": "BTC-USD", "spot": btc,
         "strike": round(btc * 1.004, 4),
         "prompt": f"Will BTC finish above ${btc * 1.004:,.2f} (spot +0.4%)?"},
        {"id": 2,  "kind": "below",       "ticker": "BTC-USD", "spot": btc,
         "strike": round(btc * 0.996, 4),
         "prompt": f"Will BTC finish below ${btc * 0.996:,.2f} (spot -0.4%)?"},
        {"id": 3,  "kind": "above",       "ticker": "ETH-USD", "spot": eth,
         "strike": round(eth * 1.005, 4),
         "prompt": f"Will ETH finish above ${eth * 1.005:,.2f} (spot +0.5%)?"},
        {"id": 4,  "kind": "above",       "ticker": "SOL-USD", "spot": sol,
         "strike": round(sol * 1.007, 4),
         "prompt": f"Will SOL finish above ${sol * 1.007:,.2f} (spot +0.7%)?"},
        {"id": 5,  "kind": "above",       "ticker": "XRP-USD", "spot": xrp,
         "strike": round(xrp * 1.006, 4),
         "prompt": f"Will XRP finish above ${xrp * 1.006:,.4f} (spot +0.6%)?"},
        {"id": 6,  "kind": "pct_gt",      "a": "ETH-USD", "b": "BTC-USD",
         "spot": {"ETH-USD": eth, "BTC-USD": btc},
         "prompt": "Will ETH's % change beat BTC's % change?"},
        {"id": 7,  "kind": "pct_gt",      "a": "SOL-USD", "b": "ETH-USD",
         "spot": {"SOL-USD": sol, "ETH-USD": eth},
         "prompt": "Will SOL's % change beat ETH's % change?"},
        {"id": 8,  "kind": "any_move",    "threshold": 0.015,
         "spot": {"BTC-USD": btc, "ETH-USD": eth, "SOL-USD": sol, "XRP-USD": xrp},
         "prompt": "Will any of the four (BTC/ETH/SOL/XRP) move more than 1.5% either direction?"},
        {"id": 9,  "kind": "within",      "ticker": "BTC-USD", "spot": btc,
         "band": 0.0025,
         "prompt": f"Will BTC finish within ±0.25% of ${btc:,.2f}?"},
        {"id": 10, "kind": "all_same_dir",
         "spot": {"BTC-USD": btc, "ETH-USD": eth, "SOL-USD": sol, "XRP-USD": xrp},
         "prompt": "Will all four (BTC/ETH/SOL/XRP) move the same direction?"},
    ]

    doc = {"resolve_at": resolve_at, "questions": questions}
    with open("questions.json", "w") as f:
        json.dump(doc, f, indent=2)

    print("\n=== LIVE QUESTIONS (resolve %s) ===" % resolve_at)
    print(f"  spot: BTC={btc:,.2f}  ETH={eth:,.2f}  SOL={sol:,.2f}  XRP={xrp:,.4f}")
    for q in questions:
        strike = q.get("strike")
        extra = ""
        if strike is not None:
            extra = f"  strike={strike:,.4f}"
        elif q["kind"] == "within":
            lo, hi = btc * (1 - q["band"]), btc * (1 + q["band"])
            extra = f"  band=[{lo:,.2f}, {hi:,.2f}]"
        elif q["kind"] == "any_move":
            extra = f"  threshold={q['threshold']*100:.1f}%"
        print(f"  Q{q['id']:2d} [{q['kind']:12s}] {q['prompt']}{extra}")


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    build_chart_questions(conn)
    build_live_questions(conn)
    conn.close()

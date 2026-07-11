"""Assay — capture app + API. Run: ./venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000"""
import json
import os
import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import scoring

DB = "assay.db"
CHART_PROMPT = "What is the probability this asset is higher 24 hours later?"

app = FastAPI(title="Assay")
app.mount("/static", StaticFiles(directory="static"), name="static")


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            handle TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            question_type TEXT NOT NULL,
            probability REAL NOT NULL,
            submitted_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init()


def load_questions():
    """20 questions: 10 chart (image + fixed prompt) then 10 live."""
    out = []
    conn = db()
    charts = conn.execute("SELECT question_id FROM chart_questions ORDER BY question_id").fetchall()
    conn.close()
    for r in charts:
        qid = r["question_id"]
        out.append({
            "type": "chart",
            "id": qid,
            "image": f"/static/charts/q{qid}.png",
            "prompt": CHART_PROMPT,
        })
    if os.path.exists("questions.json"):
        with open("questions.json") as f:
            live = json.load(f)
        for q in live["questions"]:
            out.append({"type": "live", "id": q["id"], "image": None, "prompt": q["prompt"]})
    return out


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/questions")
def questions():
    return {"questions": load_questions()}


def unique_handle(conn, handle):
    """If handle already submitted, append -2, -3, ... so we never error on dupes."""
    handle = (handle or "").strip() or "anon"
    existing = {r["handle"] for r in conn.execute("SELECT DISTINCT handle FROM forecasts").fetchall()}
    if handle not in existing:
        return handle
    i = 2
    while f"{handle}-{i}" in existing:
        i += 1
    return f"{handle}-{i}"


@app.post("/forecast")
async def forecast(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad json"}, status_code=400)

    raw_handle = body.get("handle", "")
    answers = body.get("answers", [])
    if not isinstance(answers, list) or not answers:
        return JSONResponse({"error": "no answers"}, status_code=400)

    conn = db()
    handle = unique_handle(conn, raw_handle)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for a in answers:
        try:
            qtype = a["type"]
            qid = int(a["id"])
            p = float(a["probability"])
        except (KeyError, TypeError, ValueError):
            continue
        p = max(0.0, min(1.0, p))  # store probability as 0..1
        conn.execute(
            "INSERT INTO forecasts (handle, question_id, question_type, probability, submitted_at) "
            "VALUES (?,?,?,?,?)",
            (handle, qid, qtype, p, now),
        )
        written += 1
    conn.commit()
    conn.close()
    return {"ok": True, "handle": handle, "written": written}


# ---------- Stage 3: reputation ----------
@app.get("/reputation/{handle}")
def reputation(handle: str):
    conn = db()
    try:
        return scoring.reputation(conn, handle)
    finally:
        conn.close()


# ---------- Stage 4: aggregation ----------
@app.get("/aggregate/{question_id}")
def aggregate(question_id: int, type: str = "live"):
    conn = db()
    try:
        w_abs = scoring.weights_map(conn)
        w_rel = scoring.weights_softmax(conn)
        a_abs = scoring.aggregate(conn, type, question_id, w_abs)
        a_rel = scoring.aggregate(conn, type, question_id, w_rel)
        return {
            "naive": a_abs["naive"],
            "weighted_absolute": a_abs["weighted"],
            "weighted_relative": a_rel["weighted"],
            "n": a_abs["n"],
            "outcome": a_abs.get("outcome"),
        }
    finally:
        conn.close()


@app.get("/results_data")
def results_data():
    """naive vs absolute-weighted vs relative-weighted crowd brier: live questions + holdout."""
    conn = db()
    try:
        live = scoring.results_multi(conn, "live", list(range(1, 11)))
        hold = scoring.holdout(conn)
        return {"live": live, "holdout": hold,
                "softmax_T": scoring.SOFTMAX_T,
                "n_forecasters": len(scoring.all_handles(conn))}
    finally:
        conn.close()


# ---------- Stage 5: leaderboard ----------
@app.get("/leaderboard_data")
def leaderboard_data():
    conn = db()
    try:
        rows = []
        for h in scoring.all_handles(conn):
            rep = scoring.reputation(conn, h)
            if rep["n"] == 0:
                continue
            rows.append({"handle": h, "brier": rep["brier"],
                         "skill": rep["skill"], "weight": rep["weight"], "n": rep["n"]})
        rows.sort(key=lambda r: r["brier"])  # lower brier = better
        return {"leaderboard": rows}
    finally:
        conn.close()


@app.get("/results")
def results_page():
    return FileResponse("static/results.html")


@app.get("/leaderboard")
def leaderboard_page():
    return FileResponse("static/leaderboard.html")

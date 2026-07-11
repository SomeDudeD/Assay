"""Shared scoring / reputation / aggregation logic (Stages 3-4). Pure reads on assay.db."""
import math
import sqlite3

DB = "assay.db"
SOFTMAX_T = 0.05  # temperature for the relative/softmax weighting scheme


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def chart_truth(conn):
    """{chart_question_id: outcome 0/1} from stored ground truth."""
    return {r["question_id"]: r["ground_truth"]
            for r in conn.execute("SELECT question_id, ground_truth FROM chart_questions")}


def live_outcomes(conn):
    """{live_question_id: outcome 0/1} for resolved live questions (empty until resolver runs)."""
    try:
        return {r["question_id"]: r["outcome"]
                for r in conn.execute("SELECT question_id, outcome FROM live_resolutions")}
    except sqlite3.OperationalError:
        return {}


def all_handles(conn):
    return [r["handle"] for r in
            conn.execute("SELECT DISTINCT handle FROM forecasts ORDER BY handle")]


def handle_chart_forecasts(conn, handle):
    """{chart_question_id: probability} — latest wins if duplicated."""
    out = {}
    for r in conn.execute(
        "SELECT question_id, probability FROM forecasts "
        "WHERE handle=? AND question_type='chart' ORDER BY id", (handle,)
    ):
        out[r["question_id"]] = r["probability"]
    return out


def _brier(pairs):
    if not pairs:
        return None
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def reputation(conn, handle, ids=None):
    """Stage 3. brier / skill / weight over chart questions (optionally a subset `ids`)."""
    truth = chart_truth(conn)
    fc = handle_chart_forecasts(conn, handle)
    qids = [q for q in fc if q in truth]
    if ids is not None:
        qids = [q for q in qids if q in ids]

    pairs = [(fc[q], truth[q]) for q in qids]
    baseline_pairs = [(0.5, truth[q]) for q in qids]
    brier = _brier(pairs)
    baseline = _brier(baseline_pairs)
    if brier is None or not baseline:
        skill = 0.0
    else:
        skill = 1.0 - (brier / baseline)
    weight = max(0.0, skill)

    return {
        "handle": handle,
        "n": len(pairs),
        "brier": brier,
        "baseline_brier": baseline,
        "skill": skill,
        "weight": weight,
        "calibration_curve": calibration_curve(pairs),
    }


def calibration_curve(pairs):
    """Bucket forecasts by decile -> [{bucket, mean_forecast, realized_frequency, count}] x10."""
    buckets = [[] for _ in range(10)]
    for p, o in pairs:
        idx = min(9, int(p * 10))
        buckets[idx].append((p, o))
    curve = []
    for i, b in enumerate(buckets):
        if b:
            mf = sum(p for p, _ in b) / len(b)
            rf = sum(o for _, o in b) / len(b)
        else:
            mf = rf = None
        curve.append({
            "bucket": f"{i*10}-{i*10+10}%",
            "mean_forecast": mf,
            "realized_frequency": rf,
            "count": len(b),
        })
    return curve


def weights_map(conn, ids=None):
    """Absolute scheme. {handle: weight} = max(0, skill) on chart questions (subset `ids`).

    Degenerate (all-zero) when no forecaster beats the 0.5 baseline.
    """
    return {h: reputation(conn, h, ids=ids)["weight"] for h in all_handles(conn)}


def weights_softmax(conn, ids=None, T=SOFTMAX_T):
    """Relative scheme. weight_i = exp(-brier_i / T), normalized to sum to 1.

    Always well-defined: every forecaster with any scored chart question gets positive
    weight, sharply concentrated on the lowest-brier forecasters. Never degenerate.
    """
    briers = {}
    for h in all_handles(conn):
        rep = reputation(conn, h, ids=ids)
        if rep["brier"] is not None:
            briers[h] = rep["brier"]
    raw = {h: math.exp(-b / T) for h, b in briers.items()}
    s = sum(raw.values())
    if s <= 0:
        return {h: 0.0 for h in raw}
    return {h: v / s for h, v in raw.items()}


def results_multi(conn, qtype, qids, ids_for_weights=None):
    """naive + absolute-weighted + relative-weighted crowd Brier across resolved `qids`.

    Weights are trained on the chart questions in `ids_for_weights` (None = all 10).
    """
    w_abs = weights_map(conn, ids=ids_for_weights)
    w_rel = weights_softmax(conn, ids=ids_for_weights)
    truth = live_outcomes(conn) if qtype == "live" else chart_truth(conn)

    naive_pairs, abs_pairs, rel_pairs, detail = [], [], [], []
    for qid in qids:
        if qid not in truth:
            continue
        a_abs = aggregate(conn, qtype, qid, w_abs)
        if a_abs["naive"] is None:
            continue
        a_rel = aggregate(conn, qtype, qid, w_rel)
        o = truth[qid]
        naive_pairs.append((a_abs["naive"], o))
        abs_pairs.append((a_abs["weighted"], o))
        rel_pairs.append((a_rel["weighted"], o))
        detail.append({"question_id": qid, "outcome": o,
                       "naive": a_abs["naive"],
                       "absolute": a_abs["weighted"],
                       "relative": a_rel["weighted"]})
    return {
        "naive_brier": _brier(naive_pairs),
        "absolute_brier": _brier(abs_pairs),
        "relative_brier": _brier(rel_pairs),
        "n": len(naive_pairs),
        "detail": detail,
        "absolute_degenerate": (sum(w_abs.values()) <= 0),
    }


def aggregate(conn, qtype, qid, weights=None):
    """Stage 4. naive + calibration-weighted crowd forecast for one question."""
    rows = conn.execute(
        "SELECT handle, probability FROM forecasts WHERE question_type=? AND question_id=?",
        (qtype, qid),
    ).fetchall()
    if not rows:
        return {"naive": None, "weighted": None, "n": 0}
    if weights is None:
        weights = weights_map(conn)

    ps = [r["probability"] for r in rows]
    naive = sum(ps) / len(ps)
    num = sum(weights.get(r["handle"], 0.0) * r["probability"] for r in rows)
    den = sum(weights.get(r["handle"], 0.0) for r in rows)
    weighted = (num / den) if den > 0 else naive

    truth = live_outcomes(conn) if qtype == "live" else chart_truth(conn)
    return {"naive": naive, "weighted": weighted, "n": len(rows),
            "outcome": truth.get(qid)}


def crowd_briers(conn, qtype, qids, weights):
    """naive vs weighted crowd brier across resolved questions in `qids`."""
    truth = live_outcomes(conn) if qtype == "live" else chart_truth(conn)
    naive_pairs, weighted_pairs, detail = [], [], []
    for qid in qids:
        if qid not in truth:
            continue
        agg = aggregate(conn, qtype, qid, weights)
        if agg["naive"] is None:
            continue
        o = truth[qid]
        naive_pairs.append((agg["naive"], o))
        weighted_pairs.append((agg["weighted"], o))
        detail.append({"question_id": qid, "outcome": o,
                       "naive": agg["naive"], "weighted": agg["weighted"]})
    return {
        "naive_brier": _brier(naive_pairs),
        "weighted_brier": _brier(weighted_pairs),
        "n": len(naive_pairs),
        "detail": detail,
    }


def holdout(conn, train_ids=(1, 2, 3, 4, 5), test_ids=(6, 7, 8, 9, 10)):
    """Stage 4 fallback. Train weights on `train_ids` charts, score all three schemes on `test_ids`."""
    res = results_multi(conn, "chart", list(test_ids), ids_for_weights=set(train_ids))
    res["train_ids"] = list(train_ids)
    res["test_ids"] = list(test_ids)
    return res

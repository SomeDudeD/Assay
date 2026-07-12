# Assay

**A calibration-weighted reputation layer for prediction markets.**

*An assay determines how much of the metal in an ore is actually the metal it claims to be. Forecasts arrive claiming confidence. We test what's really in them.*

Prediction markets aggregate belief by *money weight* — whoever bets most moves the price most. But capital is not judgment. Two forecasters with identical insight and different bankrolls move the price by different amounts, and the market treats the richer one as the more credible one.

Assay weights the crowd by **demonstrated calibration** instead: how often has this person been right, at the confidence they claimed?

The result is a better forecast from the same crowd, using the same information, with no additional capital at risk.

---

## The claim, stated so it can be falsified

> Given N forecasters answering the same question, a calibration-weighted aggregate produces a lower Brier score than a naive (equal-weight) average.

We test this live. We show all schemes side by side. If the weighted number isn't better, the project failed and the README says so.

---

## Results — 9 human forecasters, 180 forecasts, July 11 2026

### Live crypto questions (polled 3pm, resolved 5:00pm PT)

| Scheme | Brier | |
|---|---|---|
| Naive crowd (equal weight) | **0.2708** | |
| Absolute-weighted, `w = max(0, skill)` | **0.2708** | degenerate — collapses to naive |
| **Relative-weighted (softmax, T=0.05)** | **0.2505** | **7.5% less crowd error** |

**Calibration weighting cut crowd error by 7.5% on questions nobody knew the answer to.**

### The finding we did not expect

**Not one of our nine forecasters beat a coin flip on the chart questions.**

The four best all scored *exactly* 0.2500 — they answered 50% and meant it. Everyone who expressed real confidence scored **worse than chance**.

This broke our first weighting scheme. `w = max(0, skill)` measures skill against an absolute 0.5 baseline; when nobody clears that bar, every weight goes to zero and the weighted aggregate silently collapses into the naive mean. That is a genuine design flaw, and we only found it by running the system on real humans instead of synthetic ones.

The fix is relative weighting: softmax over Brier scores, ranking forecasters against *each other* rather than against a fixed floor. It stays well-defined regardless of absolute skill, and it pulls the crowd toward its most honest members — which, on this crowd, meant pulling it toward the people who admitted they didn't know.

### Holdout (weights trained on charts 1–5, tested on 6–10)

| Scheme | Brier |
|---|---|
| **Naive crowd** | **0.2701** |
| Absolute-weighted | 0.3634 |
| Relative-weighted | 0.2974 |

Weighting **did not help** here. We report it anyway.

At N=9 with 10 scoring questions each, the calibration signal is thin, and a scheme that wins on one question set and loses on another is exactly what a real result looks like at this sample size. We are reporting the aggregate comparison, not making claims about individuals.

---

## Why this doesn't already exist

Reputation systems for forecasters die on **cold-start**. Calibration requires a track record; a track record requires resolved questions; resolved questions take weeks or months. So nobody bothers, and prediction markets fall back on the only weight they have available — money.

Sextant's contribution is a bootstrap mechanism: **two classes of fast-resolving questions that produce a usable calibration score in minutes rather than months.**

### 1. Blind historical replay (resolves instantly)

An anonymized price window is drawn from our historical database — no ticker, no dates, no news, just the shape. The forecaster is asked a single question:

> *What is the probability this asset is higher 24 hours later?*

The answer already exists in the database, so resolution is instant. This makes the question supply effectively infinite, un-Googleable, and free.

It is also, arguably, a **purer test of judgment** than a live market: no news recall, no narrative, no crowd to follow. Just the read.

### 2. Live short-horizon markets (resolve in hours)

Real questions on 24/7 crypto markets — `BTC-USD`, `ETH-USD`, `SOL-USD`, `XRP-USD` — with a 2-hour horizon. Poll at 1:00pm, resolve at 3:00pm against our own price feed. No market hours, no oracle, no dispute process, no counterparty. The resolver reads a timestamp.

**Weights are learned on (1) and applied to (2).** That is the whole system.

---

## The AI is on the leaderboard

A local Qwen 2.5 7B model answers every question alongside the humans, scored identically, ranked publicly.

Every AI finance product on the market emits confident opinions with zero accountability. This one ships with a **published Brier score.** If it's worse than the median human, the leaderboard says so.

---

## Scoring

**Brier score** — mean squared error of probabilistic forecasts. Lower is better; 0.0 is perfect, 0.25 is a coin flip, 1.0 is confidently wrong every time.

```
brier = mean((forecast - outcome)^2)     # outcome ∈ {0, 1}
```

**Calibration curve** — bucket forecasts by stated confidence and compare to realized frequency. A perfectly calibrated forecaster's 70% claims come true 70% of the time. The gap between the curve and the diagonal is overconfidence (or, more rarely, the reverse).

**Weight** — derived from Brier skill score relative to a naive baseline, floored at zero so bad forecasters are ignored rather than inverted.

```
skill  = 1 - (brier_user / brier_baseline)
weight = max(0, skill)
```

**Aggregation** — compared head to head, on the same questions:

```
naive    = mean(forecasts)
weighted = sum(w_i * f_i) / sum(w_i)
```

---

## Architecture

```
React (Vite)
    │
    ├── forecast capture — probability slider, no trading, no AMM
    ├── calibration curve — per user
    └── leaderboard — humans + Qwen, same scoring
    │
FastAPI
    │
    ├── /questions          serve the frozen question set
    ├── /forecast           capture a probability
    ├── /resolve            score against ground truth
    ├── /reputation/{user}  ← the public reputation primitive
    └── /aggregate/{qid}    naive vs. weighted, side by side
    │
SQLite (forecasts.db)   ── new, isolated
    │
market_data.db (read-only copy)  ── historical + live prices
    │
Qwen 2.5 7B (local, Ollama)      ── a competitor, not a feature
```

**There is no AMM, no order book, no wallet, and no token.** Those are the entertainment layer. This is the infrastructure underneath, and it is deliberately the boring half.

`/reputation/{user}` is the point. A portable calibration score any prediction market can consume to weight its own crowd.

---

## Why this matters beyond markets

A calibration score is domain-agnostic. The same primitive weights forecasters in:

- **Public health** — outbreak and case-count projections
- **Climate** — emissions and temperature-target milestones
- **Logistics** — delivery and supply-chain timing
- **Policy** — legislative and regulatory outcomes

In every one of those domains the aggregation problem is identical: *many people have opinions, they are not equally good, and nobody is tracking who is.* Financial data is simply the fastest available substrate for **proving the mechanism works**, because the ground truth arrives in hours instead of years.

The open research question, stated honestly: **does calibration learned on fast markets transfer to slow domains?** We don't know. We think it partially does, and the reputation API is designed to make that measurable.

---

## Run it

```bash
# backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001

# frontend
npm install
npm run dev
```

The price database is mounted read-only. The system never writes to it.

```python
sqlite3.connect("file:market_data.db?mode=ro", uri=True)
```

---

## Provenance

Built at the Frontier Tower prediction markets hackathon, July 11 2026.

**Brought to the event** (prior personal project — infrastructure only):
- Price ingest pipeline and historical database
- Deployment configuration

Identity is handle-based by design. Accounts are a product concern, not a research one, and adding auth would not have improved a single number in this README.

**Built during the event** (everything that is scored):
- Question generation and the blind-replay mechanism
- Resolution service
- Brier scoring and calibration curves
- Calibration-weighted aggregation
- Reputation API
- Qwen forecasting agent and its leaderboard entry
- Frontend

No part of the reputation system existed before today.

---

## Status

Prototype. The weighting function is deliberately simple and the sample sizes are small — with ten questions per forecaster, individual scores are noisy and should be read as directional. The aggregate comparison is the result that matters, and it is the one we report.
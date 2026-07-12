# Assay

**A measurement layer for judgment.**

*An assay determines how much of the metal in an ore is actually the metal it claims to be. Forecasts arrive claiming confidence. We test what's really in them.*

---

## Nobody keeps score of judgment

Reality does — eventually. But its scorecard has two problems.

**It arrives late.** The trader learns he was overconfident *after* he loses the money. The doctor learns *after* the misdiagnoses. The team learns the project was never shipping in March *in April*. You pay tuition for the lesson.

**And it's contaminated.** A winning year mixes skill, luck, position size, and a rising market. Three of those aren't judgment. P&L cannot tell you which one you had.

Prediction markets don't fix this — they aggregate belief by **money weight**. Whoever bets most moves the price most, so the market treats the richer forecaster as the more credible one. Rich is not the same as right.

Assay measures the thing directly: **when you say you're 70% sure, are you right 70% of the time?**

No money, so no position size to muddy it. Enough questions, so no luck. Just the read.

---

## What this is — and what it isn't

**It is not a predictive model.** It forecasts nothing. It has no opinion about where any price goes.

**It is not a market.** Nobody bets. There is no price, no odds, no counterparty, no money.

**It is a measurement layer.** It scores forecasts that *other people* make, and hands back a number saying how much each person's opinion is worth.

| Role | Who does it |
|---|---|
| Makes predictions | People |
| Aggregates predictions into a price | Polymarket, Kalshi, a room full of analysts |
| **Measures what each prediction is worth** | **Assay** |

It sits *underneath* a market — or underneath a trading desk, a hospital, an intelligence shop, or any group where people give confidence-weighted opinions and someone has to decide who to believe.

---

## The claim, stated so it can be falsified

> Given N forecasters answering the same question, a calibration-weighted aggregate produces a lower Brier score than a naive (equal-weight) average.

We tested it on real people, today. All schemes are shown side by side. Where weighting failed, the README says so.

---

## Results — 9 human forecasters, 180 forecasts, July 11 2026

### Live crypto questions (polled ~3pm, resolved 5:00pm PT)

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

The fix is relative weighting: a softmax over Brier scores, ranking forecasters against *each other* rather than against a fixed floor. It stays well-defined regardless of absolute skill, and it pulls the crowd toward its most honest members — which, on this crowd, meant pulling it toward the people who admitted they didn't know.

### Holdout (weights trained on charts 1–5, tested on 6–10)

| Scheme | Brier |
|---|---|
| **Naive crowd** | **0.2701** |
| Absolute-weighted | 0.3634 |
| Relative-weighted | 0.2974 |

Weighting **did not help** here. We report it anyway.

At N=9 with 10 scoring questions each, the calibration signal is thin. A scheme that wins on one question set and loses on another is what an honest result looks like at this sample size. We report the aggregate comparison and make no claims about individuals.

---

## Why this doesn't already exist

Reputation systems for forecasters die on **cold-start**. Calibration requires a track record; a track record requires resolved questions; resolved questions take weeks or months. So nobody bothers, and prediction markets fall back on the only weight they have available — money.

Assay's contribution is a bootstrap mechanism: **two classes of fast-resolving questions that produce a usable calibration score in minutes rather than months.**

### 1. Blind historical replay (resolves instantly) — this is what earns the weight

An anonymized price window (60 daily candles) is drawn from our database — no ticker, no dates, no axis labels, just the shape. The forecaster is asked one question:

> *What is the probability this asset is higher 24 hours later?*

The answer already exists in the database, so **resolution is instant**. The question supply is effectively infinite, un-Googleable, and free.

It is also, arguably, a **purer test of judgment** than a live market: no news recall, no narrative, no crowd to follow. Just the read.

### 2. Live short-horizon markets (resolve in hours) — this is what tests the weight

Ten real questions on 24/7 crypto markets — `BTC-USD`, `ETH-USD`, `SOL-USD`, `XRP-USD`. Strikes are set from spot at poll time, tuned so the honest answer is near 50/50. No market hours, no oracle, no dispute process, no counterparty: the resolver reads a price at a timestamp.

**Weights are learned on (1) and applied to (2).** That is the whole system.

---

## Scoring

**Brier score** — mean squared error of a probabilistic forecast. Lower is better. 0.0 is perfect, **0.25 is a coin flip**, 1.0 is confidently wrong every time. The square is what makes it work: confident wrongness is punished far harder than cautious wrongness, so you cannot game it by shouting.

```
brier = mean((forecast - outcome)^2)          # outcome ∈ {0, 1}
```

**Calibration curve** — bucket forecasts by stated confidence, compare to realized frequency. A calibrated forecaster's 70% claims come true 70% of the time. The gap from the diagonal is overconfidence.

**Two weighting schemes, both reported.**

*Absolute* — skill against a fixed 0.5 baseline, floored at zero:

```
skill  = 1 - (brier_user / brier_baseline)
weight = max(0, skill)
```

This is degenerate on a crowd where nobody beats the baseline. Ours was such a crowd.

*Relative (softmax)* — ranks forecasters against each other, so it stays well-defined regardless of absolute skill:

```
weight_i = exp(-brier_i / T)     # T = 0.05, then normalized
```

**Aggregation** — compared head to head on the same questions:

```
naive    = mean(forecasts)
weighted = sum(w_i * f_i) / sum(w_i)
```

---

## Architecture

```
Plain HTML/JS  (static/index.html — no build step, mobile-first)
    │
    ├── capture: 20 probability sliders, no trading, no betting
    ├── /leaderboard : humans ranked by Brier
    └── /results     : naive vs. absolute vs. relative, side by side
    │
FastAPI  (app.py)
    │
    ├── GET  /questions          the frozen question set
    ├── POST /forecast           capture a probability
    ├── GET  /reputation/{handle}  ← the public reputation primitive
    ├── GET  /aggregate/{qid}    naive vs. weighted for one question
    └── GET  /results_data       all three schemes, both question sets
    │
SQLite  (assay.db)
    ├── candles           2y daily OHLC, 8 tickers, via yfinance
    ├── chart_questions   10 blind windows + ground truth
    ├── forecasts         handle, question, probability
    └── live_resolutions  outcomes at 5:00pm
```

**We did not build the betting engine** — no odds pricing, no trading, no wallets, no tokens. Everyone builds that. `/reputation/{handle}` is the point: a portable calibration score any prediction market can consume to weight its own crowd.

Identity is handle-based by design. Accounts are a product concern, not a research one, and auth would not have improved a single number in this README.

---

## Why this matters beyond markets

A calibration score is domain-agnostic. The same primitive weights forecasters in:

- **Public health** — outbreak and case-count projections
- **Climate** — emissions and temperature-target milestones
- **Logistics** — delivery and supply-chain timing
- **Policy** — legislative and regulatory outcomes

In every one of those the aggregation problem is identical: *many people have opinions, they are not equally good, and nobody is tracking who is.* Financial data is simply the fastest available substrate for **proving the mechanism works**, because ground truth arrives in hours instead of years.

The open research question, stated honestly: **does calibration learned on fast markets transfer to slow domains?** We don't know. The reputation API is designed to make that measurable.

---

## Run it

```bash
python3 -m venv venv && source venv/bin/activate
pip install fastapi uvicorn matplotlib pandas yfinance python-multipart

python stage0_data.py        # download 2y candles -> assay.db
python stage1_questions.py   # generate 10 blind charts + 10 live questions
uvicorn app:app --host 0.0.0.0 --port 8000
```

Then:
- `http://localhost:8000/` — capture app
- `http://localhost:8000/leaderboard` — Brier ranking
- `http://localhost:8000/results` — naive vs. weighted

To resolve the live questions after their deadline:

```bash
python resolve_live.py       # idempotent, re-runnable
```

---

## Provenance

Built at the Frontier Tower prediction markets hackathon, **July 11 2026**, in roughly three hours.

**Built during the event — all of it:**
- Data pipeline (`stage0_data.py`) — yfinance ingest into a fresh SQLite database
- Question generation and the blind-replay mechanism (`stage1_questions.py`)
- Capture app (`static/index.html`)
- API and resolution service (`app.py`, `resolve_live.py`)
- Brier scoring, calibration curves, both weighting schemes, aggregation (`scoring.py`)
- Live human crowd: 9 forecasters, 180 forecasts

**Brought to the event:** deployment know-how from a prior personal project. No code.

No part of this system existed before today.

---

## Status and known limitations

Prototype. Stated plainly:

- **N=9, ten scoring questions each.** Individual Brier scores are noisy and should be read as directional, not definitive. The aggregate comparison is the result we report.
- **Absolute weighting is degenerate** on a crowd where nobody beats the baseline. That is a real design flaw, discovered by running on real humans.
- **Relative weighting beat naive on the live questions and lost on the holdout.** Mixed, and reported as such.
- **Ground truth on the chart set is 3 up / 7 down**, so a reflexively bearish forecaster is rewarded by the imbalance alone. A larger, balanced question set is the first thing to fix.
- **The crowd's first submissions were lost** to a `DELETE` in a test script mid-build. The data reported here is from a re-collected crowd.

### Next

- More questions per forecaster — ten is too few to separate skill from luck
- A balanced, non-financial question set, to test whether calibration transfers across domains
- An LLM on the leaderboard, scored identically, with a **published Brier score**. Every AI finance product emits confident opinions with zero accountability; this one would ship with a track record. *(Designed, not built — cut for time.)*

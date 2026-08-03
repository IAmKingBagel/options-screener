# Options Screener

A personal options screener that ranks defined-risk option strategies using volatility regime, expected value, liquidity quality, and Greek risk. Built for swing-duration screening (14–60 DTE), not intraday execution.

📄 **[Technical writeup](docs/paper.md)** ([PDF version](docs/options-screener-paper.pdf)) — design rationale, scoring specification, and testing approach.

> **Not financial advice.** This is a research tool. It ranks and explains candidates under stated modeling assumptions. It does not predict outcomes and has not yet been validated against historical data.

---

## What it does

Given a watchlist, the screener runs each symbol through a fixed pipeline:

1. **Liquidity gate** — rejects contracts that cannot realistically be traded (no bid, inverted quotes, spreads wider than 15% of mid, stale quotes, insufficient open interest + volume).
2. **Volatility read** — computes realized volatility over 10/20/60-day windows, blends them into a forecast, and compares that forecast against implied volatility to estimate a variance risk premium.
3. **Strategy construction** — builds bull put spreads, bear call spreads, bull call debit spreads, bear put debit spreads, and iron condors from the surviving contracts, selecting legs by delta target.
4. **Expected value** — evaluates each candidate across a grid of terminal prices spanning ±4σ, assigning each an exact payoff and a lognormal probability. Computed twice: once under the forecast realized volatility (physical) and once under implied volatility (risk-neutral).
5. **Greek overlay** — aggregates Greeks across legs and scores risk shape rather than raw magnitude.
6. **Composite score** — combines the above with profile-specific weights, subtracts risk penalties, and assigns a letter grade plus a written explanation.

Every candidate carries its own score breakdown and warning list. Nothing is presented as a prediction.

## Design decisions worth noting

**Expected value is computed over the full payoff distribution.** A common shortcut is `POP × max_profit − P(loss) × max_loss`. That is wrong for spreads and condors, where most outcomes are partial wins or partial losses between the strikes. This implementation integrates over the whole distribution instead.

**Both physical and risk-neutral EV are shown.** Displaying only one silently picks a side in the disagreement between your forecast and the market's. Showing both makes the disagreement visible.

**Execution costs are subtracted before scoring, not after.** Commission ($0.65/contract) and slippage ($0.02/contract) are applied during evaluation, so no candidate can rank well on an edge that costs would erase.

**Missing data produces warnings, not substituted values.** IV Rank and IV Percentile stay neutral until at least 30 daily snapshots exist rather than being computed from a handful of days.

**Short-dated contracts are penalized heavily.** The lognormal probability model degrades as expiration approaches, so a high score under 7 DTE more likely reflects model error than opportunity.

---

## Stack

**Backend** — Python 3.11+, FastAPI, Pydantic, SQLAlchemy, SQLite
**Frontend** — React, Vite, TypeScript
**Data** — [Massive.com](https://massive.com) Options API

Roughly 4,300 lines of backend Python, plus ~990 lines of tests.

## Tests

70 tests, all passing.

```bash
pytest
```

| Module | Tests |
|---|---|
| Liquidity filtering | 10 |
| IV Rank / Percentile | 8 |
| Candidate tracking | 8 |
| Payoff calculations | 7 |
| Probability grid | 7 |
| Realized volatility | 7 |
| Composite scoring | 6 |
| Strategy builder | 4 |
| Contract metrics | 4 |
| Schemas, chain, health, normalization | 9 |

Coverage is deliberately weighted toward the math. A subtly wrong volatility number still renders as a plausible-looking score, so those paths need assertions rather than eyeballing.

---

## Setup

Requires a Massive.com API key.

### Backend

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env           # Windows: copy .env.example .env
# set MASSIVE_API_KEY in .env

cd backend
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

---

## API

| Endpoint | Description |
|---|---|
| `GET /health` | Service status |
| `GET /api/chain/{symbol}` | Normalized option chain snapshot |
| `GET /api/volatility/{symbol}` | IV30, realized vol, forecast, VRP |
| `POST /api/screen` | Run screen, return ranked candidates |
| `GET /api/tracking` | List tracked candidates |
| `POST /api/tracking` | Track a candidate |
| `POST /api/tracking/{id}/refresh` | Reprice against current quotes |
| `POST /api/tracking/refresh-all` | Reprice all open candidates |
| `POST /api/tracking/{id}/close` | Close a tracked candidate |

---

## Structure

```
backend/app/
  analytics/        liquidity, realized_vol, iv_rank, payoff,
                    probability, ev_engine, greeks,
                    strategy_builder, scoring
  api/              route handlers
  data/             Massive client, normalization
  db/               models, session
  schemas/          Pydantic schemas
  tests/            70 tests
frontend/src/       React + TypeScript dashboard
```

---

## Limitations

- **Not backtested.** The scoring model is a specified hypothesis, not a validated strategy. Historical replay is the next phase; snapshot storage already collects the required dataset.
- **Delayed data.** The Starter tier is 15-minute delayed. Suitable for daily screening, not execution.
- **Event risk is not automated.** Earnings and ex-dividend dates require manual flagging until a calendar integration exists.
- **Jump risk.** No realized-volatility forecast built from past closes anticipates a gap on news.
- **American exercise.** Early assignment on short legs is warned about, not modeled.

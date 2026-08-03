# Options Screener Dashboard

A personal options screener and dashboard that ranks option strategy candidates using volatility regime, expected value, liquidity, and Greek risk. Built for **swing-trade screening** (14–60 DTE), not intraday execution.

**Not financial advice.** This app is a research tool. It does not guarantee profitability.

## Main models (planned)

- IV Rank / IV Percentile
- Realized volatility forecast and variance risk premium
- Expected value from full payoff distribution
- EV / max loss alpha score
- Greek efficiency overlay
- Liquidity gate

## Data

Uses [Massive.com](https://massive.com) Options Starter data. Snapshots may be **15-minute delayed** — suitable for daily watchlist scanning, not live execution.

> Data may be delayed. Use this dashboard for screening and research, not live execution. Confirm live prices in your brokerage platform before trading.

## Setup

### Backend

```bash
cd options-screener
python -m venv .venv

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
copy .env.example .env
# Edit .env and set MASSIVE_API_KEY

cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### Tests

```bash
cd options-screener
pytest
```

## API (Phase 0–1)

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Service status |
| `GET /api/chain/{symbol}` | Normalized option chain snapshot |

## Limitations

- Delayed data depending on subscription tier
- Historical IV/Greeks require local snapshot storage (built over time)
- Event risk not fully automated until calendar integration
- Backtests require realistic bid/ask and slippage assumptions

## Project structure

```
options-screener/
  backend/app/     FastAPI, analytics, Massive client
  frontend/        React + Vite + TypeScript
```

See `OPTIONS_SCREENER_CURSOR_ROADMAP.txt` in the parent folder for the full build plan.

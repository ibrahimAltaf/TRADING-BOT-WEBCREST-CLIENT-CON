# TRADING-BOT-WEBCREST-CLIENT-CON

Single repository: **backend (FastAPI)** + **frontend (React/Vite)**.

| Path | Role |
|------|------|
| `bot new backend/` | API, scheduler, exchange, backtest, ML hooks |
| `trading-bot-dashboard/` | Web dashboard |

## Quick start (local)

**Backend**

```bash
cd "bot new backend"
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env   # fill DATABASE_URL, Binance keys, etc.
python -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend**

```bash
cd trading-bot-dashboard
npm install
# optional: .env with VITE_API_BASE_URL=http://127.0.0.1:8000
npm run dev
```

## Production (VPS)

- General: **`bot new backend/docs/VPS-DEPLOY.md`**
- Paths under **`/var/www`** (step-by-step): **`bot new backend/docs/VPS-VAR-WWW.md`**

On the server you can rename `bot new backend` → `backend` to avoid spaces in systemd paths.

Set **`CORS_ORIGINS`** in the API `.env` to your dashboard URL. Build the dashboard with **`VITE_API_BASE_URL`** pointing at your public API URL.

## License

Private / project use — adjust as needed.

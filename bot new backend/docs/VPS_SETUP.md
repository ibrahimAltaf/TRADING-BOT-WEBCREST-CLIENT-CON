# VPS production setup

## 1. System packages

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv git curl
# Optional: Docker
curl -fsSL https://get.docker.com | sh
```

## 2. TensorFlow

Use **Python 3.11** and install from `requirements-ml.txt` inside a venv.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-ml.txt
```

## 3. Train the BTC model (before live ML)

```bash
export PYTHONPATH=.
python scripts/train_btc_production.py --interval 5m --limit 8000 --epochs 32
```

Artifacts: `models/btc_usdt_5m/` and `models/btc_lstm_model.keras`.

## 4. Environment

Copy `.env.production` to `.env` and set `DATABASE_URL`, Binance keys, `JWT_SECRET`.

## 5. Run API

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## 6. Docker

```bash
docker compose --env-file .env.production up -d --build
```

## 7. Scheduler + systemd

Set `LIVE_SCHEDULER_ENABLED=true` and install a unit that runs uvicorn (or gunicorn) and restarts on failure.

## 8. Daily retrain (cron)

```cron
0 4 * * * cd /opt/trading && . .venv/bin/activate && PYTHONPATH=. python scripts/retrain_model.py >> /var/log/retrain.log 2>&1
```

## 9. Verify ML

- `GET /status/ml` — flags
- `GET /status/model-health?smoke=true` — load + optional inference smoke test
- `GET /stats/performance` — ML participation % from recent decisions

# Deploy on VPS under `/var/www` (example: Ubuntu)

Assumes repo: **TRADING-BOT-WEBCREST-CLIENT-CON** (monorepo: `bot new backend/` + `trading-bot-dashboard/`).

Replace:

- `api.yourdomain.com` → your API host  
- `app.yourdomain.com` → your dashboard host (optional)

---

## 1. Clone (new folder name, no spaces issue in parent)

```bash
cd /var/www
sudo git clone https://github.com/ibrahimAltaf/TRADING-BOT-WEBCREST-CLIENT-CON.git TRADING-BOT-WEBCREST
sudo chown -R $USER:www-data /var/www/TRADING-BOT-WEBCREST
cd /var/www/TRADING-BOT-WEBCREST
```

---

## 2. Backend — venv + deps

```bash
cd "/var/www/TRADING-BOT-WEBCREST/bot new backend"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
nano .env   # DATABASE_URL, BINANCE_*, JWT_SECRET, CORS_ORIGINS=https://app.yourdomain.com
```

PostgreSQL DB banao aur `DATABASE_URL` set karo, phir:

```bash
source venv/bin/activate
python scripts/init_db.py
# or: python -c "from src.db.base import Base; from src.db.session import engine; from src.db import models; Base.metadata.create_all(bind=engine)"
```

Test:

```bash
source venv/bin/activate
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
# Ctrl+C after curl test
```

---

## 3. Systemd (API always on)

Edit paths if user differs — file: `deploy/systemd/trading-bot-api.service` (copy values):

```ini
WorkingDirectory=/var/www/TRADING-BOT-WEBCREST/bot new backend
EnvironmentFile=-/var/www/TRADING-BOT-WEBCREST/bot new backend/.env
ExecStart=/var/www/TRADING-BOT-WEBCREST/bot new backend/venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --workers 2
```

**Note:** systemd `WorkingDirectory` with spaces can be tricky; safer rename:

```bash
cd /var/www/TRADING-BOT-WEBCREST
mv "bot new backend" backend
# then WorkingDirectory=/var/www/TRADING-BOT-WEBCREST/backend
```

```bash
sudo nano /etc/systemd/system/trading-bot-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now trading-bot-api
sudo systemctl status trading-bot-api
```

---

## 4. Nginx reverse proxy (HTTPS)

```bash
sudo certbot certonly --nginx -d api.yourdomain.com
```

Site config (proxy to `127.0.0.1:8000`) — see `deploy/nginx/api-site.conf`, then:

```bash
sudo ln -sf /etc/nginx/sites-available/trading-bot-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 5. Dashboard build (same server)

```bash
cd /var/www/TRADING-BOT-WEBCREST/trading-bot-dashboard
npm ci
echo 'VITE_API_BASE_URL=http://YOUR_SERVER_IP:8000' > .env.production
npm run build
```

### 5b. Live 24/7 (SSH band hone par bhi UI chale)

`npm run preview` **mat** chalao — SSH band hote hi band ho jata hai.

**Option A — Nginx (recommended):** sirf static files, Node ki zaroorat nahi.

```bash
# Agar port 80 pe pehle se koi site hai to default site disable karo ya is config mein server_name / port badlo
sudo cp /var/www/TRADING-BOT-WEBCREST/bot\ new\ backend/deploy/nginx/trading-dashboard-http-ip.conf /etc/nginx/sites-available/trading-dashboard
sudo ln -sf /etc/nginx/sites-available/trading-dashboard /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Browser: **`http://YOUR_SERVER_IP/`** (port 80).

**Option B — systemd + `serve`:** port 4173 pe Node process.

```bash
sudo npm install -g serve
sudo cp "/var/www/TRADING-BOT-WEBCREST/bot new backend/deploy/systemd/trading-dashboard-serve.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-dashboard-serve
```

Browser: **`http://YOUR_SERVER_IP:4173`**

---

Older snippet (copy dist elsewhere) — optional:

```bash
sudo mkdir -p /var/www/html-trading-dashboard
sudo cp -r dist/* /var/www/html-trading-dashboard/
```

Nginx `server` for `app.yourdomain.com` with `root /var/www/html-trading-dashboard;` and `try_files $uri $uri/ /index.html;`

---

## 6. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

---

## 7. Smoke

```bash
curl -s https://api.yourdomain.com/status | jq
curl -s https://api.yourdomain.com/status/summary | jq
```

---

## Existing folders in `/var/www`

Old projects (`WebCrestDashboard`, `TRADING-BOT`, etc.) ko **mat overwrite** karo — naya folder **`TRADING-BOT-WEBCREST`** use karo taake clash na ho.

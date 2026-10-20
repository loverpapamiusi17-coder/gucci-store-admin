# Gucci Store Admin — starter

Admin dashboard and API for a Telegram Mini App store. Includes product management, image uploads, delivery/checkout text settings, order status management, public product API, server-side order total calculation, stock checks, and optional Telegram notifications.

## Run locally
1. Install Python 3.11+.
2. `python -m venv .venv`
3. Activate venv and run `pip install -r requirements.txt`.
4. Set environment variables from `.env.example` (do not commit real secrets). At minimum set `SECRET_KEY` and `ADMIN_PASSWORD`.
5. Run `python app.py` and open `http://127.0.0.1:5000/admin/login`.

## Deploy
Deploy as a Python web service (not a static Netlify site). The included `Procfile` runs Gunicorn. Set environment variables in your hosting dashboard:
- `SECRET_KEY`: long random secret
- `ADMIN_PASSWORD`: unique strong admin password
- `COOKIE_SECURE=1` when served over HTTPS
- `DATABASE_URL`: managed PostgreSQL URL for production (recommended)
- `TELEGRAM_BOT_TOKEN`, `ADMIN_CHAT_ID`: optional new-order alerts

Use HTTPS, managed PostgreSQL, backups, rate limiting/WAF on `/api/orders`, log monitoring, and a persistent/private upload bucket for production. Do not use SQLite on ephemeral hosting for a live store. Restrict admin access further (VPN/IP allowlist or 2FA) before handling real customer data.

## API
- `GET /api/products` — active products as JSON
- `POST /api/orders` — JSON `{ "name":"...", "contact":"...", "delivery":"...", "comment":"", "items":[{"product_id":1,"quantity":2}] }`
  The server recalculates prices from the database and checks stock. Returns an order ID.
- `GET /uploads/<filename>` — uploaded product image

## Connect the existing Mini App
Change the frontend to fetch `GET /api/products` instead of hardcoded products, and send orders to `POST /api/orders`. Do not trust client-side prices or accept payment details directly. Telegram Web App `sendData` is a separate flow; validate Telegram `initData` on the backend before trusting the Telegram user identity. The current frontend HTML does not automatically connect to this backend.

## Important limitations
This is a starter, not a fully audited production commerce system. No card payments, tax/shipping integrations, Telegram initData verification, rate limiting, or image malware scanning are included. Add and test these before launch.

# ganbayar_trading_bot

## What is this?
Python (FastAPI) backend + React (Vite/TS) frontend арилжааны ботын цэвэр template.

## Firebase is the Canonical User Database

In production, **Firebase Firestore is the single source of truth** for all user-related data:
- User identity (email, name, has_paid_access)
- User preferences (telegram_chat_id, scan_enabled, etc.)
- User strategies
- User signal history

The Python backend does NOT have Firebase credentials. Instead, it accesses user data via the dashboard's internal API endpoints.

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Python Backend │────▶│ Dashboard (Next)│────▶│    Firestore    │
│  (VPS/Docker)   │     │  (Vercel)       │     │   (jkmdatabase) │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                      │
         │                      ▼
         │              ┌─────────────────┐
         │              │ Prisma (Postgres)│
         │              │ (auth/billing)  │
         │              └─────────────────┘
         ▼
    ┌─────────────────┐
    │  Internal API   │
    │  x-internal-    │
    │  api-key        │
    └─────────────────┘
```

### Production Configuration

Set these environment variables in production:

```bash
# Enable privacy mode (no local user data storage)
JKM_PRIVACY_MODE=1

# All providers should use dashboard
USER_DB_PROVIDER=dashboard
USER_STRATEGIES_PROVIDER=dashboard
USER_SIGNALS_PROVIDER=dashboard
USER_ACCOUNTS_PROVIDER=dashboard
USER_TELEGRAM_PROVIDER=dashboard

# Dashboard connection
DASHBOARD_BASE_URL=https://your-dashboard.vercel.app
DASHBOARD_INTERNAL_API_KEY=your-secure-key
```

### Migrating Existing Data

If you have existing local user data, run the migration script:

```bash
# Preview changes
python tools/migrate_local_user_data_to_dashboard.py --dry-run --verbose

# Run migration
python tools/migrate_local_user_data_to_dashboard.py
```

## Setup (Local Development)

1. Copy example files:
   - `.env.example` → `.env`
   - `user_profiles.example.json` → `user_profiles.json`
   - `allowed_users.example.json` → `allowed_users.json`
   - Fill in your local values (never commit!)

2. Python backend:
   ```bash
   pip install -r requirements.txt
   python api_server.py
   ```

3. For local development without dashboard:
   - Set `USER_*_PROVIDER=local` in `.env`
   - Set `JKM_PRIVACY_MODE=0`

## Important
- `.env`, `user_profiles.json`, `allowed_users.json`, `instruments.json` зэрэг хувийн/нууц файлуудыг commit-д оруулахгүй!
- Жишээ файлуудыг (example) ашиглан өөрийн хувийн файлаа үүсгэнэ.

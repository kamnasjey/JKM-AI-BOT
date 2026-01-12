# Deployment Guide (Docker)

This guide explains how to deploy the JKM Trading Bot to a Linux server (VPS/Cloud) using Docker Compose.

## Prerequisites

1.  **Linux Server** (Ubuntu/Debian recommended).
2.  **Docker** & **Docker Compose** installed.
    -   Link: [Install Docker Engine](https://docs.docker.com/engine/install/)

## Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/kamnasjey/JKM-AI-BOT.git
    cd JKM-AI-BOT
    ```

2.  **Configuration (Important)**
    -   Copy example configs if needed:
        ```bash
        cp allowed_users.example.json allowed_users.json
        cp user_profiles.example.json user_profiles.json
        cp instruments.example.json instruments.json
        ```
    -   Using `.env` relative to Docker is optional if you use `docker-compose.yml` environment vars, but recommended for secrets.

3.  **Start the Service**
    ```bash
    docker compose up -d --build
    ```
    -   `-d` runs in detached mode (background).
    -   `--build` ensures fresh image build.

4.  **Verify Deployment**
    -   Check if running:
        ```bash
        docker compose ps
        ```
    -   Check Health:
        ```bash
        curl http://localhost:8000/health
        ```
        Should return `{"status":"ok", ...}`

## Maintenance

### Updating Code
To pull the latest changes and update the container:

```bash
# 1. Pull changes
git pull origin main

# 2. Rebuild and restart (minimal downtime)
docker compose up -d --build

# 3. Check logs
docker compose logs -f --tail=100
```

### Logs
To see the application logs:
```bash
docker compose logs -f backend
```

### State Persistence
All runtime data is saved in the `./state` directory on the host machine. This assumes you backed up this folder if you migrate servers.

## Verification Checklist

Run these commands on the server to verify a successful deployment:

1.  **Check Container Status**:
    ```bash
    docker compose ps
    ```

2.  **Verify Health Endpoint**:
    ```bash
    curl http://localhost:8000/health
    # Expected: {"ok":true, "uptime_s":..., ...}
    ```

3.  **Verify API & Signals**:
    ```bash
    curl "http://localhost:8000/api/signals?limit=3"
    # Expected: JSON list of signals (empty list [] is fine if new)
    ```

4.  **Verify Persistence Permissions**:
    ```bash
    ls -la state
    # Expected: signals.jsonl files created by the app
    
    # Test write permission:
    touch state/_write_test && echo OK > state/_write_test && cat state/_write_test
    rm state/_write_test
    ```

## New API Endpoints (v0.2)

All internal endpoints require header: `x-internal-api-key: <YOUR_INTERNAL_API_KEY>`

### Owner Admin Default Strategy (Optional)

By default, the backend requires users to explicitly configure a strategy before scanning.

If you want the owner/admin account to have the previously-default working strategy preloaded,
set this env var in your Docker Compose:

```bash
OWNER_ADMIN_USER_ID=<your_admin_user_id>
```

On startup, if that user has no saved strategies yet, the backend will seed the owner strategy
(`strategy_id: jkm_strategy`, `name: JKM strategy`) into the per-user strategies store.

### Engine Status (Truth Source)
```bash
curl -H "x-internal-api-key: $INTERNAL_API_KEY" http://localhost:8000/api/engine/status
# Returns: {"ok":true,"running":true,"last_scan_ts":1736684400,"last_scan_id":"scan_abc123","cadence_sec":300,"last_error":null}
```

### Manual Scan Trigger
```bash
curl -X POST -H "x-internal-api-key: $INTERNAL_API_KEY" http://localhost:8000/api/engine/manual-scan
# Returns: {"ok":true,"result":{"ok":true,"triggered":true,"last_scan_id":"scan_xyz","last_scan_ts":"..."}}
```

### Signal Detail
```bash
curl "http://localhost:8000/api/signals/abc123-signal-id"
# Returns: {"ok":true,"signal":{...}} or 404 {"ok":false,"message":"not_found"}
```

### Symbols (Watchlist)
```bash
curl http://localhost:8000/api/symbols
# Returns: {"ok":true,"symbols":["EURUSD","XAUUSD",...],"count":15}
```

### Candles for Charts
```bash
curl "http://localhost:8000/api/markets/XAUUSD/candles?tf=M5&limit=200"
# Returns: {"ok":true,"symbol":"XAUUSD","tf":"M5","candles":[{"time":1736684400,"open":2650.5,"high":2651.0,"low":2649.8,"close":2650.2},...],"count":200}
```

### Metrics Summary
```bash
curl http://localhost:8000/api/metrics
# Returns: {"ok":true,"total_signals":1234,"ok_count":456,"none_count":778,"hit_rate":0.3693,"last_24h_ok":12,"last_24h_total":45}
```


5.  **Check Application Logs**:
    ```bash
    docker compose logs --tail=100 backend
    ```

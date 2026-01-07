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

# Production Deploy (One Command)

Target host:
- VPS: `159.65.11.255`
- User: `root`
- Repo path: `/opt/JKM-AI-BOT`

This repo supports a beginner-proof, one-command deploy via `deploy_safe.sh`.

## Deploy (copy/paste)

```bash
ssh -o StrictHostKeyChecking=no root@159.65.11.255

cd /opt/JKM-AI-BOT
pwd

git pull

chmod +x ./deploy_safe.sh
./deploy_safe.sh
```

Notes:
- The script loads `.env` without printing secrets.
- Use `python3` (not `python`) for JSON formatting.

## Verification (copy/paste)

```bash
cd /opt/JKM-AI-BOT

docker compose ps

curl -s http://localhost:8000/health | python3 -m json.tool || curl -s http://localhost:8000/health
curl -s "http://localhost:8000/api/signals?limit=3" | python3 -m json.tool || curl -s "http://localhost:8000/api/signals?limit=3"

# Check persistence mounts exist on host
ls -la state logs
```

Expected:
- `docker compose ps` shows `backend` is `Up`
- `/health` includes `"ok": true` and `"provider_configured": true`
- `/api/signals?limit=3` returns `[]`

## Troubleshooting

### Container not up / restarting

```bash
docker compose ps

docker compose logs --tail=200 backend
```

### Health fails (`provider_configured` is false)

- Ensure `/opt/JKM-AI-BOT/.env` exists and contains `MASSIVE_API_KEY`.
- Re-run:

```bash
cd /opt/JKM-AI-BOT
./deploy_safe.sh
```

### Permission / persistence problems

- Verify bind mounts exist and are writable by Docker:

```bash
cd /opt/JKM-AI-BOT
mkdir -p state logs

echo "ok" > state/_host_write_test.txt
ls -la state | tail -n 20
```

If needed, check the container view of the mount:

```bash
docker compose exec -T backend sh -lc 'ls -la /app/state | tail -n 20'
```

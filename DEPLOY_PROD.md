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

## GO-LIVE VPS Runbook (copy/paste)

This is the end-to-end production runbook for a fresh VPS or a go-live day.

```bash
# 0) SSH
ssh -o StrictHostKeyChecking=no root@159.65.11.255

set -euo pipefail

# 1) Deploy latest backend
cd /opt/JKM-AI-BOT
git pull
chmod +x ./deploy_safe.sh
./deploy_safe.sh

# 2) Verify backend locally (backend is localhost-only)
docker compose ps
curl -fsS http://127.0.0.1:8000/health | python3 -m json.tool
curl -fsS "http://127.0.0.1:8000/api/signals?limit=3" | python3 -m json.tool

# 3) DNS check from VPS (requires A record api.jkmcopilot.com -> 159.65.11.255)
apt update
apt install -y dnsutils
dig +short api.jkmcopilot.com

# 4) Nginx reverse proxy + SSL (Let's Encrypt)
apt install -y nginx certbot python3-certbot-nginx
systemctl enable --now nginx

cat > /etc/nginx/sites-available/jkm_api <<'NGINX'
server {
	listen 80;
	listen [::]:80;
	server_name api.jkmcopilot.com;

	client_max_body_size 10m;

	location / {
		proxy_pass http://127.0.0.1:8000;
		proxy_http_version 1.1;
		proxy_set_header Connection "";

		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
	}
}
NGINX

rm -f /etc/nginx/sites-enabled/default || true
ln -sf /etc/nginx/sites-available/jkm_api /etc/nginx/sites-enabled/jkm_api
nginx -t
systemctl reload nginx

# 5) Firewall
ufw allow OpenSSH || true
ufw allow 'Nginx Full' || true
ufw --force enable || true
ufw status || true

# 6) Issue SSL cert (requires DNS + inbound port 80/443)
certbot --nginx -d api.jkmcopilot.com

# 7) HTTPS verify
curl -fsS https://api.jkmcopilot.com/health | python3 -m json.tool
curl -fsS "https://api.jkmcopilot.com/api/signals?limit=3" | python3 -m json.tool
```

## Verification (copy/paste)

```bash
cd /opt/JKM-AI-BOT

docker compose ps

curl -s http://localhost:8000/health | python3 -m json.tool || curl -s http://localhost:8000/health
curl -s "http://localhost:8000/api/signals?limit=3" | python3 -m json.tool || curl -s "http://localhost:8000/api/signals?limit=3"

# After hardening docker-compose.yml, the backend binds to 127.0.0.1 only.
# Health/API should still work via localhost (on the VPS) and via your Nginx+HTTPS domain.
# Example (if Nginx is configured to proxy to the backend):
# curl -s https://jkmcopilot.com/health | python3 -m json.tool || true

# Check persistence mounts exist on host
ls -la state logs
```

Expected:
- `docker compose ps` shows `backend` is `Up`
- `/health` includes `"ok": true` and `"provider_configured": true`
- `/api/signals?limit=3` returns a JSON array (can be empty or non-empty)

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

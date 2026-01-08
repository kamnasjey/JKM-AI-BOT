# Frontend Deploy (Vercel)

This repo’s frontend lives in the `frontend/` folder and is built with Vite + React.

## Configure API base URL

The frontend reads the API base URL from:
- `NEXT_PUBLIC_API_BASE`

If it is not set, it defaults to `http://localhost:8000`.

Important (official Next.js docs note):
- To expose an environment variable to the browser in Next.js, it must be prefixed with `NEXT_PUBLIC_`.
- Source: https://nextjs.org/docs/app/building-your-application/configuring/environment-variables#bundling-environment-variables-for-the-browser

Quote from the docs:
> "By default, environment variables are only available on the server. To expose an environment variable to the browser, it must be prefixed with `NEXT_PUBLIC_`."

Even though this frontend is Vite-based (not Next.js), we intentionally support the same `NEXT_PUBLIC_` prefix for consistency.

## Local development

```bash
cd frontend
npm install
npm run dev
```

Backend options for local dev:
- If you run the backend on `http://localhost:8000`, the frontend will use it by default.
- If you changed backend CORS to be strict, set `CORS_ALLOW_ALL=true` in the backend environment for local dev, or use a same-origin proxy.

## Vercel deploy steps

1) Push your repo to GitHub.
2) Go to Vercel → **New Project** → Import your GitHub repo.
3) Set **Root Directory** to `frontend`.
4) Build settings (Vercel usually auto-detects):
   - Build Command: `npm run build`
   - Output Directory: `dist`
5) Add Environment Variables (Project Settings → Environment Variables):
   - `NEXT_PUBLIC_API_BASE` = `https://api.jkmcopilot.com`
6) Click **Deploy** (or **Redeploy** after changing env vars).

## Post-deploy checks

Open the deployed site and confirm:
- The status widget shows API OK
- Signals page shows either signals or “No signals yet”

# Frontend Deployment on Vercel (Vite + React)

This is a **Vite** project. Do NOT use Next.js framework preset.

## Vercel Project Settings

| Setting           | Value                            |
|-------------------|----------------------------------|
| Root Directory    | `frontend`                       |
| Framework Preset  | **Vite**                         |
| Install Command   | `npm install`                    |
| Build Command     | `npm run build`                  |
| Output Directory  | `dist`                           |

## Environment Variables (Vercel → Settings → Environment Variables)

| Name            | Value                            |
|-----------------|----------------------------------|
| `VITE_API_BASE` | `https://api.jkmcopilot.com`     |

> **Important**: Do NOT use `NEXT_PUBLIC_*` env vars. Vite only exposes `VITE_*` prefixed variables to the browser.

## Local Development

```bash
cd frontend
npm install
npm run dev
```

The app defaults to `http://localhost:8000` for API calls when `VITE_API_BASE` is not set.

## Production Build (local test)

```bash
cd frontend
npm run build
npm run preview
```

## Troubleshooting

- **Build fails with `next build`**: Ensure Framework Preset is set to **Vite**, not Next.js.
- **API calls fail in production**: Ensure `VITE_API_BASE` is set in Vercel environment variables.
- **404 on page refresh (SPA routes)**: Add a `vercel.json` with rewrites if needed:

```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }]
}
```

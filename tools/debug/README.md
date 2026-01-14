# Debug tools (JKM)

Энд байгаа скриптүүд нь түр debug/ops зориулалттай бөгөөд runtime кодыг бохирдуулахгүй байлгахын тулд `tools/debug/` дотор байрлуулсан.

## Dashboard user-data gateway шалгах

### Backend талын env-үүд

- `DASHBOARD_USER_DATA_URL=https://<your-vercel-domain>`
- `DASHBOARD_INTERNAL_API_KEY=<same key as Vercel>`

### Ажиллуулах

`python tools/debug/test_dashboard_user_data_gateway.py`

Юу шалгана:
- `GET /api/internal/user-data/health` (Firestore + Prisma)
- `GET /api/internal/user-data/users` (paid users)
- `GET /api/internal/user-data/users/{userId}` (prefs)
- `GET /api/internal/user-data/strategies/{userId}`

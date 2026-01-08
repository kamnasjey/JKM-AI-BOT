# ganbayar_trading_bot

## What is this?
Python (FastAPI) backend + React (Vite/TS) frontend арилжааны ботын цэвэр template.

## Setup
1. .env.example, user_profiles.example.json, allowed_users.example.json файлуудыг хуулж:
   - .env, user_profiles.json, allowed_users.json нэртэй үүсгэнэ
   - Жинхэнэ утгуудыг зөвхөн өөрийн локал дээр бөглөнө (commit хийхгүй!)
2. Python backend:
   - pip install -r requirements.txt
   - python main.py
3. Frontend:
   - cd frontend
   - npm install
   - npm run dev

## Important
- .env, user_profiles.json, allowed_users.json, instruments.json зэрэг хувийн/нууц файлуудыг commit-д оруулахгүй!
- Жишээ файлуудыг (example) ашиглан өөрийн хувийн файлаа үүсгэнэ.

## Documentation
- [AGENT_SESSION_GUIDE.md](./AGENT_SESSION_GUIDE.md) - GitHub Copilot agent session-тэй ажиллах заавар (Англи + Монгол)
- [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) - Төслийн архитектур, дизайны зарчим
- [.github/copilot-instructions.md](./.github/copilot-instructions.md) - Copilot агентын дүрэм

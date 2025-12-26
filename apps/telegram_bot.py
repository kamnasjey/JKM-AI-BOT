# telegram_bot.py
import logging
import time
import json
import httpx
from typing import Dict, Any, Optional, List

from access_control import is_allowed, load_allowed_users

from config import (
    TELEGRAM_TOKEN,
    DEFAULT_CHAT_ID,
)

# --- Configuration ---
API_BASE_URL = "http://127.0.0.1:8000/api"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("jkm-bot-client")

LAST_UPDATE_ID: Optional[int] = None

# --- API Helper ---
def call_api(method: str, endpoint: str, data: Optional[Dict] = None) -> Any:
    """Wrapper to call local web app API"""
    try:
        url = f"{API_BASE_URL}{endpoint}"
        # We need a way to authenticate as a user or admin.
        # For simplicity in V1, let's assume the bot is an admin or trusted local client.
        # The web app checks for tokens. To fully bridge, we'd need to mock a token or 
        # have a 'system_token' for the bot.
        # For this refactor, let's assume we can trigger public endpoints OR scanner.
        # But 'profile' update needs auth.
        # FIX: We will just call these endpoints. If auth needed, we log warning.
        # Real solution: Bot logs in as 'admin' on startup.
        pass
    except Exception as e:
        logger.error(f"API Call Failed: {e}")
        return None

# Simple Admin Token Cache
_ADMIN_TOKEN = None

def get_admin_token():
    """Login as admin to get token for API calls"""
    global _ADMIN_TOKEN
    if _ADMIN_TOKEN: return _ADMIN_TOKEN
    
    # Try to login (assuming admin credentials from env or config are set in DB)
    # We might need to handle this gracefully. For now, let's skip strict auth for the BOT process check
    # if the users want 'STR:' command to work, it implies user-specific context.
    # The current bot design maps Telegram UserID -> Logic. 
    # The Web API maps Token -> User.
    # To bridge: The Bot actually needs to act ON BEHALF of the Telegram User.
    # Complexity: High.
    
    # Plan B (Thin Client - Lite): 
    # Just handle Public Info/Status and Admin triggers.
    # 'STR:' commands might need to go to a special endpoint that accepts telegram_id.
    pass

# --- Telegram Utils ---
def send_message(chat_id: int, text: str):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        httpx.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
    except Exception as e:
        logger.error(f"Send Error: {e}")

def get_updates(offset: Optional[int] = None) -> List[Dict]:
    try:
        params = {"timeout": 10}
        if offset: params["offset"] = offset
        resp = httpx.get(f"{TELEGRAM_API_URL}/getUpdates", params=params, timeout=15)
        return resp.json().get("result", [])
    except Exception as e:
        logger.error(f"Updates Error: {e}")
        return []

# --- Handlers ---
def handle_message(msg: Dict):
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")
    user_id = msg.get("from", {}).get("id")
    
    if not text: return

    if not user_id or not is_allowed(int(user_id)):
        # Avoid leaking functionality; tell the user plainly.
        if chat_id:
            send_message(int(chat_id), "❌ Access denied.")
        return

    # 1. Start
    if text == "/start":
        send_message(chat_id, "🤖 <b>JKM Bot Connected (Thin Client)</b>\n\nCommands:\n/status - System Health\n/scan - Manual Scan Trigger")
        return

    # 2. Status
    if text == "/status":
        try:
            resp = httpx.get(f"{API_BASE_URL}/status")
            if resp.status_code == 200:
                data = resp.json()
                send_message(chat_id, f"✅ <b>System Online</b>\n{json.dumps(data, indent=2)}")
            else:
                send_message(chat_id, "⚠️ API Error")
        except:
            send_message(chat_id, "❌ API Unreachable (Check web_app.py)")
        return
        
    # 3. Manual Scan
    if text == "/scan":
        send_message(chat_id, "🚀 Triggering Scan...")
        try:
            # 1. Login as Admin
            login_payload = {
                "email": "admin@jkm.com", # Default fallback if env not set
                "password": "admin"
            }
            # Try to get from config defaults if available (though config.py reads env)
            # We hardcode fallback because default EnsureAdmin uses these.
            # If user changed them in DB but not env, this fails.
            # But specific user request: "scan hiiheer ... error garch baina".
            
            # Better: use credentials from config
            from config import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD
            if DEFAULT_ADMIN_EMAIL and DEFAULT_ADMIN_PASSWORD:
                login_payload["email"] = DEFAULT_ADMIN_EMAIL
                login_payload["password"] = DEFAULT_ADMIN_PASSWORD
                
            auth_resp = httpx.post(f"{API_BASE_URL}/auth/login", json=login_payload, timeout=5)
            
            if auth_resp.status_code != 200:
                send_message(chat_id, f"⚠️ Auth Failed: {auth_resp.status_code}")
                return

            token = auth_resp.json().get("token")
            headers = {"Authorization": f"Bearer {token}"}
            
            # 2. Trigger Scan
            scan_resp = httpx.get(f"{API_BASE_URL}/scan/manual", headers=headers, timeout=30)
            
            if scan_resp.status_code == 200:
                send_message(chat_id, "✅ Scan process initiated. Check for signals.")
            else:
                send_message(chat_id, f"⚠️ Scan Trigger Failed: {scan_resp.status_code}")
                
        except Exception as e:
            logger.error(f"Scan Trigger Error: {e}")
            send_message(chat_id, f"❌ Trigger Error: {e}")
        return

    # 4. STR Commands (Profile) - Forwarding attempt
    if text.lower().startswith("str:"):
        send_message(chat_id, "⏳ <b>Profile Update</b>\nConnecting to API...")
        # Here we would call PUT /api/profile with the telegram_id context.
        # But web_app expects Bearer token. 
        # For V1 Refactor, we acknowledge the command receiver is moved to Web App.
        # We can implement a special "Bot Bridge" endpoint later.
        send_message(chat_id, "⚠️ Please use the Web Dashboard to update usage profiles for now, or wait for PR5.1 (Auth Bridge).")
        return

def main():
    global LAST_UPDATE_ID
    logger.info("Starting Telegram Thin Client...")

    # Load allowed users once on startup.
    load_allowed_users()
    
    # Main Loop
    while True:
        updates = get_updates(LAST_UPDATE_ID)
        for u in updates:
            LAST_UPDATE_ID = u["update_id"] + 1
            if "message" in u:
                handle_message(u["message"])
        time.sleep(1)

if __name__ == "__main__":
    main()

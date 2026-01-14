#!/usr/bin/env python3
"""Worker process for async notification delivery.

Consumes events from the queue and sends Telegram notifications.
Runs separately from core scan to prevent blocking.

Usage:
    python worker_main.py
    
Environment:
    WORKER_POLL_INTERVAL_S: Polling interval (default: 2)
    WORKER_BATCH_SIZE: Events per batch (default: 50)
    WORKER_DRY_RUN: If "1", don't actually send (default: 0)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] worker: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("worker")

# Suppress httpx token leakage
logging.getLogger("httpx").setLevel(logging.WARNING)


def _log_kv(event: str, **kv: Any) -> None:
    """Structured log output."""
    parts = [event]
    for k, v in kv.items():
        if v is not None:
            parts.append(f"{k}={v}")
    logger.info(" | ".join(parts))


def main() -> None:
    """Main worker loop."""
    
    # Enforce privacy mode on startup (purge local user artifacts)
    from core.privacy import enforce_privacy_on_startup
    enforce_privacy_on_startup(verbose=True)
    
    # Config
    poll_interval = float(os.getenv("WORKER_POLL_INTERVAL_S", "2"))
    batch_size = int(os.getenv("WORKER_BATCH_SIZE", "50"))
    dry_run = str(os.getenv("WORKER_DRY_RUN", "0")).strip() == "1"
    
    logger.info("=== JKM Worker Starting ===")
    logger.info(f"poll_interval={poll_interval}s batch_size={batch_size} dry_run={dry_run}")
    
    # Initialize event queue DB
    from core.event_queue import (
        init_db,
        claim_events,
        mark_done,
        mark_failed,
        delivery_recent,
        record_delivery,
        get_queue_stats,
        cleanup_old_deliveries,
        cleanup_old_tokens,
    )
    
    try:
        init_db()
        logger.info("event_queue DB initialized")
    except Exception as e:
        logger.error(f"Failed to init event_queue DB: {e}")
        sys.exit(1)
    
    # Import user DB functions
    from user_db import list_users_with_telegram, init_db as init_user_db
    
    try:
        init_user_db()
        logger.info("user_db initialized")
    except Exception as e:
        logger.warning(f"user_db init warning: {e}")
    
    # Import Telegram notifier
    telegram_available = True
    telegram_notifier = None
    try:
        from services.notifier_telegram import telegram_notifier as _tg
        telegram_notifier = _tg
        if not telegram_notifier.token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured - running in dry-run mode")
            telegram_available = False
    except Exception as e:
        logger.warning(f"Telegram notifier not available: {e}")
        telegram_available = False
    
    # Stats
    total_processed = 0
    total_sent = 0
    last_cleanup = 0
    cleanup_interval = 3600  # 1 hour
    
    _log_kv("WORKER_START", telegram_available=telegram_available, dry_run=dry_run)
    
    while True:
        try:
            # Periodic cleanup
            now = int(time.time())
            if now - last_cleanup > cleanup_interval:
                try:
                    d1 = cleanup_old_deliveries(older_than_days=7)
                    d2 = cleanup_old_tokens(older_than_days=7)
                    if d1 or d2:
                        _log_kv("WORKER_CLEANUP", deliveries=d1, tokens=d2)
                    last_cleanup = now
                except Exception:
                    pass
            
            # Claim events
            events = claim_events(limit=batch_size, lock_s=120)
            
            if events:
                _log_kv("WORKER_CLAIM", count=len(events))
                
                # Get users with Telegram enabled
                tg_users = []
                try:
                    tg_users = list_users_with_telegram()
                except Exception as e:
                    logger.warning(f"Failed to get telegram users: {e}")
                
                for event in events:
                    try:
                        lag_s = int(time.time()) - event.created_ts
                        
                        # For each user with Telegram
                        sent_count = 0
                        for user in tg_users:
                            user_id = str(user.get("user_id") or "")
                            chat_id = str(user.get("chat_id") or "")
                            
                            if not user_id or not chat_id:
                                continue
                            
                            # Dedupe check
                            if delivery_recent(user_id, event.setup_key):
                                continue
                            
                            # Build message
                            msg = _build_message(event)
                            
                            # Send (or dry-run)
                            if dry_run or not telegram_available:
                                _log_kv(
                                    "NOTIFY_DRY_RUN",
                                    event_id=event.id[:8],
                                    user_id=user_id,
                                    chat_id_masked=f"***{chat_id[-4:]}" if len(chat_id) > 4 else "***",
                                )
                                sent_ok = True
                            else:
                                try:
                                    sent_ok = telegram_notifier.send_message(msg, chat_id=int(chat_id))
                                except Exception as e:
                                    logger.warning(f"Send failed: {type(e).__name__}")
                                    sent_ok = False
                            
                            if sent_ok:
                                record_delivery(user_id, event.setup_key, cooldown_s=1800)
                                sent_count += 1
                        
                        # Mark event as done
                        mark_done(event.id)
                        total_processed += 1
                        total_sent += sent_count
                        
                        _log_kv(
                            "EVENT_PROCESSED",
                            event_id=event.id[:8],
                            symbol=event.symbol,
                            setup_type=event.setup_type,
                            lag_s=lag_s,
                            sent_to=sent_count,
                        )
                        
                    except Exception as e:
                        logger.error(f"Event processing error: {type(e).__name__}: {e}")
                        # Retry with exponential backoff
                        retry_s = min(60 * (2 ** min(event.attempts, 5)), 3600)
                        mark_failed(event.id, retry_after_s=retry_s)
                
                # Log queue stats periodically
                if total_processed % 100 == 0:
                    stats = get_queue_stats()
                    _log_kv(
                        "WORKER_STATS",
                        processed=total_processed,
                        sent=total_sent,
                        queue_new=stats.get("NEW", 0),
                        queue_failed=stats.get("FAILED", 0),
                    )
            
            # Sleep between polls
            time.sleep(poll_interval)
            
        except KeyboardInterrupt:
            logger.info("Worker shutting down...")
            break
        except Exception as e:
            logger.error(f"Worker loop error: {type(e).__name__}: {e}")
            time.sleep(5)  # Back off on error


def _build_message(event) -> str:
    """Build Telegram message from queue event."""
    payload = event.payload or {}
    
    direction = str(payload.get("direction") or "").upper()
    icon = "🟢" if direction == "BUY" else "🔴"
    dir_mn = "ӨСӨХ (BUY)" if direction == "BUY" else "УНАХ (SELL)"
    
    entry = payload.get("entry", 0)
    sl = payload.get("sl", 0)
    tp = payload.get("tp", 0)
    rr = payload.get("rr", 0)
    score = payload.get("score", 0)
    regime = payload.get("regime", "")
    detectors = payload.get("detectors", [])
    
    det_str = ", ".join(detectors[:5]) if isinstance(detectors, list) else str(detectors or "")
    
    msg = (
        f"⚡ <b>{event.symbol}</b> – {dir_mn} {icon}\n"
        f"--------------------------------\n"
        f"🎯 <b>Entry:</b> {entry}\n"
        f"🛑 <b>SL:</b> {sl}\n"
        f"💵 <b>TP:</b> {tp}\n"
        f"⚖️ <b>RR:</b> {rr:.2f}\n"
        f"⏱ <b>TF:</b> {event.tf}\n\n"
        f"📊 <b>Score:</b> {score:.2f}\n"
        f"🎯 <b>Regime:</b> {regime}\n"
        f"🔍 <b>Detectors:</b> {det_str}\n\n"
        f"<i>#JKM_Bot #Signal</i>"
    )
    
    return msg


if __name__ == "__main__":
    main()

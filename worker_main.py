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
    WORKER_BURST_LIMIT: Max messages per user per tick (default: 3)
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


def _mask_id(uid: str) -> str:
    """Mask user/chat IDs for logging (never expose full IDs)."""
    if not uid or len(uid) < 4:
        return "***"
    return f"***{uid[-4:]}"


def _log_kv(event: str, **kv: Any) -> None:
    """Structured log output."""
    parts = [event]
    for k, v in kv.items():
        if v is not None:
            parts.append(f"{k}={v}")
    logger.info(" | ".join(parts))


def main() -> None:
    """Main worker loop."""
    
    # Config
    poll_interval = float(os.getenv("WORKER_POLL_INTERVAL_S", "2"))
    batch_size = int(os.getenv("WORKER_BATCH_SIZE", "50"))
    dry_run = str(os.getenv("WORKER_DRY_RUN", "0")).strip() == "1"
    burst_limit = int(os.getenv("WORKER_BURST_LIMIT", "3"))
    
    logger.info("=== JKM Worker Starting (v0.3) ===")
    logger.info(f"poll_interval={poll_interval}s batch_size={batch_size} dry_run={dry_run} burst_limit={burst_limit}")
    
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
        get_burst_count,
        increment_burst_count,
        cleanup_old_bursts,
    )
    
    try:
        init_db()
        logger.info("event_queue DB initialized")
    except Exception as e:
        logger.error(f"Failed to init event_queue DB: {e}")
        sys.exit(1)
    
    # Import user DB functions
    from user_db import list_users_with_telegram, init_db as init_user_db, get_user_quota
    
    try:
        init_user_db()
        logger.info("user_db initialized")
    except Exception as e:
        logger.warning(f"user_db init warning: {e}")
    
    # Import strategy store for symbol filtering
    from core.user_strategies_store import user_has_symbol_enabled, count_enabled_symbols
    
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
    total_filtered_symbol = 0
    total_filtered_burst = 0
    total_filtered_cooldown = 0
    total_filtered_quota = 0
    last_cleanup = 0
    cleanup_interval = 3600  # 1 hour
    
    _log_kv("WORKER_START", telegram_available=telegram_available, dry_run=dry_run, burst_limit=burst_limit)
    
    while True:
        try:
            # Periodic cleanup
            now = int(time.time())
            if now - last_cleanup > cleanup_interval:
                try:
                    d1 = cleanup_old_deliveries(older_than_days=7)
                    d2 = cleanup_old_tokens(older_than_days=7)
                    d3 = cleanup_old_bursts(older_than_hours=2)
                    if d1 or d2 or d3:
                        _log_kv("WORKER_CLEANUP", deliveries=d1, tokens=d2, bursts=d3)
                    last_cleanup = now
                except Exception:
                    pass
            
            # Claim events
            events = claim_events(limit=batch_size, lock_s=120)
            
            if events:
                stats = get_queue_stats()
                _log_kv("WORKER_CLAIM", count=len(events), queue_depth=stats.get("NEW", 0))
                
                # Get users with Telegram enabled
                tg_users = []
                try:
                    tg_users = list_users_with_telegram()
                except Exception as e:
                    logger.warning(f"Failed to get telegram users: {e}")
                
                for event in events:
                    try:
                        lag_s = int(time.time()) - event.created_ts
                        symbol = event.symbol.upper()
                        
                        # Derive tick_id from event (use scan_id from payload or created_ts bucket)
                        payload = event.payload or {}
                        tick_id = str(payload.get("scan_id") or str(event.created_ts // 60))
                        
                        # Candidate filtering stats for this event
                        candidates_count = len(tg_users)
                        matched_count = 0
                        burst_drop_count = 0
                        cooldown_drop_count = 0
                        symbol_drop_count = 0
                        quota_drop_count = 0
                        
                        sent_count = 0
                        for user in tg_users:
                            user_id = str(user.get("user_id") or "")
                            chat_id = str(user.get("chat_id") or "")
                            billing_status = str(user.get("billing_status") or "active")
                            
                            if not user_id or not chat_id:
                                continue
                            
                            # Filter 1: Billing status must be active
                            if billing_status != "active":
                                continue
                            
                            # Filter 2: Symbol must be enabled in user's strategies
                            if not user_has_symbol_enabled(user_id, symbol):
                                symbol_drop_count += 1
                                continue
                            
                            # Filter 3: Optional quota mismatch check
                            quota = get_user_quota(user_id)
                            allowed_pairs = quota.get("allowed_pairs", 5)
                            current_pairs = count_enabled_symbols(user_id)
                            if current_pairs != 999 and current_pairs > allowed_pairs:
                                # User has exceeded quota - log and skip
                                quota_drop_count += 1
                                continue
                            
                            # Filter 4: Cooldown (dedupe) check
                            if delivery_recent(user_id, event.setup_key):
                                cooldown_drop_count += 1
                                continue
                            
                            # Filter 5: Burst limit check
                            current_burst = get_burst_count(user_id, tick_id)
                            if current_burst >= burst_limit:
                                burst_drop_count += 1
                                continue
                            
                            # User passed all filters - send notification
                            matched_count += 1
                            
                            # Build message
                            msg = _build_message(event)
                            
                            # Send (or dry-run)
                            if dry_run or not telegram_available:
                                _log_kv(
                                    "NOTIFY_DRY_RUN",
                                    event_id=event.id[:8],
                                    user_id_masked=_mask_id(user_id),
                                    symbol=symbol,
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
                                increment_burst_count(user_id, tick_id)
                                sent_count += 1
                        
                        # Update totals
                        total_filtered_symbol += symbol_drop_count
                        total_filtered_burst += burst_drop_count
                        total_filtered_cooldown += cooldown_drop_count
                        total_filtered_quota += quota_drop_count
                        
                        # Mark event as done
                        mark_done(event.id)
                        total_processed += 1
                        total_sent += sent_count
                        
                        # Log with masked counts
                        _log_kv(
                            "WORKER_FILTER",
                            event_id=event.id[:8],
                            symbol=symbol,
                            candidates_count=candidates_count,
                            matched_count=matched_count,
                        )
                        
                        if burst_drop_count > 0:
                            _log_kv("WORKER_BURST_DROP", tick_id=tick_id[:12], dropped=burst_drop_count)
                        if cooldown_drop_count > 0:
                            _log_kv("WORKER_COOLDOWN_DROP", count=cooldown_drop_count)
                        
                        _log_kv(
                            "NOTIFY_SENT",
                            event_id=event.id[:8],
                            symbol=symbol,
                            sent_count=sent_count,
                            lag_s=lag_s,
                        )
                        
                    except Exception as e:
                        logger.error(f"Event processing error: {type(e).__name__}: {e}")
                        # Retry with exponential backoff
                        retry_s = min(60 * (2 ** min(event.attempts, 5)), 3600)
                        mark_failed(event.id, retry_after_s=retry_s)
                
                # Log queue stats periodically
                if total_processed % 50 == 0:
                    stats = get_queue_stats()
                    _log_kv(
                        "WORKER_STATS",
                        processed=total_processed,
                        sent=total_sent,
                        queue_depth=stats.get("NEW", 0),
                        filtered_symbol=total_filtered_symbol,
                        filtered_burst=total_filtered_burst,
                        filtered_cooldown=total_filtered_cooldown,
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

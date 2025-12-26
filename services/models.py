from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

class SignalEvent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pair: str
    direction: str  # "BUY" or "SELL"
    timeframe: str
    # NA-safe for visualization/persistence.
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    rr: Optional[float] = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reasons: List[str] = Field(default_factory=list)

    # Optional evidence payload for visualization (e.g. entry_zone bounds).
    evidence: Optional[Dict[str, Any]] = None

    # User-facing timezone offset in hours (e.g. +8 for Mongolia).
    # Engine/data stays UTC; this is only for formatting timestamps in notifications/UI.
    tz_offset_hours: int = 0

    # Engine selection label (e.g. "ma_v1", "indicator_free_v1")
    engine_version: str = ""
    
    # Optional raw context (e.g. analysis text or chart buffer placeholder)
    analysis_text: Optional[str] = None
    
class UserProfile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str = "default"
    risk_percent: float = 1.0
    min_rr: float = 2.0
    trend_tf: str = "D1"
    entry_tf: str = "M15"
    watch_pairs: List[str] = Field(default_factory=list)
    exclude_pairs: List[str] = Field(default_factory=list)
    note: Optional[str] = None

    # User local timezone offset, used for calendar-day STR updates and displaying times.
    tz_offset_hours: int = 8

    # Engine toggle (empty/omitted means default MA-based)
    engine_version: str = ""

    # If True: require clear structure trend before any signal.
    # If False: allow range-safe detectors when trend is unclear.
    require_clear_trend_for_signal: bool = False
    
    # Advanced settings (optional)
    use_fib: bool = True
    use_sr: bool = True

    # --- Quality / spam controls ---
    # Minimum score required to send a signal (0 disables).
    min_score: float = 0.0

    # Per-symbol daily cap (0 disables).
    max_signals_per_day_per_symbol: int = 20

    # Conflict handling when a symbol has an opposite-direction signal same day.
    # Supported: "skip" or "allow".
    conflict_policy: str = "skip"

    # Persistent cooldown window (minutes) for identical setup keys.
    cooldown_minutes: int = 30

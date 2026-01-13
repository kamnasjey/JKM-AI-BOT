"""
Strategy Tester Models - Core data structures for backtesting.

Features:
- No lookahead bias protection
- Intrabar ambiguity handling (SL_FIRST, TP_FIRST, BAR_MAGNIFIER)
- Realistic execution modeling (spread, slippage, commission)
- Full reproducibility (run_id, config_hash, data_hash)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Literal, Any
from enum import Enum
import hashlib
import json
import uuid
from datetime import datetime


class IntrabarPolicy(str, Enum):
    """How to resolve SL/TP ambiguity when both hit in the same bar."""
    SL_FIRST = "sl_first"      # Conservative: assume SL hit first
    TP_FIRST = "tp_first"      # Optimistic: assume TP hit first
    BAR_MAGNIFIER = "bar_magnifier"  # Use lower TF data to resolve
    RANDOM = "random"          # 50/50 random (for sensitivity analysis)


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeOutcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    OPEN = "open"  # Not yet resolved
    TIMEOUT = "timeout"  # Expired without hitting SL/TP


@dataclass
class TesterConfig:
    """Configuration for a strategy test run."""
    # Detector/Strategy config
    detectors: List[str]
    symbol: str
    entry_tf: str = "M15"
    trend_tf: str = "H4"
    
    # Test parameters
    start_date: Optional[str] = None  # ISO format: 2024-01-01
    end_date: Optional[str] = None
    
    # Execution parameters
    spread_pips: float = 1.0  # Average spread
    slippage_pips: float = 0.5  # Average slippage
    commission_per_trade: float = 0.0  # Commission in account currency
    
    # Position sizing (for equity curve)
    initial_capital: float = 10000.0
    risk_per_trade_pct: float = 1.0  # Risk 1% per trade
    
    # Intrabar handling
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.SL_FIRST
    
    # Filter settings
    min_rr: float = 2.0
    min_score: float = 1.0
    max_trades_per_day: int = 10
    
    # Timeout
    max_bars_in_trade: int = 100  # Max bars before forcing timeout
    
    def to_hash(self) -> str:
        """Create deterministic hash for config fingerprint."""
        data = {
            "detectors": sorted(self.detectors),
            "symbol": self.symbol,
            "entry_tf": self.entry_tf,
            "trend_tf": self.trend_tf,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "spread_pips": self.spread_pips,
            "slippage_pips": self.slippage_pips,
            "commission_per_trade": self.commission_per_trade,
            "intrabar_policy": self.intrabar_policy.value if isinstance(self.intrabar_policy, IntrabarPolicy) else self.intrabar_policy,
            "min_rr": self.min_rr,
            "min_score": self.min_score,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class TradeResult:
    """Result of a single trade."""
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # Entry details
    entry_time: int = 0  # Epoch seconds
    entry_price: float = 0.0
    direction: TradeDirection = TradeDirection.LONG
    detector: str = ""
    signal_id: Optional[str] = None
    
    # Exit details
    exit_time: Optional[int] = None
    exit_price: Optional[float] = None
    
    # Trade parameters
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_pips: float = 0.0
    reward_pips: float = 0.0
    rr_ratio: float = 0.0
    
    # Execution costs
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    commission: float = 0.0
    
    # Outcome
    outcome: TradeOutcome = TradeOutcome.OPEN
    pnl_pips: float = 0.0
    pnl_usd: float = 0.0
    bars_in_trade: int = 0
    
    # Evidence for analysis
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_closed(self) -> bool:
        return self.outcome != TradeOutcome.OPEN
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "direction": self.direction.value if isinstance(self.direction, TradeDirection) else self.direction,
            "detector": self.detector,
            "signal_id": self.signal_id,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_pips": self.risk_pips,
            "reward_pips": self.reward_pips,
            "rr_ratio": self.rr_ratio,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "commission": self.commission,
            "outcome": self.outcome.value if isinstance(self.outcome, TradeOutcome) else self.outcome,
            "pnl_pips": self.pnl_pips,
            "pnl_usd": self.pnl_usd,
            "bars_in_trade": self.bars_in_trade,
            "evidence": self.evidence,
        }


@dataclass
class EquityPoint:
    """Single point in equity curve."""
    timestamp: int  # Epoch seconds
    equity: float
    drawdown: float
    trade_id: Optional[str] = None


@dataclass
class EquityCurve:
    """Full equity curve with metrics."""
    points: List[EquityPoint] = field(default_factory=list)
    
    @property
    def peak_equity(self) -> float:
        if not self.points:
            return 0.0
        return max(p.equity for p in self.points)
    
    @property
    def max_drawdown(self) -> float:
        if not self.points:
            return 0.0
        return min(p.drawdown for p in self.points)
    
    @property
    def final_equity(self) -> float:
        if not self.points:
            return 0.0
        return self.points[-1].equity
    
    def to_list(self) -> List[Dict[str, Any]]:
        return [
            {"timestamp": p.timestamp, "equity": p.equity, "drawdown": p.drawdown, "trade_id": p.trade_id}
            for p in self.points
        ]


@dataclass
class TesterMetrics:
    """Aggregated metrics for a test run."""
    # Basic stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    timeout_trades: int = 0
    
    # Win rate
    win_rate: float = 0.0
    
    # Profit metrics
    total_pnl_pips: float = 0.0
    total_pnl_usd: float = 0.0
    avg_win_pips: float = 0.0
    avg_loss_pips: float = 0.0
    profit_factor: float = 0.0
    
    # Risk metrics
    max_drawdown_pct: float = 0.0
    max_drawdown_usd: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    
    # Execution stats
    total_spread_cost: float = 0.0
    total_slippage_cost: float = 0.0
    total_commission: float = 0.0
    avg_bars_in_trade: float = 0.0
    
    # Time analysis
    avg_rr_achieved: float = 0.0
    best_trade_pips: float = 0.0
    worst_trade_pips: float = 0.0
    
    # Detector breakdown
    detector_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "breakeven_trades": self.breakeven_trades,
            "timeout_trades": self.timeout_trades,
            "win_rate": round(self.win_rate, 4),
            "total_pnl_pips": round(self.total_pnl_pips, 2),
            "total_pnl_usd": round(self.total_pnl_usd, 2),
            "avg_win_pips": round(self.avg_win_pips, 2),
            "avg_loss_pips": round(self.avg_loss_pips, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "max_drawdown_usd": round(self.max_drawdown_usd, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "total_spread_cost": round(self.total_spread_cost, 2),
            "total_slippage_cost": round(self.total_slippage_cost, 2),
            "total_commission": round(self.total_commission, 2),
            "avg_bars_in_trade": round(self.avg_bars_in_trade, 1),
            "avg_rr_achieved": round(self.avg_rr_achieved, 2),
            "best_trade_pips": round(self.best_trade_pips, 2),
            "worst_trade_pips": round(self.worst_trade_pips, 2),
            "detector_stats": self.detector_stats,
        }


@dataclass
class TesterRun:
    """Complete test run with all results."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Config fingerprints
    config: Optional[TesterConfig] = None
    config_hash: str = ""
    data_hash: str = ""  # Hash of candle data used
    
    # Status
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    error: Optional[str] = None
    progress_pct: float = 0.0
    
    # Results
    trades: List[TradeResult] = field(default_factory=list)
    equity_curve: Optional[EquityCurve] = None
    metrics: Optional[TesterMetrics] = None
    
    # Timing
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "config_hash": self.config_hash,
            "data_hash": self.data_hash,
            "status": self.status,
            "error": self.error,
            "progress_pct": self.progress_pct,
            "trade_count": len(self.trades),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
        }
    
    def to_full_dict(self) -> Dict[str, Any]:
        """Full dict including trades and equity curve."""
        result = self.to_dict()
        result["trades"] = [t.to_dict() for t in self.trades]
        result["equity_curve"] = self.equity_curve.to_list() if self.equity_curve else []
        return result

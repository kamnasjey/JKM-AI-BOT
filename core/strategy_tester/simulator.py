"""
Strategy Simulator - Main backtesting engine.

Walks through candle data bar-by-bar, runs detectors, and simulates trade execution.
"""

import hashlib
import json
import time
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass

from .models import (
    TesterConfig,
    TesterRun,
    TradeResult,
    TradeDirection,
    TradeOutcome,
    EquityCurve,
    EquityPoint,
    TesterMetrics,
    IntrabarPolicy,
)
from .execution import ExecutionEngine, Candle


class StrategySimulator:
    """
    Main backtesting simulator with no lookahead bias.
    
    Walk-forward approach:
    1. For each bar, only data up to and including that bar is available
    2. Signals generated at bar close are entered at next bar open
    3. SL/TP checked bar-by-bar
    4. Intrabar ambiguity resolved according to policy
    """
    
    def __init__(
        self,
        config: TesterConfig,
        detector_fn: Optional[Callable] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ):
        """
        Initialize simulator.
        
        Args:
            config: Tester configuration
            detector_fn: Function to run detectors. Signature:
                         detector_fn(candles: List[dict], idx: int) -> Optional[dict]
                         Returns signal dict if detector fires, None otherwise
            progress_callback: Optional callback for progress updates
        """
        self.config = config
        self.detector_fn = detector_fn
        self.progress_callback = progress_callback
        self.execution = ExecutionEngine(config)
    
    def run(self, candles: List[Dict[str, Any]]) -> TesterRun:
        """
        Run the backtest on candle data.
        
        Args:
            candles: List of candle dicts with keys: time, open, high, low, close, volume
                     Must be sorted by time ascending
        
        Returns:
            TesterRun with all trades and metrics
        """
        run = TesterRun(config=self.config)
        run.config_hash = self.config.to_hash()
        run.data_hash = self._compute_data_hash(candles)
        run.status = "running"
        run.started_at = datetime.utcnow().isoformat()
        
        start_time = time.time()
        
        try:
            # Convert to Candle objects
            candle_objs = [self._dict_to_candle(c) for c in candles]
            
            # Filter by date range if specified
            candle_objs = self._filter_date_range(candle_objs)
            
            if len(candle_objs) < 50:
                run.status = "failed"
                run.error = "Insufficient candle data (need at least 50 bars)"
                return run
            
            # Run walk-forward simulation
            trades, equity = self._walk_forward(candle_objs)
            
            # Calculate metrics
            metrics = self._calculate_metrics(trades, equity)
            
            run.trades = trades
            run.equity_curve = equity
            run.metrics = metrics
            run.status = "completed"
            run.progress_pct = 100.0
            
        except Exception as e:
            run.status = "failed"
            run.error = str(e)
        
        run.completed_at = datetime.utcnow().isoformat()
        run.duration_seconds = time.time() - start_time
        
        return run
    
    def _walk_forward(
        self, candles: List[Candle]
    ) -> tuple[List[TradeResult], EquityCurve]:
        """
        Walk-forward simulation with no lookahead.
        """
        trades: List[TradeResult] = []
        open_trades: List[TradeResult] = []
        equity = self.config.initial_capital
        peak_equity = equity
        
        equity_curve = EquityCurve()
        equity_curve.points.append(EquityPoint(
            timestamp=candles[0].time,
            equity=equity,
            drawdown=0.0,
        ))
        
        # Signals pending entry (generated on bar close, enter next bar open)
        pending_signals: List[Dict[str, Any]] = []
        
        # Track trades per day for limit
        trades_today: Dict[str, int] = {}
        
        total_bars = len(candles)
        
        for i in range(50, total_bars):  # Start at 50 to have enough history
            candle = candles[i]
            prev_candle = candles[i - 1]
            
            # Progress update
            if self.progress_callback and i % 100 == 0:
                self.progress_callback((i / total_bars) * 100)
            
            # 1. Enter pending signals at this bar's open
            for sig in pending_signals:
                trade = self.execution.create_trade_from_signal(sig, candle)
                
                # Check RR filter
                if trade.rr_ratio < self.config.min_rr:
                    continue
                
                # Check daily trade limit
                day_key = datetime.utcfromtimestamp(candle.time).strftime("%Y-%m-%d")
                if trades_today.get(day_key, 0) >= self.config.max_trades_per_day:
                    continue
                
                open_trades.append(trade)
                trades_today[day_key] = trades_today.get(day_key, 0) + 1
            
            pending_signals = []
            
            # 2. Check SL/TP on open trades
            still_open = []
            for trade in open_trades:
                trade.bars_in_trade += 1
                
                # Check timeout
                if trade.bars_in_trade >= self.config.max_bars_in_trade:
                    closed = self.execution.close_trade(trade, candle, TradeOutcome.TIMEOUT)
                    trades.append(closed)
                    equity += closed.pnl_usd
                    continue
                
                # Check SL/TP hit
                outcome = self.execution.check_sl_tp_hit(trade, candle)
                
                if outcome is not None:
                    closed = self.execution.close_trade(trade, candle, outcome)
                    trades.append(closed)
                    equity += closed.pnl_usd
                    
                    # Update equity curve
                    peak_equity = max(peak_equity, equity)
                    drawdown = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0
                    equity_curve.points.append(EquityPoint(
                        timestamp=candle.time,
                        equity=equity,
                        drawdown=drawdown,
                        trade_id=closed.trade_id,
                    ))
                else:
                    still_open.append(trade)
            
            open_trades = still_open
            
            # 3. Run detectors at bar close (signals enter next bar)
            if self.detector_fn:
                # Build candle history up to this point (no lookahead)
                history = [self._candle_to_dict(c) for c in candles[:i+1]]
                
                # Run detector on current bar
                signal = self.detector_fn(history, i)
                
                if signal:
                    pending_signals.append(signal)
        
        # Close any remaining open trades at last bar
        for trade in open_trades:
            closed = self.execution.close_trade(trade, candles[-1], TradeOutcome.TIMEOUT)
            trades.append(closed)
        
        return trades, equity_curve
    
    def _calculate_metrics(
        self, trades: List[TradeResult], equity: EquityCurve
    ) -> TesterMetrics:
        """Calculate aggregated metrics from trade results."""
        if not trades:
            return TesterMetrics()
        
        metrics = TesterMetrics()
        metrics.total_trades = len(trades)
        
        # Count outcomes
        wins = [t for t in trades if t.outcome == TradeOutcome.WIN]
        losses = [t for t in trades if t.outcome == TradeOutcome.LOSS]
        breakevens = [t for t in trades if t.outcome == TradeOutcome.BREAKEVEN]
        timeouts = [t for t in trades if t.outcome == TradeOutcome.TIMEOUT]
        
        metrics.winning_trades = len(wins)
        metrics.losing_trades = len(losses)
        metrics.breakeven_trades = len(breakevens)
        metrics.timeout_trades = len(timeouts)
        
        # Win rate
        if metrics.total_trades > 0:
            metrics.win_rate = metrics.winning_trades / metrics.total_trades
        
        # PnL
        metrics.total_pnl_pips = sum(t.pnl_pips for t in trades)
        metrics.total_pnl_usd = sum(t.pnl_usd for t in trades)
        
        # Average win/loss
        if wins:
            metrics.avg_win_pips = sum(t.pnl_pips for t in wins) / len(wins)
        if losses:
            metrics.avg_loss_pips = sum(t.pnl_pips for t in losses) / len(losses)
        
        # Profit factor
        gross_profit = sum(t.pnl_usd for t in trades if t.pnl_usd > 0)
        gross_loss = abs(sum(t.pnl_usd for t in trades if t.pnl_usd < 0))
        if gross_loss > 0:
            metrics.profit_factor = gross_profit / gross_loss
        
        # Drawdown
        if equity.points:
            metrics.max_drawdown_pct = abs(equity.max_drawdown)
            peak = max(p.equity for p in equity.points)
            trough = min(p.equity for p in equity.points)
            metrics.max_drawdown_usd = peak - trough
        
        # Execution costs
        metrics.total_spread_cost = sum(t.spread_cost for t in trades)
        metrics.total_slippage_cost = sum(t.slippage_cost for t in trades)
        metrics.total_commission = sum(t.commission for t in trades)
        
        # Bars in trade
        if trades:
            metrics.avg_bars_in_trade = sum(t.bars_in_trade for t in trades) / len(trades)
        
        # RR achieved
        if wins:
            metrics.avg_rr_achieved = sum(t.rr_ratio for t in wins) / len(wins)
        
        # Best/worst
        if trades:
            metrics.best_trade_pips = max(t.pnl_pips for t in trades)
            metrics.worst_trade_pips = min(t.pnl_pips for t in trades)
        
        # Sharpe/Sortino ratios
        metrics.sharpe_ratio = self._calculate_sharpe(trades)
        metrics.sortino_ratio = self._calculate_sortino(trades)
        
        # Detector breakdown
        detector_trades: Dict[str, List[TradeResult]] = {}
        for t in trades:
            det = t.detector
            if det not in detector_trades:
                detector_trades[det] = []
            detector_trades[det].append(t)
        
        for det, det_trades in detector_trades.items():
            det_wins = len([t for t in det_trades if t.outcome == TradeOutcome.WIN])
            det_total = len(det_trades)
            metrics.detector_stats[det] = {
                "total_trades": det_total,
                "wins": det_wins,
                "win_rate": det_wins / det_total if det_total > 0 else 0,
                "pnl_pips": sum(t.pnl_pips for t in det_trades),
                "pnl_usd": sum(t.pnl_usd for t in det_trades),
            }
        
        return metrics
    
    def _calculate_sharpe(self, trades: List[TradeResult], risk_free_rate: float = 0.0) -> float:
        """Calculate Sharpe ratio from trade returns."""
        if len(trades) < 2:
            return 0.0
        
        returns = [t.pnl_usd for t in trades]
        mean_return = sum(returns) / len(returns)
        
        # Standard deviation
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            return 0.0
        
        return (mean_return - risk_free_rate) / std_dev
    
    def _calculate_sortino(self, trades: List[TradeResult], target_return: float = 0.0) -> float:
        """Calculate Sortino ratio (only downside deviation)."""
        if len(trades) < 2:
            return 0.0
        
        returns = [t.pnl_usd for t in trades]
        mean_return = sum(returns) / len(returns)
        
        # Downside deviation (only negative returns)
        downside_returns = [r for r in returns if r < target_return]
        if not downside_returns:
            return float('inf') if mean_return > 0 else 0.0
        
        downside_variance = sum((r - target_return) ** 2 for r in downside_returns) / len(downside_returns)
        downside_dev = downside_variance ** 0.5
        
        if downside_dev == 0:
            return 0.0
        
        return (mean_return - target_return) / downside_dev
    
    def _compute_data_hash(self, candles: List[Dict[str, Any]]) -> str:
        """Compute hash of candle data for reproducibility."""
        if not candles:
            return "empty"
        
        # Hash first, last, and middle candles plus count
        summary = {
            "count": len(candles),
            "first": candles[0],
            "last": candles[-1],
            "mid": candles[len(candles) // 2] if len(candles) > 2 else None,
        }
        return hashlib.sha256(json.dumps(summary, sort_keys=True, default=str).encode()).hexdigest()[:16]
    
    def _filter_date_range(self, candles: List[Candle]) -> List[Candle]:
        """Filter candles by configured date range."""
        if not self.config.start_date and not self.config.end_date:
            return candles
        
        result = candles
        
        if self.config.start_date:
            try:
                start_ts = datetime.fromisoformat(self.config.start_date).timestamp()
                result = [c for c in result if c.time >= start_ts]
            except:
                pass
        
        if self.config.end_date:
            try:
                end_ts = datetime.fromisoformat(self.config.end_date).timestamp()
                result = [c for c in result if c.time <= end_ts]
            except:
                pass
        
        return result
    
    def _dict_to_candle(self, d: Dict[str, Any]) -> Candle:
        """Convert dict to Candle object."""
        return Candle(
            time=int(d.get("time", d.get("t", 0))),
            open=float(d.get("open", d.get("o", 0))),
            high=float(d.get("high", d.get("h", 0))),
            low=float(d.get("low", d.get("l", 0))),
            close=float(d.get("close", d.get("c", 0))),
            volume=float(d.get("volume", d.get("v", 0))),
        )
    
    def _candle_to_dict(self, c: Candle) -> Dict[str, Any]:
        """Convert Candle object to dict."""
        return {
            "time": c.time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }

"""
Tester Storage - Persistence for test runs.

Stores test runs in state/tester_runs/ as JSON files.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import TesterRun, TesterConfig, TradeResult, EquityCurve, TesterMetrics, EquityPoint


class TesterStorage:
    """
    Storage for test runs.
    Each run is stored as a JSON file in state/tester_runs/{run_id}.json
    """
    
    def __init__(self, base_dir: str = "state/tester_runs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, run: TesterRun) -> bool:
        """Save a test run to disk."""
        try:
            path = self.base_dir / f"{run.run_id}.json"
            data = run.to_full_dict()
            
            # Also save config details
            if run.config:
                data["config_details"] = {
                    "detectors": run.config.detectors,
                    "symbol": run.config.symbol,
                    "entry_tf": run.config.entry_tf,
                    "trend_tf": run.config.trend_tf,
                    "start_date": run.config.start_date,
                    "end_date": run.config.end_date,
                    "spread_pips": run.config.spread_pips,
                    "slippage_pips": run.config.slippage_pips,
                    "commission_per_trade": run.config.commission_per_trade,
                    "initial_capital": run.config.initial_capital,
                    "risk_per_trade_pct": run.config.risk_per_trade_pct,
                    "intrabar_policy": run.config.intrabar_policy.value if hasattr(run.config.intrabar_policy, 'value') else run.config.intrabar_policy,
                    "min_rr": run.config.min_rr,
                    "min_score": run.config.min_score,
                    "max_trades_per_day": run.config.max_trades_per_day,
                    "max_bars_in_trade": run.config.max_bars_in_trade,
                }
            
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            
            return True
        except Exception as e:
            print(f"[TesterStorage] save error: {e}")
            return False
    
    def save_simple(self, run_id: str, data: Dict[str, Any]) -> bool:
        """Save a simple run result (for simplified API)."""
        try:
            path = self.base_dir / f"{run_id}.json"
            data["created_at"] = datetime.now().isoformat()
            
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            
            return True
        except Exception as e:
            print(f"[TesterStorage] save_simple error: {e}")
            return False
    
    def load(self, run_id: str) -> Optional[TesterRun]:
        """Load a test run from disk."""
        try:
            path = self.base_dir / f"{run_id}.json"
            if not path.exists():
                return None
            
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            return self._dict_to_run(data)
        except Exception as e:
            print(f"[TesterStorage] load error: {e}")
            return None
    
    def list_runs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List all test runs (summary only, no trades)."""
        runs = []
        
        try:
            files = sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            
            for path in files[offset:offset + limit]:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Return summary only
                    runs.append({
                        "run_id": data.get("run_id"),
                        "created_at": data.get("created_at"),
                        "status": data.get("status"),
                        "trade_count": data.get("trade_count", len(data.get("trades", []))),
                        "config_hash": data.get("config_hash"),
                        "data_hash": data.get("data_hash"),
                        "metrics": data.get("metrics"),
                        "duration_seconds": data.get("duration_seconds"),
                        "config_details": data.get("config_details"),
                    })
                except:
                    continue
        except Exception as e:
            print(f"[TesterStorage] list error: {e}")
        
        return runs
    
    def delete(self, run_id: str) -> bool:
        """Delete a test run."""
        try:
            path = self.base_dir / f"{run_id}.json"
            if path.exists():
                path.unlink()
                return True
            return False
        except Exception as e:
            print(f"[TesterStorage] delete error: {e}")
            return False
    
    def get_trades(self, run_id: str) -> List[Dict[str, Any]]:
        """Get just the trades for a run."""
        run = self.load(run_id)
        if run:
            return [t.to_dict() for t in run.trades]
        return []
    
    def get_equity_curve(self, run_id: str) -> List[Dict[str, Any]]:
        """Get just the equity curve for a run."""
        try:
            path = self.base_dir / f"{run_id}.json"
            if not path.exists():
                return []
            
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            return data.get("equity_curve", [])
        except Exception as e:
            print(f"[TesterStorage] get_equity error: {e}")
            return []
    
    def _dict_to_run(self, data: Dict[str, Any]) -> TesterRun:
        """Convert dict back to TesterRun object."""
        run = TesterRun()
        run.run_id = data.get("run_id", run.run_id)
        run.created_at = data.get("created_at", run.created_at)
        run.config_hash = data.get("config_hash", "")
        run.data_hash = data.get("data_hash", "")
        run.status = data.get("status", "completed")
        run.error = data.get("error")
        run.progress_pct = data.get("progress_pct", 100.0)
        run.started_at = data.get("started_at")
        run.completed_at = data.get("completed_at")
        run.duration_seconds = data.get("duration_seconds", 0.0)
        
        # Convert trades
        run.trades = []
        for t in data.get("trades", []):
            trade = TradeResult()
            trade.trade_id = t.get("trade_id", trade.trade_id)
            trade.entry_time = t.get("entry_time", 0)
            trade.entry_price = t.get("entry_price", 0.0)
            trade.direction = t.get("direction", "long")
            trade.detector = t.get("detector", "")
            trade.signal_id = t.get("signal_id")
            trade.exit_time = t.get("exit_time")
            trade.exit_price = t.get("exit_price")
            trade.stop_loss = t.get("stop_loss", 0.0)
            trade.take_profit = t.get("take_profit", 0.0)
            trade.risk_pips = t.get("risk_pips", 0.0)
            trade.reward_pips = t.get("reward_pips", 0.0)
            trade.rr_ratio = t.get("rr_ratio", 0.0)
            trade.spread_cost = t.get("spread_cost", 0.0)
            trade.slippage_cost = t.get("slippage_cost", 0.0)
            trade.commission = t.get("commission", 0.0)
            trade.outcome = t.get("outcome", "open")
            trade.pnl_pips = t.get("pnl_pips", 0.0)
            trade.pnl_usd = t.get("pnl_usd", 0.0)
            trade.bars_in_trade = t.get("bars_in_trade", 0)
            trade.evidence = t.get("evidence", {})
            run.trades.append(trade)
        
        # Convert equity curve
        eq_data = data.get("equity_curve", [])
        if eq_data:
            run.equity_curve = EquityCurve()
            for p in eq_data:
                run.equity_curve.points.append(EquityPoint(
                    timestamp=p.get("timestamp", 0),
                    equity=p.get("equity", 0.0),
                    drawdown=p.get("drawdown", 0.0),
                    trade_id=p.get("trade_id"),
                ))
        
        # Convert metrics
        m = data.get("metrics")
        if m:
            run.metrics = TesterMetrics()
            run.metrics.total_trades = m.get("total_trades", 0)
            run.metrics.winning_trades = m.get("winning_trades", 0)
            run.metrics.losing_trades = m.get("losing_trades", 0)
            run.metrics.breakeven_trades = m.get("breakeven_trades", 0)
            run.metrics.timeout_trades = m.get("timeout_trades", 0)
            run.metrics.win_rate = m.get("win_rate", 0.0)
            run.metrics.total_pnl_pips = m.get("total_pnl_pips", 0.0)
            run.metrics.total_pnl_usd = m.get("total_pnl_usd", 0.0)
            run.metrics.avg_win_pips = m.get("avg_win_pips", 0.0)
            run.metrics.avg_loss_pips = m.get("avg_loss_pips", 0.0)
            run.metrics.profit_factor = m.get("profit_factor", 0.0)
            run.metrics.max_drawdown_pct = m.get("max_drawdown_pct", 0.0)
            run.metrics.max_drawdown_usd = m.get("max_drawdown_usd", 0.0)
            run.metrics.sharpe_ratio = m.get("sharpe_ratio", 0.0)
            run.metrics.sortino_ratio = m.get("sortino_ratio", 0.0)
            run.metrics.total_spread_cost = m.get("total_spread_cost", 0.0)
            run.metrics.total_slippage_cost = m.get("total_slippage_cost", 0.0)
            run.metrics.total_commission = m.get("total_commission", 0.0)
            run.metrics.avg_bars_in_trade = m.get("avg_bars_in_trade", 0.0)
            run.metrics.avg_rr_achieved = m.get("avg_rr_achieved", 0.0)
            run.metrics.best_trade_pips = m.get("best_trade_pips", 0.0)
            run.metrics.worst_trade_pips = m.get("worst_trade_pips", 0.0)
            run.metrics.detector_stats = m.get("detector_stats", {})
        
        # Restore config if details available
        cfg = data.get("config_details")
        if cfg:
            from .models import IntrabarPolicy
            run.config = TesterConfig(
                detectors=cfg.get("detectors", []),
                symbol=cfg.get("symbol", ""),
                entry_tf=cfg.get("entry_tf", "M15"),
                trend_tf=cfg.get("trend_tf", "H4"),
                start_date=cfg.get("start_date"),
                end_date=cfg.get("end_date"),
                spread_pips=cfg.get("spread_pips", 1.0),
                slippage_pips=cfg.get("slippage_pips", 0.5),
                commission_per_trade=cfg.get("commission_per_trade", 0.0),
                initial_capital=cfg.get("initial_capital", 10000.0),
                risk_per_trade_pct=cfg.get("risk_per_trade_pct", 1.0),
                intrabar_policy=IntrabarPolicy(cfg.get("intrabar_policy", "sl_first")),
                min_rr=cfg.get("min_rr", 2.0),
                min_score=cfg.get("min_score", 1.0),
                max_trades_per_day=cfg.get("max_trades_per_day", 10),
                max_bars_in_trade=cfg.get("max_bars_in_trade", 100),
            )
        
        return run

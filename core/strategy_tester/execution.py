"""
Execution Engine - Handles realistic trade execution and SL/TP checking.

Features:
- No lookahead bias: only uses data available at decision time
- Intrabar ambiguity resolution (SL_FIRST, TP_FIRST, BAR_MAGNIFIER)
- Realistic spread/slippage modeling
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any
import random

from .models import (
    TesterConfig,
    TradeResult,
    TradeDirection,
    TradeOutcome,
    IntrabarPolicy,
)


@dataclass
class Candle:
    """Simple candle structure for execution engine."""
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def get_pip_value(symbol: str) -> float:
    """Get pip value for a symbol."""
    symbol = symbol.upper()
    if "JPY" in symbol:
        return 0.01
    elif "XAU" in symbol or "GOLD" in symbol:
        return 0.1
    elif "BTC" in symbol:
        return 1.0
    else:
        return 0.0001


class ExecutionEngine:
    """
    Handles trade execution with realistic modeling.
    
    Key principles:
    1. No lookahead - entry happens at next bar open after signal
    2. Spread applied at entry (widening entry price adversely)
    3. Slippage modeled as random adverse movement
    4. Commission deducted from PnL
    """
    
    def __init__(self, config: TesterConfig):
        self.config = config
        self.pip_value = get_pip_value(config.symbol)
    
    def apply_entry_costs(
        self,
        entry_price: float,
        direction: TradeDirection,
    ) -> Tuple[float, float, float]:
        """
        Apply spread and slippage to entry price.
        Returns: (adjusted_price, spread_cost, slippage_cost)
        """
        spread_pips = self.config.spread_pips
        slippage_pips = self.config.slippage_pips
        
        # Spread: always adverse (long = higher entry, short = lower entry)
        spread_adj = spread_pips * self.pip_value
        
        # Slippage: random adverse up to configured amount
        slippage_adj = random.uniform(0, slippage_pips) * self.pip_value
        
        if direction == TradeDirection.LONG:
            adjusted_price = entry_price + spread_adj + slippage_adj
        else:  # SHORT
            adjusted_price = entry_price - spread_adj - slippage_adj
        
        spread_cost = spread_pips
        slippage_cost = slippage_adj / self.pip_value if self.pip_value > 0 else 0
        
        return adjusted_price, spread_cost, slippage_cost
    
    def check_sl_tp_hit(
        self,
        trade: TradeResult,
        candle: Candle,
        lower_tf_candles: Optional[List[Candle]] = None,
    ) -> Optional[TradeOutcome]:
        """
        Check if SL or TP was hit in the candle.
        Handles intrabar ambiguity based on policy.
        
        Returns: TradeOutcome if trade is closed, None if still open
        """
        sl = trade.stop_loss
        tp = trade.take_profit
        direction = trade.direction
        
        # Check if SL hit
        sl_hit = False
        if direction == TradeDirection.LONG:
            sl_hit = candle.low <= sl
        else:  # SHORT
            sl_hit = candle.high >= sl
        
        # Check if TP hit
        tp_hit = False
        if direction == TradeDirection.LONG:
            tp_hit = candle.high >= tp
        else:  # SHORT
            tp_hit = candle.low <= tp
        
        # Neither hit
        if not sl_hit and not tp_hit:
            return None
        
        # Only one hit - clear outcome
        if sl_hit and not tp_hit:
            return TradeOutcome.LOSS
        if tp_hit and not sl_hit:
            return TradeOutcome.WIN
        
        # Both hit in same bar - ambiguity
        return self._resolve_intrabar_ambiguity(
            trade, candle, lower_tf_candles
        )
    
    def _resolve_intrabar_ambiguity(
        self,
        trade: TradeResult,
        candle: Candle,
        lower_tf_candles: Optional[List[Candle]] = None,
    ) -> TradeOutcome:
        """Resolve SL/TP ambiguity when both hit in same bar."""
        policy = self.config.intrabar_policy
        
        if policy == IntrabarPolicy.SL_FIRST:
            return TradeOutcome.LOSS
        
        elif policy == IntrabarPolicy.TP_FIRST:
            return TradeOutcome.WIN
        
        elif policy == IntrabarPolicy.RANDOM:
            return TradeOutcome.WIN if random.random() > 0.5 else TradeOutcome.LOSS
        
        elif policy == IntrabarPolicy.BAR_MAGNIFIER:
            return self._bar_magnifier_resolve(trade, candle, lower_tf_candles)
        
        # Default to conservative
        return TradeOutcome.LOSS
    
    def _bar_magnifier_resolve(
        self,
        trade: TradeResult,
        candle: Candle,
        lower_tf_candles: Optional[List[Candle]] = None,
    ) -> TradeOutcome:
        """
        Use lower timeframe data to resolve ambiguity.
        If no lower TF data available, use OHLC order heuristic.
        """
        sl = trade.stop_loss
        tp = trade.take_profit
        direction = trade.direction
        
        # If we have lower TF candles, scan them in order
        if lower_tf_candles:
            for ltf_candle in lower_tf_candles:
                if direction == TradeDirection.LONG:
                    if ltf_candle.low <= sl:
                        return TradeOutcome.LOSS
                    if ltf_candle.high >= tp:
                        return TradeOutcome.WIN
                else:  # SHORT
                    if ltf_candle.high >= sl:
                        return TradeOutcome.LOSS
                    if ltf_candle.low <= tp:
                        return TradeOutcome.WIN
            # Didn't resolve - shouldn't happen if data is correct
            return TradeOutcome.LOSS
        
        # Fallback: OHLC order heuristic
        # If open is closer to one level, assume that hit first
        o, h, l, c = candle.open, candle.high, candle.low, candle.close
        
        if direction == TradeDirection.LONG:
            dist_to_sl = abs(o - sl)
            dist_to_tp = abs(o - tp)
            # If price opened closer to SL, assume SL hit first
            if dist_to_sl < dist_to_tp:
                return TradeOutcome.LOSS
            else:
                return TradeOutcome.WIN
        else:  # SHORT
            dist_to_sl = abs(o - sl)
            dist_to_tp = abs(o - tp)
            if dist_to_sl < dist_to_tp:
                return TradeOutcome.LOSS
            else:
                return TradeOutcome.WIN
    
    def calculate_pnl(
        self,
        trade: TradeResult,
        exit_price: float,
    ) -> Tuple[float, float]:
        """
        Calculate PnL in pips and USD.
        Returns: (pnl_pips, pnl_usd)
        """
        entry = trade.entry_price
        direction = trade.direction
        
        if direction == TradeDirection.LONG:
            pnl_pips = (exit_price - entry) / self.pip_value if self.pip_value > 0 else 0
        else:  # SHORT
            pnl_pips = (entry - exit_price) / self.pip_value if self.pip_value > 0 else 0
        
        # Deduct execution costs
        pnl_pips -= trade.spread_cost + trade.slippage_cost
        
        # Convert to USD (simplified - uses risk per trade)
        # In real implementation, this would use position size
        risk_amount = self.config.initial_capital * (self.config.risk_per_trade_pct / 100)
        
        if trade.risk_pips > 0:
            pnl_usd = (pnl_pips / trade.risk_pips) * risk_amount
        else:
            pnl_usd = 0.0
        
        # Deduct commission
        pnl_usd -= self.config.commission_per_trade
        
        return pnl_pips, pnl_usd
    
    def close_trade(
        self,
        trade: TradeResult,
        candle: Candle,
        outcome: TradeOutcome,
    ) -> TradeResult:
        """Close a trade with final PnL calculation."""
        trade.exit_time = candle.time
        trade.outcome = outcome
        
        # Determine exit price based on outcome
        if outcome == TradeOutcome.WIN:
            trade.exit_price = trade.take_profit
        elif outcome == TradeOutcome.LOSS:
            trade.exit_price = trade.stop_loss
        elif outcome == TradeOutcome.TIMEOUT:
            trade.exit_price = candle.close
        elif outcome == TradeOutcome.BREAKEVEN:
            trade.exit_price = trade.entry_price
        else:
            trade.exit_price = candle.close
        
        # Calculate PnL
        trade.pnl_pips, trade.pnl_usd = self.calculate_pnl(trade, trade.exit_price)
        
        return trade
    
    def create_trade_from_signal(
        self,
        signal: Dict[str, Any],
        entry_candle: Candle,
    ) -> TradeResult:
        """
        Create a TradeResult from a detector signal.
        Entry is at next bar open after signal (no lookahead).
        """
        direction_str = signal.get("direction", "long").lower()
        direction = TradeDirection.LONG if direction_str in ("long", "buy", "up") else TradeDirection.SHORT
        
        # Entry at bar open (signal was generated on previous bar close)
        raw_entry = entry_candle.open
        
        # Apply execution costs
        adj_entry, spread_cost, slippage_cost = self.apply_entry_costs(raw_entry, direction)
        
        # Get SL/TP from signal
        sl = signal.get("sl", signal.get("stop_loss", 0.0))
        tp = signal.get("tp", signal.get("take_profit", 0.0))
        
        # Calculate risk/reward
        if direction == TradeDirection.LONG:
            risk_pips = (adj_entry - sl) / self.pip_value if self.pip_value > 0 else 0
            reward_pips = (tp - adj_entry) / self.pip_value if self.pip_value > 0 else 0
        else:
            risk_pips = (sl - adj_entry) / self.pip_value if self.pip_value > 0 else 0
            reward_pips = (adj_entry - tp) / self.pip_value if self.pip_value > 0 else 0
        
        rr_ratio = reward_pips / risk_pips if risk_pips > 0 else 0.0
        
        trade = TradeResult(
            entry_time=entry_candle.time,
            entry_price=adj_entry,
            direction=direction,
            detector=signal.get("detector", "unknown"),
            signal_id=signal.get("signal_id"),
            stop_loss=sl,
            take_profit=tp,
            risk_pips=risk_pips,
            reward_pips=reward_pips,
            rr_ratio=rr_ratio,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            commission=self.config.commission_per_trade,
            evidence=signal.get("evidence", {}),
        )
        
        return trade

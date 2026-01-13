import json

data = {
    "schema_version": 1,
    "user_id": "cmkaspmrp0000klwig8orkd7l",
    "updated_at": 1768291600,
    "strategies": [{
        "strategy_id": "trading_reversal",
        "name": "Trading Reversal",
        "enabled": True,
        "detectors": ["break_retest", "breakout_retest_entry", "fibo_retrace_confluence", "head_shoulders", "double_top_bottom"],
        "min_score": 0.8,
        "min_rr": 2.0
    }]
}

with open("state/user_strategies/cmkaspmrp0000klwig8orkd7l.json", "w") as f:
    json.dump(data, f, indent=2)

print("Done - saved 5 detectors")

import os


def test_loader_default_requires_explicit_strategies(monkeypatch):
    monkeypatch.delenv("REQUIRE_USER_STRATEGY", raising=False)
    monkeypatch.delenv("REQUIRE_STRATEGIES", raising=False)
    monkeypatch.delenv("ALLOW_PROFILE_STRATEGY_FALLBACK", raising=False)

    from strategies.loader import load_strategies_from_profile

    # No strategy/strategies fields: by default, do not fall back.
    profile = {
        "user_id": "u1",
        "watch_pairs": ["EURCHF"],
        "tz_offset_hours": 0,
    }

    res = load_strategies_from_profile(profile)
    assert res.errors == []
    assert res.strategies == []


def test_loader_optional_legacy_profile_fallback(monkeypatch):
    monkeypatch.setenv("ALLOW_PROFILE_STRATEGY_FALLBACK", "1")

    from strategies.loader import load_strategies_from_profile

    profile = {"user_id": "u1", "watch_pairs": ["EURCHF"]}
    res = load_strategies_from_profile(profile)

    # Backward compatible behavior: profile is treated as a strategy-like config.
    assert isinstance(res.strategies, list)
    assert len(res.strategies) == 1
    assert isinstance(res.strategies[0], dict)
    assert res.strategies[0].get("enabled") is True
    assert isinstance(res.strategies[0].get("strategy_id"), str)

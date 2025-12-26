from engine.utils.reason_codes import STABLE_PAIR_NONE_REASONS, normalize_pair_none_reason


def test_reason_normalization_aliases_map_to_stable_codes():
    assert normalize_pair_none_reason(["COOLDOWN_BLOCK"]) == "COOLDOWN_ACTIVE"
    assert normalize_pair_none_reason(["DAILY_LIMIT_BLOCK"]) == "DAILY_LIMIT_REACHED"
    assert normalize_pair_none_reason(["no_match"]) == "NO_HITS"


def test_reason_normalization_outputs_stable_only():
    samples = [
        ["COOLDOWN_BLOCK"],
        ["DAILY_LIMIT_BLOCK"],
        ["no_match"],
        ["SCORE_BELOW_MIN|0.10<0.20"],
        ["low_score"],
        ["conflict"],
        ["NO_DETECTORS_FOR_REGIME"],
        ["data_gap"],
        ["no_m5"],
        ["SOME_NEW_INTERNAL_REASON"],
    ]
    for reasons in samples:
        out = normalize_pair_none_reason(reasons)
        assert out in STABLE_PAIR_NONE_REASONS


def test_no_hits_preferred_when_present_anywhere():
    assert normalize_pair_none_reason(["SCORE_BELOW_MIN|0.10<0.20", "NO_HITS"]) == "NO_HITS"

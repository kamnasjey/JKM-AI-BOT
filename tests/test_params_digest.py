from __future__ import annotations


def test_params_digest_stable_for_same_payload_different_order():
    from engine.utils.params_utils import stable_params_digest

    a = {"d1": {"x": 1, "y": 2}, "d2": {"a": True}}
    b = {"d2": {"a": True}, "d1": {"y": 2, "x": 1}}

    assert stable_params_digest(a) == stable_params_digest(b)

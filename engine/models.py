"""engine.models

Back-compat re-export for shared dataclasses.

Canonical definitions live in core.models.
"""

from __future__ import annotations

from core.models import CombineResult, DetectorHit

__all__ = ["DetectorHit", "CombineResult"]

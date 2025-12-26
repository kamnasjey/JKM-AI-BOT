from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


_NORM_RE = re.compile(r"[^a-z0-9_]+")


def _norm(name: str) -> str:
    s = str(name or "").strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    s = _NORM_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _build_registry_maps(registry_names: Sequence[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    # normalized -> canonical registry name
    norm_map: Dict[str, str] = {}
    # lower -> canonical registry name
    lower_map: Dict[str, str] = {}

    for rn in registry_names:
        r = str(rn or "").strip()
        if not r:
            continue
        lower_map.setdefault(r.lower(), r)
        norm_map.setdefault(_norm(r), r)

    return norm_map, lower_map


def similarity_score(a: str, b: str) -> float:
    """Return similarity score in [0, 1] using normalized strings."""
    na = _norm(a)
    nb = _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    try:
        return float(difflib.SequenceMatcher(a=na, b=nb).ratio())
    except Exception:
        return 0.0


@dataclass(frozen=True)
class ResolveResult:
    resolved: List[str]
    unknown: List[str]
    suggestions: Dict[str, List[str]]
    suggestions_scored: Dict[str, List[Tuple[str, float]]]
    alias_applied: Dict[str, str]


def resolve_detector_names(
    requested_names: Iterable[str],
    registry_names: Iterable[str],
    *,
    aliases: Optional[Dict[str, str]] = None,
    max_suggestions: int = 3,
) -> ResolveResult:
    """Resolve requested detector names against registry.

    Resolution steps (deterministic):
      1) exact match (case-sensitive)
      2) case-insensitive exact match
      3) underscore/dash/space normalization match
      4) alias map (optional): old -> new

    For names that remain unknown, provides top-N suggestions using:
      - difflib.get_close_matches over normalized names

    Returns:
      ResolveResult(resolved, unknown, suggestions, alias_applied)
    """
    req = [str(x or "").strip() for x in requested_names if str(x or "").strip()]
    reg = [str(x or "").strip() for x in registry_names if str(x or "").strip()]

    reg_set = set(reg)
    norm_map, lower_map = _build_registry_maps(reg)

    alias_applied: Dict[str, str] = {}
    suggestions: Dict[str, List[str]] = {}
    suggestions_scored: Dict[str, List[Tuple[str, float]]] = {}
    unknown: List[str] = []
    resolved: List[str] = []

    # Build normalized corpus for difflib
    norm_to_reg: Dict[str, str] = {}
    norm_corpus: List[str] = []
    for r in reg:
        n = _norm(r)
        if n and n not in norm_to_reg:
            norm_to_reg[n] = r
            norm_corpus.append(n)

    # Alias map should be case-insensitive on key.
    alias_map: Dict[str, str] = {}
    if isinstance(aliases, dict):
        for k, v in aliases.items():
            ks = str(k or "").strip()
            vs = str(v or "").strip()
            if ks and vs:
                alias_map[ks.lower()] = vs

    for name in req:
        # 1) exact
        if name in reg_set:
            resolved.append(name)
            continue

        # 2) case-insensitive
        lc = name.lower()
        if lc in lower_map:
            resolved.append(lower_map[lc])
            continue

        # 3) normalized
        n = _norm(name)
        if n and n in norm_map:
            resolved.append(norm_map[n])
            continue

        # 4) alias map
        if lc in alias_map:
            target = alias_map[lc]
            # Resolve alias target via same rules so users can map to any casing.
            if target in reg_set:
                resolved.append(target)
                alias_applied[name] = target
                continue
            tlc = target.lower()
            if tlc in lower_map:
                resolved.append(lower_map[tlc])
                alias_applied[name] = lower_map[tlc]
                continue
            tn = _norm(target)
            if tn and tn in norm_map:
                resolved.append(norm_map[tn])
                alias_applied[name] = norm_map[tn]
                continue

        # Unknown: compute suggestions
        unknown.append(name)
        cand: List[str] = []
        cand_scored: List[Tuple[str, float]] = []
        if n:
            close = difflib.get_close_matches(n, norm_corpus, n=int(max_suggestions), cutoff=0.6)
            for cn in close:
                rname = norm_to_reg.get(cn)
                if rname and rname not in cand:
                    cand.append(rname)

        # Score candidates deterministically.
        for rname in cand:
            cand_scored.append((rname, similarity_score(name, rname)))

        # If difflib returned nothing, still try scoring all registry names lightly.
        if not cand_scored and reg:
            scored_all = [(r, similarity_score(name, r)) for r in reg]
            scored_all.sort(key=lambda x: (-float(x[1]), str(x[0])))
            cand_scored = scored_all[: int(max_suggestions)]
            cand = [x[0] for x in cand_scored if x[0]]

        # Also try case-insensitive startswith boost (deterministic)
        if len(cand) < int(max_suggestions):
            for r in reg:
                if r.lower().startswith(lc[: max(1, min(3, len(lc)))]):
                    if r not in cand:
                        cand.append(r)
                        cand_scored.append((r, similarity_score(name, r)))
                if len(cand) >= int(max_suggestions):
                    break

        if cand:
            suggestions[name] = cand[: int(max_suggestions)]
        if cand_scored:
            # sort scored suggestions and keep top-N
            cand_scored_sorted = list(cand_scored)
            cand_scored_sorted.sort(key=lambda x: (-float(x[1]), str(x[0])))
            suggestions_scored[name] = cand_scored_sorted[: int(max_suggestions)]

    return ResolveResult(
        resolved=resolved,
        unknown=unknown,
        suggestions=suggestions,
        suggestions_scored=suggestions_scored,
        alias_applied=alias_applied,
    )

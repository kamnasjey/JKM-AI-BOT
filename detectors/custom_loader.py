from __future__ import annotations

import hashlib
import importlib.util
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class CustomDetectorLoadFailure:
    file: str
    code: str
    detail: str


@dataclass(frozen=True)
class CustomDetectorLoadResult:
    loaded_modules: List[str]
    failures: List[CustomDetectorLoadFailure]

    @property
    def loaded_count(self) -> int:
        return int(len(self.loaded_modules))

    @property
    def failed_count(self) -> int:
        return int(len(self.failures))


def _is_safe_py_file(path: str) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if os.path.basename(path).startswith("__"):
        return False
    return path.lower().endswith(".py")


def _module_name_for_path(path: str) -> str:
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    digest = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:10]
    safe_stem = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in stem)
    return f"detectors.custom.{safe_stem}_{digest}"


def load_custom_detectors(custom_dir: str) -> CustomDetectorLoadResult:
    """Dynamically import custom detector modules.

    Non-fatal by design:
    - Missing directory => returns empty result
    - Import errors per module => captured in failures, does not raise

    Expected convention: modules register detectors into
    `engines.detectors.detector_registry` at import time.
    """
    loaded: List[str] = []
    failures: List[CustomDetectorLoadFailure] = []

    if not custom_dir:
        return CustomDetectorLoadResult(loaded_modules=[], failures=[])

    try:
        abs_dir = os.path.abspath(custom_dir)
        if not os.path.isdir(abs_dir):
            return CustomDetectorLoadResult(loaded_modules=[], failures=[])

        for name in sorted(os.listdir(abs_dir)):
            path = os.path.join(abs_dir, name)
            if not os.path.isfile(path):
                continue
            if not _is_safe_py_file(path):
                continue

            module_name = _module_name_for_path(path)
            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    failures.append(
                        CustomDetectorLoadFailure(
                            file=str(path),
                            code="SPEC_LOAD_FAILED",
                            detail="spec_from_file_location returned None",
                        )
                    )
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded.append(module_name)
            except Exception as e:
                failures.append(
                    CustomDetectorLoadFailure(
                        file=str(path),
                        code="IMPORT_ERROR",
                        detail=f"{type(e).__name__}: {e}",
                    )
                )
    except Exception as e:
        # Directory listing errors, permission issues, etc.
        failures.append(
            CustomDetectorLoadFailure(
                file=str(custom_dir),
                code="CUSTOM_DIR_ERROR",
                detail=f"{type(e).__name__}: {e}",
            )
        )

    return CustomDetectorLoadResult(loaded_modules=loaded, failures=failures)


def load_custom_detectors_with_logs(
    logger,
    *,
    custom_dir: str,
    log_kv,
    log_kv_warning,
) -> CustomDetectorLoadResult:
    """Convenience wrapper for boot-time logging."""
    res = load_custom_detectors(custom_dir)
    for f in res.failures:
        log_kv_warning(logger, "CUSTOM_DETECTOR_LOAD_FAILED", file=f.file, code=f.code, detail=f.detail)
    log_kv(logger, "CUSTOM_DETECTORS_LOADED", dir=custom_dir, count=res.loaded_count, failed=res.failed_count)
    return res

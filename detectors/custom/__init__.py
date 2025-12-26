"""Custom detector modules.

Convention:
- Put custom detector modules in this folder.
- Each module should register detectors into `engines.detectors.detector_registry`
  (typically via `from engines.detectors.registry import register_detector`).

These modules are loaded dynamically by `detectors.custom_loader`.
"""

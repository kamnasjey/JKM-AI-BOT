"""Provider adapters.

Goal: engine/cache remain provider-agnostic. Only this layer knows about
provider-specific IDs (e.g., IG EPIC) and transport/auth details.
"""

from .factory import create_provider

__all__ = ["create_provider"]

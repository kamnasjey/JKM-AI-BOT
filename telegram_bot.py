"""Backward-compatible entrypoint for the Telegram thin client.

The canonical implementation now lives in `apps.telegram_bot`.
"""

from apps.telegram_bot import main

__all__ = ["main"]


if __name__ == "__main__":
    main()

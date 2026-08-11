"""REST API layer for MemOS.

Presentation only: every handler validates the request model, delegates the
operation to the Memory Kernel, and maps the result to the documented JSON
envelope. No business logic and no engine imports live here.
"""

from memos.api.app import create_app

__all__ = ["create_app"]
"""Process-wide singletons shared by the tools."""

from __future__ import annotations

from .browser import BrowserPool
from .config import settings

pool = BrowserPool(settings)

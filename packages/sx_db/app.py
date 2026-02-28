from __future__ import annotations

from .api import create_app
from .settings import load_settings

settings = load_settings()
app = create_app(settings)

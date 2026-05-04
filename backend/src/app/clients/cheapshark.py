"""Legacy CheapShark client kept for backwards compatibility.

The canonical client is `app.core.services.cheapshark`. This file
re-exports its `fetch_deals` so any older imports keep working.
"""
from ..core.services.cheapshark import fetch_deals

__all__ = ["fetch_deals"]

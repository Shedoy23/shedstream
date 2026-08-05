"""Compatibility endpoints for already published extension versions.

Version 0.0.1 still polls the removed rulection status endpoint.  Keeping an
inert, read-only response avoids noisy 404s without reviving the removed
currency mechanics.  Mutation endpoints intentionally remain absent.
"""

from fastapi import APIRouter


router = APIRouter()


@router.get("/api/event/status")
async def legacy_event_status():
    """Return the neutral shape expected by the published 0.0.1 frontend."""
    return {
        "pool": 0,
        "pool_pct_points": 0,
        "min_points": 0,
        "can_start": False,
        "can_start_reason": "feature_removed",
        "top_contributors": [],
        "active_event": None,
        "last_winner": None,
    }

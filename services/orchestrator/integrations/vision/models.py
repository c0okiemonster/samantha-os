"""Dataclasses for the vision integration. Pure data, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


class SnapshotError(Exception):
    """Raised by the snapshot round-trip when the shell returns an error
    code instead of an image (vision_off, permission_revoked, grab_failed)."""


@dataclass
class Observation:
    id: Optional[int]
    raw_description: str
    spoken_text: str
    user_trigger: Optional[str] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


@dataclass
class SnapshotResult:
    spoken: str
    observation_id: Optional[int]
    overlay: Optional[Any]  # kept for symmetry with TaskActionResult

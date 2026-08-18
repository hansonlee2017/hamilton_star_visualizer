"""Turn a PyLabRobot deck into the JSON scene graph the frontend renders.

``Resource.serialize()`` already recurses into every child and reports each
resource's location, rotation, and size *relative to its parent*. That is
exactly the parent-child transform hierarchy the frontend mirrors with
nested Three.js groups (see ``frontend/main.js``), so there is very little
to do here beyond calling it -- the real coordinates come straight from
PyLabRobot, we don't recompute anything.
"""

from __future__ import annotations

from typing import Any, Dict

from pylabrobot.resources import Deck


def build_scene(deck: Deck) -> Dict[str, Any]:
  """Serialize ``deck`` (and everything assigned to it) for the browser."""

  return deck.serialize()

"""Helpers for turning PyLabRobot operation objects into the small JSON events
that drive the gantry animation in the browser.

Each event is a plain dict with a ``"type"`` key so the frontend can dispatch
on it; see ``frontend/main.js`` for the consumer side and ``docs/DESIGN.md``
for why this exists instead of parsing Chatterbox log text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pylabrobot.resources import Resource


def resource_point(resource: Resource) -> Dict[str, float]:
  """Absolute (x, y, z) of the top-center of ``resource``, in deck mm.

  This is an approximation of "where a channel would go to act on this
  resource" -- good enough for simple bounding-box animation, not a
  substitute for real motion planning.
  """

  loc = resource.get_absolute_location(x="c", y="c", z="t")
  return {"x": round(loc.x, 2), "y": round(loc.y, 2), "z": round(loc.z, 2)}


def channel_ops_event(
  op_name: str,
  ops: Sequence[Any],
  use_channels: Sequence[int],
  *,
  volume_attr: Optional[str] = None,
) -> Dict[str, Any]:
  """Build a ``{"type": "op", ...}`` event for a per-channel pipetting call
  (pick_up_tips / drop_tips / aspirate / dispense).
  """

  channels: List[Dict[str, Any]] = []
  for op, channel in zip(ops, use_channels):
    entry: Dict[str, Any] = {
      "channel": channel,
      "resource": op.resource.name,
      **resource_point(op.resource),
    }
    if volume_attr is not None:
      entry["volume"] = getattr(op, volume_attr)
    tip = getattr(op, "tip", None)
    if tip is not None:
      entry["tip_type"] = type(tip).__name__
    channels.append(entry)
  return {"type": "op", "op": op_name, "channels": channels}


def resource_event(op_name: str, resource: Resource, **extra: Any) -> Dict[str, Any]:
  """Build a ``{"type": "op", ...}`` event for a single-resource call (96-head
  and resource-move operations)."""

  return {"type": "op", "op": op_name, "resource": resource.name, **resource_point(resource), **extra}

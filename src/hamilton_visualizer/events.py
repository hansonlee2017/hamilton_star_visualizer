"""Helpers for turning PyLabRobot operation objects into the small JSON events
that drive the gantry animation in the browser.

Each event is a plain dict with a ``"type"`` key so the frontend can dispatch
on it; see ``frontend/main.js`` for the consumer side and ``docs/DESIGN.md``
for why this exists instead of parsing Chatterbox log text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pylabrobot.resources import Resource
from pylabrobot.resources.tip import Tip
from pylabrobot.resources.tip_rack import TipSpot


def resource_point(resource: Resource) -> Dict[str, float]:
  """Absolute (x, y, z) of the top-center of ``resource``, in deck mm.

  This is an approximation of "where a channel would go to act on this
  resource" -- good enough for simple bounding-box animation, not a
  substitute for real motion planning.
  """

  loc = resource.get_absolute_location(x="c", y="c", z="t")
  return {"x": round(loc.x, 2), "y": round(loc.y, 2), "z": round(loc.z, 2)}


def tip_grab_point(tip_spot: TipSpot, tip: Tip) -> Dict[str, float]:
  """Absolute (x, y, z) of where a channel actually grabs a tip seated at
  ``tip_spot``, in deck mm.

  ``TipSpot`` resources are zero-height placement markers (``size_z=0`` by
  construction -- see ``pylabrobot.resources.tip_rack.TipSpot.__init__``):
  their own bounding box has no "top", so ``resource_point()``'s top-anchor
  is a no-op there and just returns the spot's raw location. That raw
  location is *not* where a channel grabs the tip either -- each tip rack
  factory places its spots via a ``dz`` offset that (empirically, from
  PyLabRobot's own STAR backend math) lands close to the tip's sharp point,
  well below the rack surface where the tip's mounting collar actually sits.

  PyLabRobot's ``STARBackend.pick_up_tips`` computes the real seating depth
  as ``spot_z + tip.total_tip_length - tip.fitting_depth`` (its
  ``end_tip_pick_up_process``) -- this mirrors that formula so the
  visualization's descend target matches where a channel would really stop.
  """

  loc = tip_spot.get_absolute_location(x="c", y="c", z="b")
  z = loc.z + tip.total_tip_length - tip.fitting_depth
  return {"x": round(loc.x, 2), "y": round(loc.y, 2), "z": round(z, 2)}


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
    tip = getattr(op, "tip", None)
    # pick_up_tips/drop_tips against a TipSpot (not e.g. a Trash) need the
    # tip-length-aware grab point -- see tip_grab_point() -- everything else
    # (aspirate/dispense wells, drop_tips into a Trash) uses the generic
    # top-anchor approximation.
    if op_name in ("pick_up_tips", "drop_tips") and tip is not None and isinstance(op.resource, TipSpot):
      point = tip_grab_point(op.resource, tip)
    else:
      point = resource_point(op.resource)
    entry: Dict[str, Any] = {"channel": channel, "resource": op.resource.name, **point}
    if volume_attr is not None:
      entry["volume"] = getattr(op, volume_attr)
    if tip is not None:
      entry["tip_type"] = type(tip).__name__
    channels.append(entry)
  return {"type": "op", "op": op_name, "channels": channels}


def resource_event(op_name: str, resource: Resource, **extra: Any) -> Dict[str, Any]:
  """Build a ``{"type": "op", ...}`` event for a single-resource call (96-head
  and resource-move operations)."""

  return {"type": "op", "op": op_name, "resource": resource.name, **resource_point(resource), **extra}

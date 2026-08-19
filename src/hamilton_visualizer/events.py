"""Helpers for turning PyLabRobot operation objects into the small JSON events
that drive the gantry animation in the browser.

Each event is a plain dict with a ``"type"`` key so the frontend can dispatch
on it; see ``frontend/main.js`` for the consumer side and ``docs/DESIGN.md``
for why this exists instead of parsing Chatterbox log text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pylabrobot.resources import Coordinate, Resource
from pylabrobot.resources.tip import Tip
from pylabrobot.resources.tip_rack import TipSpot


def _apply_offset(loc: Coordinate, offset: Optional[Coordinate]) -> Coordinate:
  return loc if offset is None else loc + offset


def resource_point(resource: Resource, offset: Optional[Coordinate] = None) -> Dict[str, float]:
  """Absolute (x, y, z) of the top-center of ``resource`` plus ``offset``, in
  deck mm.

  ``offset`` matters more than it looks: it's how PyLabRobot spreads
  multiple channels that are nominally acting on the *same* resource --
  e.g. ``discard_tips()`` sends every channel to the deck's one Trash, with
  a small per-channel offset (``compute_channel_offsets(..., spread="tight")``)
  so they don't all collapse onto the same point. Every op carries an
  ``offset`` (``Coordinate.zero()`` when not otherwise set), mirroring how
  ``STARBackend`` itself always adds it to the resource's raw location.

  This is otherwise an approximation of "where a channel would go to act on
  this resource" -- good enough for simple bounding-box animation, not a
  substitute for real motion planning.
  """

  loc = _apply_offset(resource.get_absolute_location(x="c", y="c", z="t"), offset)
  return {"x": round(loc.x, 2), "y": round(loc.y, 2), "z": round(loc.z, 2)}


def tip_grab_point(tip_spot: TipSpot, tip: Tip, offset: Optional[Coordinate] = None) -> Dict[str, float]:
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

  loc = _apply_offset(tip_spot.get_absolute_location(x="c", y="c", z="b"), offset)
  z = loc.z + tip.total_tip_length - tip.fitting_depth
  return {"x": round(loc.x, 2), "y": round(loc.y, 2), "z": round(z, 2)}


def liquid_surface_point(
  resource: Resource, liquid_height: Optional[float], offset: Optional[Coordinate] = None
) -> Dict[str, float]:
  """Absolute (x, y, z) of the liquid surface a channel would aspirate from
  or dispense into ``resource`` (a well/container), in deck mm.

  Mirrors ``STARBackend.aspirate``'s own formula for the z --
  ``well_bottom + material_z_thickness + liquid_height`` -- rather than
  ``resource_point()``'s generic top-anchor, which stops at the well's
  *opening* instead of the liquid.

  If ``liquid_height`` isn't given (the common case -- it's an optional,
  explicit override on the PyLabRobot op), it's derived from the well's
  *currently tracked* volume via ``compute_height_from_volume()`` when the
  resource supports it, so the depth reflects reality and drops as a well
  drains. Falls back to the well bottom otherwise, matching what
  ``STARBackend`` itself does when liquid_height is unset.

  Note: this reads the tracker *synchronously within the same op* that's
  changing it, before ``LiquidHandler`` commits the pending change -- so in
  practice this ends up reading the volume as it was *before* this
  operation, for both aspirate and dispense. That's a reasonable
  approximation (roughly "where the surface was when the tip arrived") but
  not exact; a substitute for real motion planning this is not.
  """

  loc = _apply_offset(resource.get_absolute_location(x="c", y="c", z="b"), offset)
  bottom_z = loc.z + (getattr(resource, "material_z_thickness", None) or 0)

  if liquid_height is None:
    liquid_height = 0.0
    tracker = getattr(resource, "tracker", None)
    supports_hv = getattr(resource, "supports_compute_height_volume_functions", None)
    if tracker is not None and callable(supports_hv) and supports_hv():
      try:
        liquid_height = resource.compute_height_from_volume(tracker.volume)
      except Exception:  # noqa: BLE001 - fall back to well bottom on any surprise
        liquid_height = 0.0

  z = bottom_z + liquid_height
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

  Each channel entry also embeds the *resulting* tip-presence/volume state
  of the resource it targets (``resource_has_tip`` or ``resource_volume``/
  ``resource_max_volume``) -- see the comment above the block that computes
  them for why this exists instead of relying on the separate live "state"
  broadcast for these two resource categories.
  """

  channels: List[Dict[str, Any]] = []
  for op, channel in zip(ops, use_channels):
    tip = getattr(op, "tip", None)
    offset = getattr(op, "offset", None)
    # pick_up_tips/drop_tips against a TipSpot (not e.g. a Trash) need the
    # tip-length-aware grab point -- see tip_grab_point(). aspirate/dispense
    # need the liquid-surface-aware point -- see liquid_surface_point().
    # Everything else (drop_tips into a Trash, 96-head via resource_event)
    # uses the generic top-anchor approximation. All three apply `offset`,
    # which matters even when every channel in a call nominally targets the
    # *same* resource -- e.g. discard_tips() sends every channel to the
    # deck's one Trash, distinguished only by a per-channel offset; without
    # applying it, all those channels would collapse onto the same point.
    if op_name in ("pick_up_tips", "drop_tips") and tip is not None and isinstance(op.resource, TipSpot):
      point = tip_grab_point(op.resource, tip, offset)
    elif op_name in ("aspirate", "dispense"):
      point = liquid_surface_point(op.resource, getattr(op, "liquid_height", None), offset)
    else:
      point = resource_point(op.resource, offset)
    entry: Dict[str, Any] = {"channel": channel, "resource": op.resource.name, **point}
    if volume_attr is not None:
      entry["volume"] = getattr(op, volume_attr)
    if tip is not None:
      entry["tip_type"] = type(tip).__name__

    # Embed the resulting state directly, timed by the frontend's animation
    # (applied at "arrival," not on receipt) instead of relying on the
    # separately-broadcast "state" event PyLabRobot's tracker callbacks
    # produce. That broadcast fires the moment `LiquidHandler` queues the
    # tracker change -- *before* it even calls this backend -- so by the
    # time our own event reaches the frontend, the color change has usually
    # already arrived and been applied too early (visually "the well fills
    # before the dispense animation gets there"). visualizer_backend.py's
    # `_register_state_callbacks` deliberately skips live callbacks for
    # exactly the two categories covered here (tip_spot, well) so this is
    # the only path driving their color during a live run.
    if op_name in ("pick_up_tips", "drop_tips"):
      # No tracker read needed: a successful pick_up_tips always empties the
      # spot and a successful drop_tips always fills its target: if either
      # failed, we wouldn't have reached this line (the inner backend call
      # above would have raised).
      entry["resource_has_tip"] = op_name == "drop_tips"
    elif op_name in ("aspirate", "dispense"):
      tracker = getattr(op.resource, "tracker", None)
      # `pending_volume`, not `volume`: LiquidHandler queues the tracker
      # change before calling the backend and only commits it (syncing
      # `volume` from `pending_volume`) afterwards -- we're still inside
      # that window, so `pending_volume` is the one that already reflects
      # this operation's result.
      if tracker is not None and hasattr(tracker, "pending_volume"):
        entry["resource_volume"] = tracker.pending_volume
        entry["resource_max_volume"] = getattr(op.resource, "max_volume", None)

    channels.append(entry)
  return {"type": "op", "op": op_name, "channels": channels}


def resource_event(
  op_name: str, resource: Resource, *, offset: Optional[Coordinate] = None, **extra: Any
) -> Dict[str, Any]:
  """Build a ``{"type": "op", ...}`` event for a single-resource call (96-head
  and resource-move operations)."""

  return {
    "type": "op",
    "op": op_name,
    "resource": resource.name,
    **resource_point(resource, offset),
    **extra,
  }

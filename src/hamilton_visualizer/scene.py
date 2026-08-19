"""Turn a PyLabRobot deck into the JSON scene graph the frontend renders.

``Resource.serialize()`` already recurses into every child and reports each
resource's location, rotation, and size *relative to its parent*. That is
exactly the parent-child transform hierarchy the frontend mirrors with
nested Three.js groups (see ``frontend/main.js``), so there is very little
to do here beyond calling it -- the real coordinates come straight from
PyLabRobot, we don't recompute anything.

The one thing it *is* worth adding: a tip rack's own children (TipSpot
resources) carry no notion of "how long is the tip that goes here" until a
real ``Tip`` object exists at that spot -- ``total_tip_length`` lives on the
``Tip``, not the ``TipSpot``. Without it the frontend has no way to size a
resting tip's pyramid correctly and falls back to an arbitrary constant.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pylabrobot.resources import Deck, TipRack


def build_scene(deck: Deck) -> Dict[str, Any]:
  """Serialize ``deck`` (and everything assigned to it) for the browser."""

  data = deck.serialize()
  _inject_tip_lengths(deck, data)
  return data


def _inject_tip_lengths(resource: Any, node: Dict[str, Any]) -> None:
  """Walk ``resource``/``node`` in lockstep (they have identical structure --
  ``node`` is what ``resource.serialize()`` produced) and add a
  ``tip_length_mm`` field to every ``TipRack`` node, read from whatever tip
  model it holds.
  """

  if isinstance(resource, TipRack):
    length = _rack_tip_length(resource)
    if length is not None:
      node["tip_length_mm"] = length

  for child_resource, child_node in zip(resource.children, node.get("children") or []):
    _inject_tip_lengths(child_resource, child_node)


def _rack_tip_length(tip_rack: TipRack) -> Optional[float]:
  """The tip length used throughout ``tip_rack`` (real Hamilton racks hold
  one uniform tip type, so the first spot is representative).

  Prefers a tip that's actually seated (real data, no side effects). If
  every spot is currently empty, falls back to synthesizing one via
  ``TipSpot.make_tip()`` purely to read its length -- this has one minor,
  harmless side effect: it advances that spot's tip-naming counter by one,
  so the next *real* tip picked from it is named "...#1" instead of "...#0".
  Nothing that affects tracked state or the running protocol.
  """

  for spot in tip_rack.children:
    tracker = getattr(spot, "tracker", None)
    if tracker is not None and tracker.has_tip:
      return tracker.get_tip().total_tip_length
  for spot in tip_rack.children:
    make_tip = getattr(spot, "make_tip", None)
    if callable(make_tip):
      try:
        return make_tip().total_tip_length
      except Exception:  # noqa: BLE001 - this is a best-effort visual nicety
        continue
  return None

"""Plans hardware-feasible gantry motion for multi-channel operations whose
target wells don't share a column.

A real Hamilton STAR's 8 pipetting channels are all bolted to one arm with a
single X motor -- every loaded channel is always at the *same* x, whether or
not it's doing anything there. Each channel does have its own Y and Z motor,
but two physical constraints apply: channels can't pass each other (channel
0's y must stay on the same side of channel 1's as channel 1's is of channel
2's, and so on -- they're mounted in a fixed physical order), and they can't
get closer than ``CHANNEL_PITCH_MM`` center-to-center (their bodies are that
wide).

A protocol that wants channel 0 at one well and channel 1 at a well in a
*different* column can't do that in a single ``aspirate()``/``dispense()``
call -- there's no single x that reaches both. On a real instrument this
becomes a sequence of arm stops, one per distinct x, in order; at each stop,
only the channel(s) whose target is actually at that x do anything, but
every *other* loaded channel still has to have some valid y right there too
(it's dragged along by the shared arm), nudged only as far as needed to stay
clear of whichever channels are working.

A single column can itself have more than one channel with a target in it
(e.g. two rows of a scattered pattern happen to land in the same column).
When that happens, ``plan_gantry_passes()`` first tries to reach all of them
in one simultaneous move -- possible exactly when their channel-index gaps
and y gaps agree (a real gap of 4 rows can't fit channels that are 6 slots
apart; see this module's own dry-run notes in docs/PLAN.md's round-9 section
for a concrete case). When it can't, it falls back to one channel at a time,
smallest channel index first, each its own stop at that same x -- exactly
what a real instrument does when a single move can't reach both.

``plan_gantry_passes()`` turns "channel i eventually needs to visit resource
R" into that sequence of stops. See ``examples/cherry_pick_demo.py`` for how
to turn a ``GantryPass`` into real ``LiquidHandler`` calls (the active
channels) plus purely-cosmetic repositioning of the idle ones (see
``VisualizerBackend.nudge_channel``'s docstring for why that's a separate,
non-hardware call).

Channel-index-to-y direction: channel 0 is the highest-y (e.g. row "A")
channel, increasing index means decreasing y -- this matches the ordering
every existing demo in this repo already uses (``plate["A1:H1"]`` assigns
row A to channel 0 through row H to channel 7, and row A's y is larger than
row H's, confirmed against PyLabRobot's real coordinates). A plan that asks
for the opposite order (a lower-index channel needing a *smaller* y than a
higher-index one) is physically impossible and raises ``ValueError``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pylabrobot.resources import Resource

# Hamilton STAR's standard channel spacing -- also the minimum center-to-
# center distance two channels can be at without colliding.
CHANNEL_PITCH_MM = 9.0


@dataclass
class GantryPass:
  """One stop of the shared-x gantry arm."""

  x: float
  # channel -> the resource it actually visits (aspirates/dispenses/etc.)
  # at this stop.
  targets: Dict[int, Resource] = field(default_factory=dict)
  # channel -> the y every *other* loaded channel must be nudged to here,
  # so it's dragged to this stop's x without colliding with (or crossing
  # the order of) whichever channels in `targets` are working. Present for
  # every loaded channel not in `targets`, even when its y doesn't change
  # from the previous pass -- its x still needs updating, since the whole
  # arm just moved there too.
  idle_moves: Dict[int, float] = field(default_factory=dict)


def plan_gantry_passes(
  targets: Dict[int, Resource],
  *,
  initial_y: Optional[Dict[int, float]] = None,
  pitch_mm: float = CHANNEL_PITCH_MM,
) -> List[GantryPass]:
  """Group ``targets`` (channel -> the one resource it needs to visit) into
  a sequence of hardware-feasible arm stops, ordered by ascending x.

  ``initial_y``: each loaded channel's y *before* this plan starts (e.g.
  wherever an earlier ``aspirate()`` actually left it) -- used as the
  preferred position for a channel before its own pass comes up, so it
  isn't nudged unless something later actually needs the room. A channel
  missing from ``initial_y`` (or if the argument is omitted entirely)
  defaults to its own eventual target's y, i.e. "assume it's already
  parked where it'll end up" -- a reasonable placeholder when nothing
  better is known, and exactly correct once its own pass arrives.
  """

  if not targets:
    return []

  channel_indices = sorted(targets.keys())
  # x="c", y="c": center of the resource's footprint -- matches
  # events.py's tip_grab_point()/liquid_surface_point(), which is what
  # actually drives a channel's real x/y when it aspirates/dispenses/picks
  # up a tip. Using the same reference point here keeps an idle channel's
  # nudged (x, y) visually aligned with the active channel(s) it's sharing
  # a stop with, instead of a few mm off to one side.
  locs = {i: targets[i].get_absolute_location(x="c", y="c", z="c") for i in channel_indices}
  own_y = {i: locs[i].y for i in channel_indices}
  xs = sorted({round(locs[i].x, 3) for i in channel_indices})

  current_y: Dict[int, float] = dict(initial_y or {})
  passes: List[GantryPass] = []

  for x in xs:
    column_channels = sorted(i for i in channel_indices if round(locs[i].x, 3) == x)

    # Try every channel with a target at this x in one simultaneous stop
    # first; _resolve_ys raises exactly when that's not reachable (two of
    # them would need to be out of order, or closer than pitch_mm, once
    # every channel between them is accounted for) -- in which case fall
    # back to one stop per channel, smallest index first.
    try:
      groups = [column_channels]
      _ = _resolve_ys(
        channel_indices,
        {i: locs[i].y for i in column_channels},
        {i: current_y.get(i, own_y[i]) for i in channel_indices if i not in column_channels},
        pitch_mm,
      )
    except ValueError:
      groups = [[i] for i in column_channels]

    for group in groups:
      fixed_y = {i: locs[i].y for i in group}
      preferred_y = {
        i: current_y.get(i, own_y[i]) for i in channel_indices if i not in group
      }
      resolved = _resolve_ys(channel_indices, fixed_y, preferred_y, pitch_mm)
      current_y.update(resolved)
      idle_moves = {i: resolved[i] for i in channel_indices if i not in group}
      passes.append(
        GantryPass(x=x, targets={i: targets[i] for i in group}, idle_moves=idle_moves)
      )

  return passes


def _resolve_ys(
  channel_indices: List[int],
  fixed_y: Dict[int, float],
  preferred_y: Dict[int, float],
  pitch_mm: float,
) -> Dict[int, float]:
  """Assign every channel in ``channel_indices`` (sorted ascending) a y for
  one gantry stop: y must decrease by at least ``pitch_mm`` from each
  channel to the next. ``fixed_y`` entries are non-negotiable (they're this
  stop's real targets, e.g. one of them might be on a completely different
  plate/site than where the rest of these channels last were -- see
  ``examples/cherry_pick_demo.py``'s source-plate-vs-destination-plate y
  ranges for a case where that's exactly what happens); every other
  channel is nudged off its preferred y no further than needed to keep the
  whole sequence in order.

  Solved with a change of variable, ``z[k] = y[channel_indices[k]] + k *
  pitch_mm``, which turns "must decrease by >= pitch_mm per step" into the
  simpler "must be non-increasing" -- then one forward pass (each value
  capped by the *actual resolved* value before it -- a fixed value is never
  capped, even if that means it's higher than what came before; that just
  means the earlier ones were resolved too low, corrected next) and one
  backward pass (each value raised to the actual resolved value after it,
  same exception for fixed values) converge on the unique tightest
  solution. A free channel sandwiched between two fixed ones always ends
  up consistent this way; the only way the *final* sequence can still be
  out of order is two fixed channels that are themselves mutually
  incompatible (out of order, or too close together), which is when this
  raises ``ValueError``.
  """

  eps = 1e-6
  n = channel_indices
  fixed_z = {k: fixed_y[ch] + k * pitch_mm for k, ch in enumerate(n) if ch in fixed_y}
  preferred_z = {
    k: preferred_y[ch] + k * pitch_mm for k, ch in enumerate(n) if ch not in fixed_y
  }

  z: List[float] = [0.0] * len(n)
  running = math.inf
  for k in range(len(n)):
    v = fixed_z[k] if k in fixed_z else min(preferred_z[k], running)
    z[k] = v
    running = v

  running = -math.inf
  for k in range(len(n) - 1, -1, -1):
    v = fixed_z[k] if k in fixed_z else max(z[k], running)
    z[k] = v
    running = v

  for k in range(len(n) - 1):
    if z[k] < z[k + 1] - eps:
      raise ValueError(
        f"channels {n[k]} and {n[k + 1]} need y positions here that put "
        f"them out of order or closer than {pitch_mm}mm apart -- this "
        "combination of targets isn't reachable in one gantry stop"
      )

  return {n[k]: z[k] - k * pitch_mm for k in range(len(n))}

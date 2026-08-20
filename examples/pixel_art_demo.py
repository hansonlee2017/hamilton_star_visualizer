"""Pixel-art demo: draw a simple picture (a heart) on a 384-well plate, one
color pulled from a single 60mL reservoir.

A 384-well plate is 16 rows (A-P) x 24 columns at half the pitch of a
96-well plate (4.5mm, not 9mm). PyLabRobot's own catalog doesn't have a
plate explicitly branded "square well" for this format, so this demo uses
a custom one instead -- ``custom_labware.cellvis_384_wellplate_120uL_Fb``,
a real, genuinely square-welled 384 glass-bottom plate (see that module for
the full dimensions and where they come from). Its SBS footprint (127.6 x
85.6mm) is identical to a 96-well plate's, so it drops into the same
``PLT_CAR_L5AC_A00`` carrier those other demos use without any
special-casing.

The picture is an ordinary bitmap (``HEART_BITMAP`` below, a small pixel-art
heart, hand-drawn and left-right symmetric by construction) mapped onto a
9-row x 11-column patch roughly centered on the plate. Its 64 filled wells
split cleanly into 8 batches of 8 -- each batch is one ordinary 8-channel
``LiquidHandler`` call, aspirating from the one shared reservoir
(``spread="wide"``, PyLabRobot's own idiom for multiple channels sharing a
single large container) and dispensing into up to 8 *scattered* wells at
once, exactly like ``cherry_pick_demo.py``'s smiley face -- no gantry-
planning code here either; ``frontend/main.js``'s ``planGantryPasses()``
works out the real column-by-column arm motion for each batch on its own.

One tip pick-up covers the whole picture: every aspirate draws from the
same reservoir and every dispense lands in a still-empty well, so there's
no cross-contamination risk a fresh tip per batch would be guarding
against (same reasoning as picogreen_demo.py's PicoGreen transfer stage).

Deliberately no ``asyncio.sleep()`` calls anywhere in this script. The
browser's own animation queue is entirely decoupled from how fast these
calls actually run -- each channel's queue plays out its own real ~1.6s/leg
pace regardless of how quickly the backend sends the events that filled it
(see picogreen_demo.py's module docstring, and docs/PLAN.md's "Review
round 25", for the full reasoning and the one real tradeoff: a ``replay()``
of a run recorded without any pacing plays back in a couple of seconds
rather than at anything resembling the original pace).

Run it with:

    uv run python examples/pixel_art_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765).
"""

from __future__ import annotations

import asyncio

from custom_labware import cellvis_384_wellplate_120uL_Fb
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARLetDeck,
  Trough_CAR_5R60_A00,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_50uL_filter,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer

# 16 rows (A-P), matching a 384-well plate's real row count (24 columns x
# 16 rows).
PLATE_ROWS = "ABCDEFGHIJKLMNOP"

# A small pixel-art heart -- 9 rows x 11 columns, hand-drawn but verified
# left-right symmetric (every row reads the same forwards and backwards).
# 64 filled ('X') wells total, chosen to split evenly into 8 batches of 8
# for the 8-channel dispense loop below.
HEART_BITMAP = [
  ".XXX...XXX.",
  "XXXXXXXXXXX",
  "XXXXXXXXXXX",
  "XXXXXXXXXXX",
  ".XXXXXXXXX.",
  "..XXXXXXX..",
  "...XXXXX...",
  "....XXX....",
  ".....X.....",
]
assert all(row == row[::-1] for row in HEART_BITMAP), "HEART_BITMAP must be left-right symmetric"
assert len({len(row) for row in HEART_BITMAP}) == 1, "HEART_BITMAP rows must all be the same width"

# Where the bitmap's own (0, 0) -- top-left -- lands on the plate: roughly
# centered in both directions (16 - 9 = 7, so 3 rows of margin top and
# bottom; 24 - 11 = 13, so 6-7 columns of margin left and right).
ROW_OFFSET = 3
COL_OFFSET = 6

INK_VOLUME_UL = 20.0  # per well -- comfortably under a 50uL tip's capacity
BATCH_SIZE = 8  # one 8-channel call per batch


def heart_wells() -> list[str]:
  """Every filled well in ``HEART_BITMAP``, mapped onto the plate via
  ``ROW_OFFSET``/``COL_OFFSET``, in bitmap reading order (top row first,
  left to right within each row)."""

  wells = []
  for r, row_pattern in enumerate(HEART_BITMAP):
    row_letter = PLATE_ROWS[ROW_OFFSET + r]
    for c, char in enumerate(row_pattern):
      if char == "X":
        wells.append(f"{row_letter}{COL_OFFSET + c + 1}")
  return wells


async def main() -> None:
  # -- deck layout: a tip carrier, a plate carrier, a reservoir carrier -----
  deck = STARLetDeck()

  tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
  tip_rack = hamilton_96_tiprack_50uL_filter(name="tip_rack_50uL")
  tip_carrier[0] = tip_rack
  deck.assign_child_resource(tip_carrier, rails=1)

  # Same SBS footprint as any other 96- or 384-format plate, so the usual
  # plate carrier holds it without any special-casing -- see custom_labware.py
  # for this plate's real dimensions and where they come from.
  plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
  canvas = cellvis_384_wellplate_120uL_Fb(name="canvas")
  plate_carrier[0] = canvas
  deck.assign_child_resource(plate_carrier, rails=7)

  reservoir_carrier = Trough_CAR_5R60_A00(name="reservoir_carrier_1")
  ink_reservoir = hamilton_1_trough_60mL_Vb(name="ink_reservoir")
  reservoir_carrier[0] = ink_reservoir
  deck.assign_child_resource(reservoir_carrier, rails=13)

  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()

  inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
  backend = VisualizerBackend(inner_backend, server)
  lh = LiquidHandler(backend=backend, deck=deck)
  await lh.setup()  # also turns on tip/volume tracking -- see VisualizerBackend docstring

  # 64 wells x 20uL = 1280uL total -- this is a generous, simple fixed fill,
  # not a computed-to-the-drop one, since (unlike picogreen_demo.py) nothing
  # here varies at run time.
  ink_reservoir.tracker.set_volume(5000.0)

  # Wait for you to open the visualizer, check the initial state, and click
  # "Start Protocol" -- see demo_protocol.py for why backend.wait_for_start()
  # (not server.wait_for_start()) matters here: it re-syncs state so the
  # pre-fill above is visible from the very first frame.
  print("Open the visualizer, then click 'Start Protocol' when ready.")
  await backend.wait_for_start()
  print("Started.")

  wells = heart_wells()
  batches = [wells[i : i + BATCH_SIZE] for i in range(0, len(wells), BATCH_SIZE)]

  await lh.pick_up_tips(tip_rack["A1:H1"])
  for batch in batches:
    n = len(batch)
    dest_wells = canvas[batch]
    await lh.aspirate([ink_reservoir] * n, vols=[INK_VOLUME_UL] * n, spread="wide")
    # Each batch's 8 wells are scattered across multiple columns -- an
    # ordinary multi-channel dispense call. The visualizer works out the
    # real column-by-column gantry motion on its own (see this module's
    # docstring).
    await lh.dispense(dest_wells, vols=[INK_VOLUME_UL] * n)
  await lh.discard_tips()

  print("Pixel-art demo finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

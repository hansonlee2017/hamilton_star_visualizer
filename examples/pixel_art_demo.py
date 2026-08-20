"""Pixel-art demo: paint "ROCHE" across five 96-well Corning plates, one
letter per plate in portrait orientation, using a Hamilton multi-dispense
pattern -- aspirate 300uL, then dispense it back out in ten 30uL steps
without re-aspirating -- pulling every drop from a single shared 60mL
reservoir.

Portrait orientation: a 96-well plate is natively 12 columns x 8 rows
(wider than tall). Each letter's own bitmap (``LETTERS`` below, 12 rows x
8 columns, hand-drawn block letters) is mapped onto the plate with the
*bitmap's* row axis (12, its tall dimension) landing on the plate's
*column* axis (also 12) and the bitmap's column axis (8) landing on the
plate's *row* axis (also 8) -- so the letter reads correctly once the
physical plate is rotated 90 degrees from its native landscape orientation.

Multi-dispense: every bitmap row is at most 8 cells wide -- i.e. it never
needs more than one dispense per channel -- and, because of the portrait
mapping above, every cell in one bitmap row shares the *same plate column*
(``letter_row_batches()`` below), so it's naturally both a single
8-channel dispense call *and* a single gantry pass (see
``frontend/main.js``'s ``planGantryPasses()``) -- no rechunking needed to
keep dispenses column-aligned. A letter's 12 rows batch into 2 aspirate
cycles of up to 10 dispenses each (300uL / 30uL = 10 dispenses per
aspirate, exactly the "10 pixels per channel" this demo was asked for):
aspirate once for all 8 channels, then dispense row by row without
aspirating again until that cycle's rows are used up.

One tip pick-up per letter, spanning both of its aspirate cycles: a bitmap
row's width varies (3-8 cells), so a channel that isn't needed on every
row of a 10-row cycle ends the cycle still holding leftover volume (e.g.
one of "R"'s channels dispenses only 2 of that cycle's 10 rows, leaving
240uL after only 60uL dispensed) -- reusing that tip for the next cycle's
fresh 300uL aspirate would overflow it (240 + 300 > the tip's 360uL
capacity; confirmed live -- see docs/PLAN.md's "Review round 30"). Rather
than discarding tips to dodge that (wasting whatever ink each tip was
still holding), each cycle ends by dispensing every channel's *actual*
leftover back into the reservoir -- computed from how many of that
cycle's rows each channel's own row letter actually appeared in, using
PyLabRobot's real ``empty=True`` dispense-mode flag (a genuine
``STARBackend.dispense()`` kwarg, forwarded through like any other
backend kwarg -- see ``visualizer_backend.py``'s ``dispense()``) to mark
it as *fully* emptying the tip rather than a specific measured volume,
matching how you'd actually write this for real hardware. That leaves
every tip genuinely empty and ready to aspirate again without ever
discarding it mid-letter -- there's no cross-contamination risk a fresh
tip would otherwise be guarding against anyway (every dispense lands in a
still-empty well, same reasoning as picogreen_demo.py's PicoGreen
transfer stage), so reusing the tip costs nothing and returning the ink
avoids wasting it.

Deliberately no ``asyncio.sleep()`` calls anywhere in this script -- see
picogreen_demo.py's module docstring for the full reasoning.

Run it with:

    uv run python examples/pixel_art_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765).
"""

from __future__ import annotations

import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARLetDeck,
  Trough_CAR_5R60_A00,
  cor_96_wellplate_360uL_Fb,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_300uL_filter,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer

# 8 rows (A-H) -- a 96-well plate's short axis, which the letter bitmaps'
# column axis (also 8 wide) maps onto; see this module's docstring.
PLATE_ROWS = "ABCDEFGH"

# Five bold block letters, each 12 rows (the bitmap's own "tall" axis,
# mapped onto the plate's 12 columns) x 8 columns (mapped onto the plate's
# 8 rows) -- see this module's docstring for the portrait mapping. Hand-
# drawn and verified by rendering before use (every row is exactly 8
# characters; printed with '#'/' ' in place of 'X'/'.', each one clearly
# legible as its own letter).
LETTERS = {
  "R": [
    "XXXXXXX.",
    "XX....X.",
    "XX....X.",
    "XX....X.",
    "XX....X.",
    "XXXXXXX.",
    "XX.X....",
    "XX..X...",
    "XX..X...",
    "XX...X..",
    "XX...X..",
    "XX....X.",
  ],
  "O": [
    ".XXXXX..",
    "XX...XX.",
    "X.....X.",
    "X.....X.",
    "X.....X.",
    "X.....X.",
    "X.....X.",
    "X.....X.",
    "X.....X.",
    "X.....X.",
    "XX...XX.",
    ".XXXXX..",
  ],
  "C": [
    ".XXXXX..",
    "XX...XX.",
    "X.......",
    "X.......",
    "X.......",
    "X.......",
    "X.......",
    "X.......",
    "X.......",
    "X.......",
    "XX...XX.",
    ".XXXXX..",
  ],
  "H": [
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XXXXXXXX",
    "XXXXXXXX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
  ],
  "E": [
    "XXXXXXXX",
    "XXXXXXXX",
    "XX......",
    "XX......",
    "XX......",
    "XXXXXXX.",
    "XXXXXXX.",
    "XX......",
    "XX......",
    "XX......",
    "XXXXXXXX",
    "XXXXXXXX",
  ],
}
WORD = "ROCHE"
for _letter in WORD:
  _bitmap = LETTERS[_letter]
  assert len(_bitmap) == 12, f"{_letter}: bitmap must be 12 rows tall"
  assert all(len(row) == 8 for row in _bitmap), f"{_letter}: every row must be 8 characters wide"

ASPIRATE_VOLUME_UL = 300.0
DISPENSE_VOLUME_UL = 30.0
DISPENSES_PER_ASPIRATE = int(ASPIRATE_VOLUME_UL // DISPENSE_VOLUME_UL)  # 10


def letter_row_batches(letter: str) -> list[tuple[str, str]]:
  """``(column, rows)`` pairs, one per bitmap row of ``LETTERS[letter]`` --
  ``rows`` a string of plate row letters (A-H), one per filled cell in that
  bitmap row. Every batch is already both <=8 wells (one dispense's worth)
  and all in the *same* plate column (the portrait mapping's whole point --
  see this module's docstring), so grouping dispenses by bitmap row is
  exactly grouping them by plate column, with no separate rechunking step
  needed to keep each dispense a single gantry pass.

  The bitmap column index is read *reversed* (``PLATE_ROWS[7 - c]``, not
  ``PLATE_ROWS[c]``): swapping row<->column with neither axis reversed is a
  transpose, and a plain transpose is a *reflection*, not a rotation -- it
  mirrored every letter left-right (confirmed live: "R" rendered as a
  mirror image on the plate -- see docs/PLAN.md's "Review round 30").
  Reversing one axis while swapping turns that reflection into the
  intended 90-degree rotation instead.

  ``rows`` is sorted ascending (A before H) before being returned, and
  ``main()`` below always dispenses to channel ``PLATE_ROWS.index(row)``
  for each row letter -- not PyLabRobot's positional default (channel 0
  gets the first resource, etc) -- so channel index always lines up with
  plate row (channel 0 -> row A, channel 1 -> row B, ...), consistently
  across every row-batch of a letter, not just within one call. A real
  gantry channel is physically fixed to its row; a channel that ends up
  targeting a different row from one dispense to the next would be
  reaching diagonally for no reason, and per-channel leftover-volume
  bookkeeping below (see ``main()``) depends on a channel meaning the same
  row every time.
  """

  batches = []
  for r, row_pattern in enumerate(LETTERS[letter]):
    rows = "".join(sorted(PLATE_ROWS[7 - c] for c, ch in enumerate(row_pattern) if ch == "X"))
    if rows:
      batches.append((str(r + 1), rows))
  return batches


def chunked(seq: list, n: int) -> list[list]:
  return [seq[i : i + n] for i in range(0, len(seq), n)]


async def main() -> None:
  # -- deck layout: a tip carrier, a 5-site plate carrier, a reservoir -----
  deck = STARLetDeck()

  tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
  tip_rack = hamilton_96_tiprack_300uL_filter(name="tip_rack_300uL")
  tip_carrier[0] = tip_rack
  deck.assign_child_resource(tip_carrier, rails=1)

  # PLT_CAR_L5AC_A00 -- the "L5" is 5 plate sites, exactly enough for one
  # per letter of "ROCHE", in reading order (site 0 = R, ..., site 4 = E).
  plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
  plates = {}
  for i, letter in enumerate(WORD):
    plate = cor_96_wellplate_360uL_Fb(name=f"plate_{letter}")
    plate_carrier[i] = plate
    plates[letter] = plate
  deck.assign_child_resource(plate_carrier, rails=7)

  reservoir_carrier = Trough_CAR_5R60_A00(name="reservoir_carrier_1")
  ink_reservoir = hamilton_1_trough_60mL_Vb(name="ink_reservoir")
  reservoir_carrier[2] = ink_reservoir
  deck.assign_child_resource(reservoir_carrier, rails=13)

  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()

  inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
  backend = VisualizerBackend(inner_backend, server)
  lh = LiquidHandler(backend=backend, deck=deck)
  await lh.setup()  # also turns on tip/volume tracking -- see VisualizerBackend docstring

  # 218 filled wells total across all 5 letters (44+34+26+56+58 -- R/O/C/H/E
  # respectively) x 30uL = 6,540uL actually *delivered*. Every aspirate
  # cycle draws a full 300uL/channel regardless of that cycle's real need,
  # but the leftover goes back to the reservoir at the end of each cycle
  # (see the main loop below), so the reservoir's net drawdown matches the
  # delivered total, not the much larger amount actually aspirated over the
  # run -- a generous fixed fill well above that, not computed to the drop,
  # since nothing here varies at run time.
  ink_reservoir.tracker.set_volume(10_000.0)

  # Wait for you to open the visualizer, check the initial state, and click
  # "Start Protocol" -- see demo_protocol.py for why backend.wait_for_start()
  # (not server.wait_for_start()) matters here: it re-syncs state so the
  # pre-fill above is visible from the very first frame.
  print("Open the visualizer, then click 'Start Protocol' when ready.")
  await backend.wait_for_start()
  print("Started.")

  # One tip-rack column per letter (5 total), spanning both of that
  # letter's aspirate cycles -- tips are reused between cycles (see the
  # empty=True return-to-reservoir step below), not discarded and re-picked.
  for tip_column, letter in enumerate(WORD, start=1):
    plate = plates[letter]
    row_batches = letter_row_batches(letter)

    await lh.pick_up_tips(tip_rack[f"A{tip_column}:H{tip_column}"])
    for cycle in chunked(row_batches, DISPENSES_PER_ASPIRATE):
      # All 8 channels aspirate a full 300uL every cycle, regardless of
      # how many of that cycle's rows any one channel actually ends up
      # dispensing into -- "10 pixels per channel" per aspirate, not a
      # tighter per-cycle estimate.
      await lh.aspirate([ink_reservoir] * 8, vols=[ASPIRATE_VOLUME_UL] * 8, spread="wide")
      dispense_count = {row: 0 for row in PLATE_ROWS}
      for col, rows in cycle:
        use_channels = [PLATE_ROWS.index(row) for row in rows]
        dest_wells = plate[[f"{row}{col}" for row in rows]]
        await lh.dispense(dest_wells, vols=[DISPENSE_VOLUME_UL] * len(rows), use_channels=use_channels)
        for row in rows:
          dispense_count[row] += 1
      # Return each channel's actual leftover to the reservoir instead of
      # discarding it with the tip -- see this module's docstring for why
      # (and for `empty=True`, PyLabRobot's real "fully empty the tip"
      # dispense-mode flag).
      leftover_channels = [
        i for i, row in enumerate(PLATE_ROWS) if dispense_count[row] < DISPENSES_PER_ASPIRATE
      ]
      if leftover_channels:
        leftover_vols = [
          ASPIRATE_VOLUME_UL - dispense_count[PLATE_ROWS[i]] * DISPENSE_VOLUME_UL
          for i in leftover_channels
        ]
        await lh.dispense(
          [ink_reservoir] * len(leftover_channels),
          vols=leftover_vols,
          use_channels=leftover_channels,
          spread="wide",
          empty=True,
        )
    await lh.discard_tips()

  print("Pixel-art demo finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

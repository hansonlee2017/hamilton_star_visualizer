"""Pixel-art demo: print any 5-character word (A-Z0-9, entered in the HUD)
across five 96-well Corning plates, one character per plate in portrait
orientation, using a Hamilton multi-dispense pattern -- aspirate 300uL
once, then dispense it back out in several equal steps without
re-aspirating -- pulling every drop from a single shared 60mL reservoir.
Both the word and the per-well dispense volume (30-150uL) are HUD inputs,
not hardcoded (see "HUD inputs" below).

Character bitmaps: all 36 characters (A-Z, 0-9) are pre-generated, not
computed at runtime -- ``PATTERNS`` below is a plain 36-entry literal dict,
each value 12 rows x 8 columns of ``'X'``/``'.'``, produced once, offline,
by rasterizing Arial Bold through Pillow (a one-off generation script, not
a runtime dependency of this module -- see docs/PLAN.md's "Review round
32" for exactly how) and pasting the result in verbatim. ``main()`` never
draws or generates a character -- it only ever does a ``PATTERNS[ch]``
dict lookup, which is what actually makes arbitrary 5-character input
practical: no per-run font rendering, just recall.

Portrait orientation: a 96-well plate is natively 12 columns x 8 rows
(wider than tall). Each character's own bitmap (12 rows x 8 columns) is
mapped onto the plate with the *bitmap's* row axis (12, its tall
dimension) landing on the plate's *column* axis (also 12) and the
bitmap's column axis (8) landing on the plate's *row* axis (also 8) -- so
the character reads correctly once the physical plate is rotated 90
degrees from its native landscape orientation.

Multi-dispense: every bitmap row is at most 8 cells wide -- i.e. it never
needs more than one dispense per channel -- and, because of the portrait
mapping above, every cell in one bitmap row shares the *same plate column*
(``pattern_row_batches()`` below), so it's naturally both a single
8-channel dispense call *and* a single gantry pass (see
``frontend/main.js``'s ``planGantryPasses()``) -- no rechunking needed to
keep dispenses column-aligned. A character's 12 rows batch into aspirate
cycles of up to ``dispenses_per_aspirate`` dispenses each (``300uL //
dispense_volume_ul``, computed at runtime from the HUD's chosen volume --
10 at the default 30uL, as few as 2 at 150uL): aspirate once for all 8
channels, then dispense row by row without aspirating again until that
cycle's rows are used up.

One tip pick-up per character, spanning all of its aspirate cycles: a
bitmap row's width varies (0-8 cells), so a channel that isn't needed on
every row of a cycle ends the cycle still holding leftover volume --
reusing that tip for the next cycle's fresh 300uL aspirate could overflow
it (confirmed live at the old fixed 30uL setting -- see docs/PLAN.md's
"Review round 30"). Rather than discarding tips to dodge that, each cycle
ends by dispensing every channel's *actual* leftover back into the
reservoir -- computed from how many of that cycle's rows each channel's
own row letter actually appeared in, using PyLabRobot's real
``empty=True`` dispense-mode flag (a genuine ``STARBackend.dispense()``
kwarg, forwarded through like any other backend kwarg -- see
``visualizer_backend.py``'s ``dispense()``) to mark it as *fully* emptying
the tip rather than a specific measured volume, matching how you'd
actually write this for real hardware. That leaves every tip genuinely
empty and ready to aspirate again without ever discarding it mid-
character -- there's no cross-contamination risk a fresh tip would
otherwise be guarding against anyway (every dispense lands in a still-
empty well, same reasoning as picogreen_demo.py's PicoGreen transfer
stage), so reusing the tip costs nothing and returning the ink avoids
wasting it.

HUD inputs (see ``VisualizerServer.set_run_params()``'s docstring for the
field schema this demo is the first to use a "text" field from):

  - **Word** (exactly 5 characters, A-Z0-9): sanitized (uppercased,
    non-alnum stripped) and length-capped as you type, and "Start
    Protocol" stays disabled until it's exactly 5 characters long -- see
    ``main.js``'s ``runParamsValid()``. Read back as ``params["word"]``,
    then re-sanitized server-side by ``_clamped_word()`` below (never
    trust a value that crossed a websocket, same reasoning as every
    numeric HUD field in this repo).
  - **Volume** (30-150uL): the per-well dispense volume. Everything about
    the aspirate-cycle chunking, leftover-return accounting, and reservoir
    pre-fill below is computed *from* this at runtime -- nothing is
    hardcoded to the old fixed 30uL.

Reservoir pre-fill is computed dynamically, right after "Start Protocol"
is clicked (once the actual word and volume are known): enough for every
filled well this specific run actually delivers, plus a fixed margin --
capped at the trough's real 60mL capacity, the same residual-guarantee
shape ``picogreen_demo.py`` uses for its own reservoir. The margin itself
can't be small the way PicoGreen's is, though: every aspirate cycle here
draws the *full* 8 x 300uL = 2400uL from the reservoir instantly, and only
returns that cycle's actual leftover a few dispenses later (see
``RESIDUAL_INK_UL``'s own comment) -- so the pre-fill has to cover that
single largest in-flight draw, not just the run's much smaller net
delivery total. A flat constant (this demo's pre-round-32 style) can't
work at all anymore now that the total ink needed varies with both the
chosen characters and the chosen volume.

Deliberately no ``asyncio.sleep()`` calls anywhere in this script -- see
picogreen_demo.py's module docstring for the full reasoning.

Run it with:

    uv run python examples/pixel_art_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), type a
5-character word and pick a dispense volume in the HUD, and click "Start
Protocol".
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

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
from pylabrobot.resources.plate import Plate

from hamilton_visualizer import VisualizerBackend, VisualizerServer

# 8 rows (A-H) -- a 96-well plate's short axis, which the character
# bitmaps' column axis (also 8 wide) maps onto; see this module's
# docstring.
PLATE_ROWS = "ABCDEFGH"

WORD_LENGTH = 5  # PLT_CAR_L5AC_A00 has exactly 5 plate sites

# All 36 characters (A-Z, 0-9), each 12 rows (the bitmap's own "tall" axis,
# mapped onto the plate's 12 columns) x 8 columns (mapped onto the plate's
# 8 rows) -- see this module's docstring for the portrait mapping and
# where this data actually comes from (rasterized once, offline, from
# Arial Bold -- not hand-drawn, not generated at runtime).
PATTERNS: Dict[str, List[str]] = {
  "A": [
    "........",
    "...XX...",
    "..XXXX..",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    ".XX..XX.",
    "XXXXXXXX",
    "XXXXXXXX",
    "XX....XX",
    "XX....XX",
    "........",
  ],
  "B": [
    "........",
    "XXXXXXX.",
    "XXXXXXXX",
    "XX....XX",
    "XX...XXX",
    "XXXXXXX.",
    "XXXXXXXX",
    "XX....XX",
    "XX....XX",
    "XXXXXXXX",
    "XXXXXXX.",
    "........",
  ],
  "C": [
    "........",
    "..XXXXX.",
    ".XXXXXXX",
    "XXX...XX",
    "XX......",
    "XX......",
    "XX......",
    "XX....XX",
    "XXX...XX",
    ".XXXXXXX",
    "..XXXXX.",
    "........",
  ],
  "D": [
    "........",
    "XXXXXX..",
    "XXXXXXXX",
    "XX...XXX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX...XXX",
    "XXXXXXXX",
    "XXXXXX..",
    "........",
  ],
  "E": [
    "........",
    "XXXXXXXX",
    "XXXXXXXX",
    "XXX.....",
    "XXX.....",
    "XXXXXXXX",
    "XXXXXXX.",
    "XXX.....",
    "XXX.....",
    "XXXXXXXX",
    "XXXXXXXX",
    "........",
  ],
  "F": [
    "........",
    ".XXXXXXX",
    ".XXXXXXX",
    ".XX.....",
    ".XX.....",
    ".XXXXXX.",
    ".XXXXXX.",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    "........",
  ],
  "G": [
    "........",
    ".XXXXXX.",
    "XXXXXXXX",
    "XX....XX",
    "XX......",
    "XX...XXX",
    "XX..XXXX",
    "XX...XXX",
    "XX....XX",
    "XXXXXXXX",
    ".XXXXXXX",
    "........",
  ],
  "H": [
    "........",
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
    "........",
  ],
  "I": [
    "........",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "........",
  ],
  "J": [
    "........",
    ".....XX.",
    ".....XX.",
    ".....XX.",
    ".....XX.",
    ".....XX.",
    ".....XX.",
    ".X...XX.",
    "XXX.XXX.",
    ".XXXXXX.",
    ".XXXXX..",
    "........",
  ],
  "K": [
    "........",
    "XX...XXX",
    "XX...XXX",
    "XX..XXX.",
    "XX.XXX..",
    "XXXXXX..",
    "XXXXXX..",
    "XXX.XXX.",
    "XX...XXX",
    "XX...XXX",
    "XX....XX",
    "........",
  ],
  "L": [
    "........",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    ".XX.....",
    ".XXXXXXX",
    ".XXXXXXX",
    "........",
  ],
  "M": [
    "........",
    "XXX...XX",
    "XXX..XXX",
    "XXX..XXX",
    "XXX..XXX",
    "XXXXXXXX",
    "X.XXXX.X",
    "X.XXXX.X",
    "X.XXXX.X",
    "X..XXX.X",
    "X..XX..X",
    "........",
  ],
  "N": [
    "........",
    "XX....XX",
    "XXX...XX",
    "XXXX..XX",
    "XXXX..XX",
    "XXXXX.XX",
    "XX.XXXXX",
    "XX..XXXX",
    "XX..XXXX",
    "XX...XXX",
    "XX...XXX",
    "........",
  ],
  "O": [
    "........",
    ".XXXXXX.",
    "XXXXXXXX",
    "XX....XX",
    "XX....XX",
    "XX.....X",
    "XX.....X",
    "XX....XX",
    "XX....XX",
    "XXXXXXXX",
    ".XXXXXX.",
    "........",
  ],
  "P": [
    "........",
    "XXXXXXX.",
    "XXXXXXXX",
    "XXX...XX",
    "XXX...XX",
    "XXXXXXXX",
    "XXXXXXX.",
    "XXX.....",
    "XXX.....",
    "XXX.....",
    "XXX.....",
    "........",
  ],
  "Q": [
    "..XXXX..",
    ".XXXXXX.",
    "XXX..XXX",
    "XX....XX",
    "XX....XX",
    "XX.....X",
    "XX....XX",
    "XX..X.XX",
    "XXX.XXXX",
    ".XXXXXXX",
    "..XXXXXX",
    "........",
  ],
  "R": [
    "........",
    "XXXXXXX.",
    "XXXXXXXX",
    "XX....XX",
    "XX....XX",
    "XXXXXXXX",
    "XXXXXXX.",
    "XX..XXX.",
    "XX...XXX",
    "XX...XXX",
    "XX....XX",
    "........",
  ],
  "S": [
    "........",
    ".XXXXXX.",
    "XXXXXXX.",
    "XX...XXX",
    "XXXX....",
    ".XXXXXX.",
    "..XXXXXX",
    "XX...XXX",
    "XX....XX",
    "XXXXXXXX",
    ".XXXXXX.",
    "........",
  ],
  "T": [
    "........",
    "XXXXXXXX",
    "XXXXXXXX",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "........",
  ],
  "U": [
    "........",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XX....XX",
    "XXX..XXX",
    "XXXXXXXX",
    ".XXXXXX.",
    "........",
  ],
  "V": [
    "........",
    "XX....XX",
    "XX....XX",
    "XXX..XXX",
    "XXX..XXX",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "..XXXX..",
    "..XXXX..",
    "...XX...",
    "........",
  ],
  "W": [
    "........",
    "...XXX..",
    "..XXXX..",
    "..XXXX..",
    "X.XXXX..",
    "XXXXXXXX",
    "XXX..XXX",
    "XXX..XXX",
    "XXX..XXX",
    "XXX..XXX",
    "XX....XX",
    "........",
  ],
  "X": [
    "........",
    "XXX..XXX",
    "XXX..XXX",
    ".XXXXXX.",
    "..XXXX..",
    "..XXXX..",
    "..XXXX..",
    "..XXXXX.",
    ".XXXXXX.",
    "XXX..XXX",
    "XX....XX",
    "........",
  ],
  "Y": [
    "........",
    "XX....XX",
    "XXX..XXX",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "...XX...",
    "........",
  ],
  "Z": [
    "........",
    "XXXXXXXX",
    "XXXXXXXX",
    "....XXX.",
    "....XX..",
    "...XXX..",
    "..XXX...",
    ".XXX....",
    "XXX.....",
    "XXXXXXXX",
    "XXXXXXXX",
    "........",
  ],
  "0": [
    "........",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    ".XX..XX.",
    ".XX..XX.",
    ".XX..XX.",
    ".XX..XX.",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "........",
  ],
  "1": [
    "........",
    "....XX..",
    "...XXX..",
    ".XXXXX..",
    ".XXXXX..",
    "...XXX..",
    "...XXX..",
    "...XXX..",
    "...XXX..",
    "...XXX..",
    "....XX..",
    "........",
  ],
  "2": [
    "........",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    ".....XX.",
    "....XXX.",
    "...XXX..",
    "..XXX...",
    ".XXX....",
    ".XXXXXX.",
    "XXXXXXX.",
    "........",
  ],
  "3": [
    "........",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    "....XXX.",
    "...XXX..",
    "...XXXX.",
    ".....XX.",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "........",
  ],
  "4": [
    "........",
    "....XX..",
    "....XXX.",
    "...XXXX.",
    "..XXXXX.",
    ".XXXXXX.",
    ".XX.XXX.",
    "XXXXXXXX",
    "XXXXXXXX",
    "....XXX.",
    "....XX..",
    "........",
  ],
  "5": [
    "........",
    "..XXXXX.",
    "..XXXXX.",
    ".XX.....",
    ".XXXXX..",
    ".XXXXXX.",
    "..X..XXX",
    ".....XXX",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "........",
  ],
  "6": [
    "........",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    ".XX.X...",
    ".XXXXXX.",
    ".XX..XX.",
    ".XX..XXX",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "........",
  ],
  "7": [
    "........",
    ".XXXXXX.",
    ".XXXXXX.",
    "....XXX.",
    "....XX..",
    "...XX...",
    "...XX...",
    "..XXX...",
    "..XX....",
    "..XX....",
    "..XX....",
    "........",
  ],
  "8": [
    "........",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    ".XX.XXX.",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "........",
  ],
  "9": [
    "........",
    "..XXXX..",
    ".XXXXXX.",
    ".XX..XX.",
    "XXX..XX.",
    ".XX..XX.",
    ".XXXXXX.",
    "..XX.XX.",
    ".XX..XX.",
    ".XXXXXX.",
    "..XXXX..",
    "........",
  ],
}
for _ch, _bitmap in PATTERNS.items():
  assert len(_bitmap) == 12, f"{_ch}: bitmap must be 12 rows tall"
  assert all(len(row) == 8 for row in _bitmap), f"{_ch}: every row must be 8 characters wide"

DEFAULT_WORD = "ROCHE"

ASPIRATE_VOLUME_UL = 300.0  # fixed -- comfortably under the tip's 360uL capacity
# Matches index.html's HUD volume input's min/max/default -- see
# server.set_run_params() below, built directly from these constants.
MIN_DISPENSE_VOLUME_UL, MAX_DISPENSE_VOLUME_UL, DEFAULT_DISPENSE_VOLUME_UL = 30.0, 150.0, 30.0

# Every aspirate cycle draws the *full* 8-channel x 300uL = 2400uL from the
# reservoir instantly, before that cycle's actual leftover is returned a
# few dispenses later (see main()'s leftover-return step) -- so it's not
# enough for the pre-fill to just cover total *net* ink delivered, or the
# very last aspirate of a run could momentarily need more than what's left
# after every prior cycle's net draw, even though the run's total delivery
# never gets close to the reservoir's capacity. 2,500uL comfortably covers
# that single largest in-flight draw (2,400uL) with a small margin, and
# also ends up as the amount left over once the run finishes (nothing here
# ever gets returned *below* what an in-progress cycle temporarily holds).
RESIDUAL_INK_UL = 2_500.0
TROUGH_MAX_VOLUME_UL = 60_000.0


def pattern_row_batches(ch: str) -> list[tuple[str, str]]:
  """``(column, rows)`` pairs, one per bitmap row of ``PATTERNS[ch]`` --
  ``rows`` a string of plate row letters (A-H), one per filled cell in that
  bitmap row. Every batch is already both <=8 wells (one dispense's worth)
  and all in the *same* plate column (the portrait mapping's whole point --
  see this module's docstring), so grouping dispenses by bitmap row is
  exactly grouping them by plate column, with no separate rechunking step
  needed to keep each dispense a single gantry pass.

  The bitmap column index is read *reversed* (``PLATE_ROWS[7 - c]``, not
  ``PLATE_ROWS[c]``): swapping row<->column with neither axis reversed is a
  transpose, and a plain transpose is a *reflection*, not a rotation -- it
  mirrored every character left-right (confirmed live: "R" rendered as a
  mirror image on the plate -- see docs/PLAN.md's "Review round 30").
  Reversing one axis while swapping turns that reflection into the
  intended 90-degree rotation instead.

  ``rows`` is sorted ascending (A before H) before being returned, and
  ``main()`` below always dispenses to channel ``PLATE_ROWS.index(row)``
  for each row letter -- not PyLabRobot's positional default (channel 0
  gets the first resource, etc) -- so channel index always lines up with
  plate row (channel 0 -> row A, channel 1 -> row B, ...), consistently
  across every row-batch of a character, not just within one call. A real
  gantry channel is physically fixed to its row; a channel that ends up
  targeting a different row from one dispense to the next would be
  reaching diagonally for no reason, and per-channel leftover-volume
  bookkeeping below (see ``main()``) depends on a channel meaning the same
  row every time.
  """

  batches = []
  for r, row_pattern in enumerate(PATTERNS[ch]):
    rows = "".join(sorted(PLATE_ROWS[7 - c] for c, mark in enumerate(row_pattern) if mark == "X"))
    if rows:
      batches.append((str(r + 1), rows))
  return batches


def chunked(seq: list, n: int) -> list[list]:
  return [seq[i : i + n] for i in range(0, len(seq), n)]


def _clamped_param(params: Dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
  """Read ``key`` out of the "Start Protocol" click's params dict, falling
  back to ``default`` for anything missing or unparseable, and clamping to
  ``[lo, hi]`` regardless -- the value crossed a websocket from a browser,
  so it's treated the same as any other untrusted external input (argv, a
  config file) rather than trusted outright. Same helper picogreen_demo.py
  uses for its own numeric HUD fields.
  """

  try:
    value = float(params.get(key, default))
  except (TypeError, ValueError):
    value = default
  return max(lo, min(hi, value))


def _clamped_word(raw: Any, default: str) -> str:
  """Sanitize a "Start Protocol" click's raw ``word`` param the same "never
  trust it, always fall back to something valid" way ``_clamped_param()``
  handles numeric fields -- uppercases, strips anything that isn't a real
  ``PATTERNS`` key, then pads with ``default``'s own characters (and
  truncates) if what's left isn't exactly ``WORD_LENGTH``.

  The HUD's own "text" field validation (main.js's ``runParamsValid()``)
  already keeps a real browser from ever sending something short enough to
  need the padding branch here -- this mostly matters for a non-browser
  client, a hand-crafted message, or a stray lowercase/symbol character
  that made it past client-side sanitization somehow.
  """

  text = "".join(ch for ch in str(raw or "").upper() if ch in PATTERNS)
  if len(text) < WORD_LENGTH:
    text = (text + default)[:WORD_LENGTH]
  return text[:WORD_LENGTH]


async def main() -> None:
  # -- deck layout: a tip carrier, a 5-site plate carrier, a reservoir -----
  deck = STARLetDeck()

  tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
  tip_rack = hamilton_96_tiprack_300uL_filter(name="tip_rack_300uL")
  tip_carrier[0] = tip_rack
  deck.assign_child_resource(tip_carrier, rails=1)

  # PLT_CAR_L5AC_A00 -- the "L5" is 5 plate sites, one per character of
  # whatever word ends up chosen. Named by *position* (plate_0..plate_4),
  # not by character -- a word can repeat a character (e.g. "HELLO"), so a
  # character can't be used as a unique key the way the old fixed "ROCHE"
  # demo's plate_R/plate_O/... naming did.
  plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
  plates: List[Plate] = []
  for i in range(WORD_LENGTH):
    plate = cor_96_wellplate_360uL_Fb(name=f"plate_{i}")
    plate_carrier[i] = plate
    plates.append(plate)
  deck.assign_child_resource(plate_carrier, rails=7)

  reservoir_carrier = Trough_CAR_5R60_A00(name="reservoir_carrier_1")
  ink_reservoir = hamilton_1_trough_60mL_Vb(name="ink_reservoir")
  reservoir_carrier[2] = ink_reservoir
  deck.assign_child_resource(reservoir_carrier, rails=13)

  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()
  await server.set_run_params(
    [
      {
        "id": "word",
        "type": "text",
        "label": "Word",
        "length": WORD_LENGTH,
        "default": DEFAULT_WORD,
        "title": f"{WORD_LENGTH} letters/numbers to print, one per plate (A-Z, 0-9)",
      },
      {
        "id": "dispense_volume_ul",
        "type": "number",
        "label": "Volume",
        "min": MIN_DISPENSE_VOLUME_UL,
        "max": MAX_DISPENSE_VOLUME_UL,
        "step": 1,
        "default": DEFAULT_DISPENSE_VOLUME_UL,
        "suffix": "µL",
        "title": (
          f"Per-well dispense volume "
          f"({MIN_DISPENSE_VOLUME_UL:g}-{MAX_DISPENSE_VOLUME_UL:g}uL)"
        ),
      },
    ]
  )

  inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
  backend = VisualizerBackend(inner_backend, server)
  lh = LiquidHandler(backend=backend, deck=deck)
  await lh.setup()  # also turns on tip/volume tracking -- see VisualizerBackend docstring

  # server.wait_for_start() (not backend.wait_for_start()) deliberately
  # skips backend's usual post-click state resync here -- the reservoir's
  # required fill depends on the word/volume just chosen and can't be
  # computed until after the click (see below). backend.broadcast_state()
  # does the same resync once that fill is actually done -- same pattern
  # picogreen_demo.py uses for its own param-dependent reservoir.
  print("Open the visualizer, then click 'Start Protocol' when ready.")
  params = await server.wait_for_start()
  word = _clamped_word(params.get("word"), DEFAULT_WORD)
  dispense_volume = _clamped_param(
    params, "dispense_volume_ul", DEFAULT_DISPENSE_VOLUME_UL, MIN_DISPENSE_VOLUME_UL, MAX_DISPENSE_VOLUME_UL
  )
  dispenses_per_aspirate = max(1, int(ASPIRATE_VOLUME_UL // dispense_volume))
  print(f"Started: printing {word!r} at {dispense_volume:g}uL/well.")

  # Enough ink for every filled well this specific word actually needs,
  # plus a fixed residual left over at the end -- not a flat guess at the
  # *starting* fill (impossible now that both the word and the volume
  # vary), a guaranteed *residual*, the same style picogreen_demo.py uses
  # for its own reservoir. Capped at the trough's real 60mL capacity.
  total_filled_wells = sum(sum(row.count("X") for row in PATTERNS[ch]) for ch in word)
  required_ink = total_filled_wells * dispense_volume + RESIDUAL_INK_UL
  ink_reservoir.tracker.set_volume(min(required_ink, TROUGH_MAX_VOLUME_UL))
  await backend.broadcast_state()

  # One tip-rack column per character (WORD_LENGTH total), spanning all of
  # that character's aspirate cycles -- tips are reused between cycles (see
  # the empty=True return-to-reservoir step below), not discarded and
  # re-picked.
  for tip_column, (plate, ch) in enumerate(zip(plates, word), start=1):
    row_batches = pattern_row_batches(ch)

    await lh.pick_up_tips(tip_rack[f"A{tip_column}:H{tip_column}"])
    for cycle in chunked(row_batches, dispenses_per_aspirate):
      # All 8 channels aspirate a full 300uL every cycle, regardless of
      # how many of that cycle's rows any one channel actually ends up
      # dispensing into.
      await lh.aspirate([ink_reservoir] * 8, vols=[ASPIRATE_VOLUME_UL] * 8, spread="wide")
      dispense_count = {row: 0 for row in PLATE_ROWS}
      for col, rows in cycle:
        use_channels = [PLATE_ROWS.index(row) for row in rows]
        dest_wells = plate[[f"{row}{col}" for row in rows]]
        await lh.dispense(dest_wells, vols=[dispense_volume] * len(rows), use_channels=use_channels)
        for row in rows:
          dispense_count[row] += 1
      # Return each channel's actual leftover to the reservoir instead of
      # discarding it with the tip -- see this module's docstring for why
      # (and for `empty=True`, PyLabRobot's real "fully empty the tip"
      # dispense-mode flag).
      leftover_channels = [
        i for i, row in enumerate(PLATE_ROWS) if dispense_count[row] < dispenses_per_aspirate
      ]
      if leftover_channels:
        leftover_vols = [
          ASPIRATE_VOLUME_UL - dispense_count[PLATE_ROWS[i]] * dispense_volume for i in leftover_channels
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

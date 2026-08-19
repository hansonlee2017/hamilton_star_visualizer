"""Cherry-picking demo: aspirate a column of the source plate, then have each
channel dispense independently onto a hand-picked "smiley face" pattern on
the destination plate.

Unlike ``demo_protocol.py`` (which moves a whole column to the matching
column, so every channel just shifts sideways together), the 8 destination
wells here aren't a straight row or column -- each channel has to travel to
its own, differently-offset target. That's the point of the demo: it
exercises the per-channel independent x/y animation (see frontend/main.js's
``Channel`` class) instead of the channels moving in lockstep.

Run it with:

    uv run python examples/cherry_pick_demo.py

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
  cor_96_wellplate_360uL_Fb,
  hamilton_96_tiprack_1000uL_filter,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer

# 2 eyes + a 6-point mouth curve (corners turned up, bottom flat), chosen to
# read as a smiley face on the destination plate's 8-row (A-H) x 12-column
# grid. Index i here receives whatever channel i aspirated -- i.e. source
# row A ends up at the first well below, source row B at the second, etc.
SMILEY_WELLS = ["C5", "C8", "F4", "G5", "G6", "G7", "G8", "F9"]


async def main() -> None:
  # -- deck layout: a tip carrier and a plate carrier on a STARLet deck -----
  deck = STARLetDeck()

  tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
  tip_rack = hamilton_96_tiprack_1000uL_filter(name="tip_rack_01")
  tip_carrier[0] = tip_rack
  deck.assign_child_resource(tip_carrier, rails=1)

  plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
  source_plate = cor_96_wellplate_360uL_Fb(name="source_plate")
  dest_plate = cor_96_wellplate_360uL_Fb(name="dest_plate")
  plate_carrier[0] = source_plate
  plate_carrier[1] = dest_plate
  deck.assign_child_resource(plate_carrier, rails=9)

  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()

  inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
  backend = VisualizerBackend(inner_backend, server)
  lh = LiquidHandler(backend=backend, deck=deck)
  await lh.setup()  # also turns on tip/volume tracking -- see VisualizerBackend docstring

  # Pre-fill just the column we're picking from -- everything else on the
  # source plate stays at 0uL (renders empty/black) so it's obvious which
  # wells this demo actually uses.
  for well in source_plate["A1:H1"]:
    well.set_volume(150)

  # Wait for you to open the visualizer, check the initial state, and click
  # "Start Protocol" -- see demo_protocol.py for why backend.wait_for_start()
  # (not server.wait_for_start()) matters here: it re-syncs state so the
  # pre-fill above is visible from the very first frame.
  print("Open the visualizer, then click 'Start Protocol' when ready.")
  await backend.wait_for_start()
  print("Started.")

  source_wells = source_plate["A1:H1"]
  dest_wells = dest_plate[SMILEY_WELLS]

  await lh.pick_up_tips(tip_rack["A1:H1"])
  await asyncio.sleep(0.5)

  # One aspirate: each of the 8 channels pulls from its own row of column 1.
  await lh.aspirate(source_wells, vols=[40.0] * 8)
  await asyncio.sleep(0.5)

  # One dispense: each channel independently travels to its own smiley-face
  # target well instead of the channels shifting sideways together.
  await lh.dispense(dest_wells, vols=[40.0] * 8)
  await asyncio.sleep(0.5)

  await lh.discard_tips()

  print("Cherry-picking demo finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

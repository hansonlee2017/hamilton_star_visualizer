"""Cherry-picking demo: aspirate a column of the source plate, then dispense
onto a hand-picked "smiley face" pattern on the destination plate --
column by column, the way a real Hamilton STAR actually would.

The smiley's 8 wells span 6 different columns, and a real instrument's 8
channels are all bolted to one arm with a single x motor: they can't be at
6 different x's at once. ``hamilton_visualizer.gantry.plan_gantry_passes()``
turns "channel i eventually dispenses into well W_i" into a sequence of
real, reachable arm stops -- one per distinct x -- moving only the
channel(s) with a well at that stop, and nudging any other loaded channel
just far enough on y to stay >= CHANNEL_PITCH_MM from whoever's working
(see that module's docstring for the physical reasoning). Contrast this
with the aspirate step below, which *is* a single simultaneous op, exactly
because all 8 source wells share one column (one x) to begin with.

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
from hamilton_visualizer.gantry import plan_gantry_passes

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

  # One aspirate: all 8 source wells share column 1's x, so a real Hamilton
  # reaches them in a single simultaneous pass too -- each channel just
  # pulls from its own row.
  await lh.aspirate(source_wells, vols=[40.0] * 8)
  await asyncio.sleep(0.5)

  # The smiley targets are scattered across 6 columns, so the dispense
  # can't be one simultaneous op -- plan_gantry_passes() breaks it into one
  # arm stop per column, in order, moving only the channel(s) that actually
  # have a well there and nudging any others just far enough to stay clear.
  # `initial_y` is where the aspirate above actually left each channel (its
  # own source row), so a channel isn't nudged at all until something later
  # genuinely needs the room.
  dispense_targets = {i: well for i, well in enumerate(dest_wells)}
  initial_y = {i: well.get_absolute_location(x="c", y="c", z="c").y for i, well in enumerate(source_wells)}
  for gantry_pass in plan_gantry_passes(dispense_targets, initial_y=initial_y):
    for channel, y in gantry_pass.idle_moves.items():
      await backend.nudge_channel(channel, x=gantry_pass.x, y=y)
    active_channels = list(gantry_pass.targets.keys())
    await lh.dispense(
      list(gantry_pass.targets.values()),
      use_channels=active_channels,
      vols=[40.0] * len(active_channels),
    )
    await asyncio.sleep(0.3)

  await asyncio.sleep(0.5)
  await lh.discard_tips()

  print("Cherry-picking demo finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

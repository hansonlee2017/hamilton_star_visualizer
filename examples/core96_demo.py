"""CO-RE 96 head demo: pick up all 96 tips from a full rack at once, aspirate
from every well of a source plate simultaneously, dispense into a fresh
destination plate, then drop the tips back onto the rack.

No individual 8-channel ops here -- this demo exists purely to exercise the
96-head integration (``frontend/gantry.js``'s ``Core96Head``,
``VisualizerBackend.pick_up_tips96()``/``aspirate96()``/``dispense96()``/
``drop_tips96()``) on its own. See ``cherry_pick_demo.py``/
``picogreen_demo.py`` for the per-channel side; the two mechanisms are
independent and coexist on the same deck (per design), just not both
exercised by this one script.

Rendered as a single rigid rectangular block (see ``Core96Head``'s own
comment for why it's sized to the shared SBS/ANSI footprint every touched
labware -- tip racks, plates -- already has, rather than to any one
specific resource) that moves through the same rise/x/y/descend/hold/
retract leg pattern a single ``Channel`` does, engaging an entire 96-well
plate/rack at once instead of one well/tip at a time.

Run it with:

    uv run python examples/core96_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), and click
"Start Protocol" when ready. Click "Reset" once a run finishes to watch it
again with a completely fresh scene (the same "start the entire thing
over" pattern picogreen_demo.py/thermocycler_demo.py use).
"""

from __future__ import annotations

import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARDeck,
  cor_96_wellplate_360uL_Fb,
  hamilton_96_tiprack_300uL_filter,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer

TRANSFER_VOLUME_UL = 50.0
# Enough to cover the transfer above with margin -- pre-filled uniformly
# across all 96 wells at once, since aspirate96 draws from every well
# simultaneously (a single shared volume for the whole plate, not a
# per-well amount -- see pylabrobot.liquid_handling.standard.
# MultiHeadAspirationPlate's own `volume: float` field).
SOURCE_FILL_UL = 200.0


async def main() -> None:
  server = VisualizerServer()
  await server.start()

  # "Start the entire thing over" rebuilds a completely fresh deck/backend/
  # LiquidHandler each pass -- see picogreen_demo.py's own while True: loop
  # docstring for why (PyLabRobot's tip/volume trackers and
  # VisualizerBackend's per-resource state callbacks all get a clean slate
  # this way, for free).
  while True:
    deck = STARDeck()

    tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
    tip_rack = hamilton_96_tiprack_300uL_filter(name="tip_rack_1")
    tip_carrier[0] = tip_rack
    deck.assign_child_resource(tip_carrier, rails=1)

    plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
    source_plate = cor_96_wellplate_360uL_Fb(name="source_plate")
    dest_plate = cor_96_wellplate_360uL_Fb(name="dest_plate")
    plate_carrier[0] = source_plate
    plate_carrier[1] = dest_plate
    deck.assign_child_resource(plate_carrier, rails=9)

    inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
    backend = VisualizerBackend(inner_backend, server)
    lh = LiquidHandler(backend=backend, deck=deck)
    await lh.setup()  # also broadcasts the scene and turns on tip/volume tracking -- see VisualizerBackend's docstring

    # Every well, uniformly -- aspirate96 draws from all 96 at once.
    for well in source_plate.get_all_items():
      well.set_volume(SOURCE_FILL_UL)

    # backend.wait_for_start() (not server.wait_for_start()) re-syncs state
    # so the pre-fill above is visible from the very first frame -- see
    # cherry_pick_demo.py's own comment on this same call for why.
    print("Open the visualizer, then click 'Start Protocol' when ready.")
    await backend.wait_for_start()
    print("Started.")

    print("Picking up 96 tips...")
    await lh.pick_up_tips96(tip_rack)

    print(f"Aspirating {TRANSFER_VOLUME_UL}uL from every well of the source plate...")
    await lh.aspirate96(source_plate, volume=TRANSFER_VOLUME_UL)

    print(f"Dispensing {TRANSFER_VOLUME_UL}uL into every well of the destination plate...")
    await lh.dispense96(dest_plate, volume=TRANSFER_VOLUME_UL)

    print("Dropping tips back onto the rack...")
    await lh.drop_tips96(tip_rack)

    print("CO-RE 96 head demo finished.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await lh.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  asyncio.run(main())

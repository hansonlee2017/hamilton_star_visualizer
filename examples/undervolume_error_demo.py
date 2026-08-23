"""Under-volume error handling demo: transfers 100uL of H2O from column 1
of a source 96-well flat-bottom plate to column 1 of a fresh destination
plate (8-channel, one column -- the same per-column
``lh.aspirate()``/``lh.dispense()`` shape ``pcr_setup_demo.py``'s own fill
step uses), with the actual transfer wrapped in a ``try``/``except``.

Source wells start at 150uL -- comfortably more than the 100uL this demo
draws. Right below that fill, a single **commented-out** line lets you
deliberately under-fill well D1 down to 50uL instead:

    # source_plate.get_item("D1").tracker.set_volume(50.0)

Uncomment it and re-run: with this project's own volume tracking enabled
by default (``VisualizerBackend``'s ``enable_tracking=True``), the
transfer's own ``lh.aspirate()`` call raises a real
``pylabrobot.resources.errors.TooLittleLiquidError`` the moment it reaches
D1 (trying to draw 100uL from a well that only has 50uL) -- exactly the
same kind of error PyLabRobot's own tracker would raise against real
hardware, not something this project simulates separately. The
``except`` block catches it, builds a plain description of what went
wrong, and sends an SMS alert via ``sms_message.py``'s own
``send_sms()`` (an email-to-SMS gateway, configured entirely through a
local ``.env`` file -- see that module's own docstring; nothing
credential-shaped lives in this script or gets committed).

Run it with:

    uv run python examples/undervolume_error_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), and click
"Start Protocol" when ready. With the D1 line left commented out, the
transfer succeeds and no SMS is sent. Click "Reset" once a run finishes
to watch it again with a completely fresh scene, the same "start the
entire thing over" pattern every other demo in this repo uses.
"""

from __future__ import annotations

import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  STARDeck,
  TIP_CAR_480_A00,
  cor_96_wellplate_360uL_Fb,
  hamilton_96_tiprack_300uL_filter,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer
from sms_message import send_sms

SOURCE_FILL_UL = 150.0
TRANSFER_VOLUME_UL = 100.0


async def main() -> None:
  server = VisualizerServer()
  await server.start()

  # "Start the entire thing over" rebuilds a completely fresh deck/backend/
  # LiquidHandler each pass -- see core96_demo.py's own while True: loop
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

    # Every well of column 1 pre-filled with 150uL of H2O.
    for well in source_plate["A1:H1"]:
      well.set_volume(SOURCE_FILL_UL)

    # Uncomment to deliberately under-fill D1 below the 100uL this demo
    # tries to draw -- see this module's own docstring for exactly what
    # happens once you do (a real TooLittleLiquidError, caught below, an
    # SMS alert sent).
    # source_plate.get_item("D1").tracker.set_volume(50.0)

    # backend.wait_for_start() (not server.wait_for_start()) re-syncs state
    # so the fill above (and D1's own deliberate under-fill, if
    # uncommented) is visible from the very first frame -- see
    # core96_demo.py's own comment on this same call for why.
    print("Open the visualizer, then click 'Start Protocol' when ready.")
    await backend.wait_for_start()
    print("Started.")

    try:
      print(f"Transferring {TRANSFER_VOLUME_UL:g}uL from column 1 to the destination plate...")
      await lh.pick_up_tips(tip_rack["A1:H1"])
      await lh.aspirate(source_plate["A1:H1"], vols=[TRANSFER_VOLUME_UL] * 8)
      await lh.dispense(dest_plate["A1:H1"], vols=[TRANSFER_VOLUME_UL] * 8)
      await lh.discard_tips()
      print("Transfer completed successfully.")
    except Exception as exc:  # noqa: BLE001 - deliberately broad: alert on *any* transfer failure, not just under-volume
      error_description = (
        f"Hamilton Visualizer alert: column-1 transfer failed "
        f"({type(exc).__name__}): {exc}"
      )
      print(f"Transfer failed -- sending SMS alert.\n  {error_description}")
      send_sms(error_description, subject="Hamilton Visualizer: transfer error")

    print("Under-volume error handling demo finished.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await lh.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  asyncio.run(main())

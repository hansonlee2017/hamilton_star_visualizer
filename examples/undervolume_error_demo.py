from __future__ import annotations

import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  STARLetDeck,
  TIP_CAR_480_A00,
  cor_96_wellplate_360uL_Fb,
  hamilton_96_tiprack_300uL_filter,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer
from sms_message import send_sms


# Defining volumes in the plate and transfer volumes

SOURCE_FILL_UL = 150.0
TRANSFER_VOLUME_UL = 100.0


async def main() -> None:
  server = VisualizerServer()
  await server.start()

  # Wrapped in try/finally so Ctrl-C (or any other early exit) still lets
  # the visualizer server shut down cleanly -- server.stop() tells uvicorn
  # to release its socket instead of leaving it bound, which is what was
  # producing a wall of tracebacks on Ctrl-C before (asyncio.run() abruptly
  # cancelling the server's own background task mid-request) and also
  # explains "port already in use" on the next run.
  try:
    while True:

      # setting up the deck
      deck = STARLetDeck()   # This is a Hamilton STARLet Deck

      # Put a 300 uL tip rack on tip carrier
      # Then put the tip carrier on rail 1
      tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
      tip_rack = hamilton_96_tiprack_300uL_filter(name="tip_rack_1")
      tip_carrier[0] = tip_rack
      deck.assign_child_resource(tip_carrier, rails=1)


      # Put two plates on the plate carrier
      # Then put the plate carrier on rail 9
      plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
      source_plate = cor_96_wellplate_360uL_Fb(name="source_plate")
      dest_plate = cor_96_wellplate_360uL_Fb(name="dest_plate")
      plate_carrier[0] = source_plate
      plate_carrier[1] = dest_plate
      deck.assign_child_resource(plate_carrier, rails=9)

      # Setting up the liquid hanlder with 8 channels
      inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
      backend = VisualizerBackend(inner_backend, server)
      lh = LiquidHandler(backend=backend, deck=deck)
      await lh.setup()  # also broadcasts the scene and turns on tip/volume tracking -- see VisualizerBackend's docstring

      # Every well of column 1 pre-filled with 150uL of H2O.
      for well in source_plate["A1:H1"]:
        well.set_volume(SOURCE_FILL_UL)

      # Uncomment to deliberately under-fill D1 below the 100uL this demo
      # tries to draw -- triggers a real TooLittleLiquidError, caught by the
      # except block below, which sends an SMS alert via sms_message.py.
      # source_plate.get_item("D1").tracker.set_volume(50.0)


      print("Open the visualizer, then click 'Start Protocol' when ready.")
      await backend.wait_for_start()
      print("Started.")

      try:  # This an error handling block
        print(f"Transferring {TRANSFER_VOLUME_UL:g}uL from column 1 to the destination plate...")

        # Pick up tips from A1-H1 from tip rack
        await lh.pick_up_tips(tip_rack["A1:H1"])

        # Aspirate TRANSFER_VOLUME_UL = 100 uL from the source plate, wells A1-H1
        await lh.aspirate(source_plate["A1:H1"], vols=[TRANSFER_VOLUME_UL] * 8)

        # Dispense TRANSFER_VOLUME_UL = 100 uL to the destination plate, wells A1-H1
        await lh.dispense(dest_plate["A1:H1"], vols=[TRANSFER_VOLUME_UL] * 8)

        # Discard the tips
        await lh.discard_tips()


        print("Transfer completed successfully.")
      except Exception as exc:  # noqa: BLE001 - deliberately broad: alert on *any* transfer failure, not just under-volume
        # Error handling by checking which wells fail and then inform the user via SMS

        for well in source_plate["A1:H1"]:
          well.tracker.rollback()
        short_wells = [
          f"{well.name} ({well.tracker.get_used_volume():g}uL)"
          for well in source_plate["A1:H1"]
          if well.tracker.get_used_volume() < TRANSFER_VOLUME_UL
        ]
        well_detail = f" -- short well(s): {', '.join(short_wells)}" if short_wells else ""
        error_description = (
          f"Hamilton Visualizer alert: column-1 transfer failed "
          f"({type(exc).__name__}): {exc}{well_detail}"
        )
        print(f"Transfer failed -- sending SMS alert.\n  {error_description}")

        # Actually send out a sms message
        send_sms(error_description, subject="Hamilton Visualizer: transfer error")

      print("Under-volume error handling demo finished.")
      await server.mark_finished()
      print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
      await server.wait_for_reset()
      await lh.stop()
      await server.reset_for_new_run()
      print("Reset -- waiting for a new run.")
  finally:
    print("Shutting down the visualizer server...")
    await server.stop()


if __name__ == "__main__":
  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    # Suppresses the raw KeyboardInterrupt traceback Python would otherwise
    # print here -- main()'s own try/finally above has already shut the
    # server down cleanly by the time this runs.
    print("\nStopped.")

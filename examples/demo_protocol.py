"""Runnable, hardware-free demo of the Hamilton Visualizer.

Builds a small STARLet deck (a tip carrier + a plate carrier), runs a short
pick-up-tips / aspirate / dispense / discard-tips protocol against
PyLabRobot's own ``LiquidHandlerChatterboxBackend`` (which just prints what
it's doing -- no real hardware involved), and streams every step to the
browser via ``VisualizerBackend``.

Deliberately no ``asyncio.sleep()`` calls anywhere in this script. The
browser's own animation queue is entirely decoupled from how fast these
calls actually run -- each channel's queue plays out its own real ~1.6s/leg
pace regardless of how quickly the backend sends the events that filled it
(see picogreen_demo.py's module docstring, and docs/PLAN.md's "Review
round 25", for the full reasoning and the one real tradeoff: a ``replay()``
of a run recorded without any pacing plays back in a couple of seconds
rather than at anything resembling the original pace).

Run it with:

    uv run python examples/demo_protocol.py

then open the printed URL (defaults to http://127.0.0.1:8765).

This file is meant to be read and copied: swap ``LiquidHandlerChatterboxBackend``
for ``STARChatterboxBackend`` or a real ``STARBackend`` and this is exactly
how you'd wire the visualizer into your own protocol.
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

  # pre-fill the source wells so there's something to aspirate and watch
  # drain in the visualizer (tracking is off by default in PyLabRobot, so
  # without VisualizerBackend enabling it, wells would stay at 0 uL forever)
  for well in source_plate.children:
    well.set_volume(200)

  # Wait for you to open the visualizer, check the initial deck/tip/liquid
  # state, and click "Start Protocol" -- no arbitrary timer to race against.
  # backend.wait_for_start() (not server.wait_for_start()) also re-syncs
  # state at this point, covering the well pre-fill above -- see its
  # docstring.
  print("Open the visualizer, then click 'Start Protocol' when ready.")
  await backend.wait_for_start()
  print("Started.")

  # -- a short, representative protocol: for each of the first 3 columns, ---
  # -- pick up 8 fresh tips, aspirate from the source plate, dispense to ----
  # -- the destination plate, and discard the tips to trash (discard_tips, -
  # -- not drop_tips -- see README) ------------------------------------------
  columns = ["1", "2", "3"]
  for col in columns:
    well_range = f"A{col}:H{col}"

    await lh.pick_up_tips(tip_rack[well_range])

    await lh.aspirate(source_plate[well_range], vols=[50.0] * 8)
    await lh.dispense(dest_plate[well_range], vols=[50.0] * 8)

    await lh.discard_tips()

  print("Demo protocol finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

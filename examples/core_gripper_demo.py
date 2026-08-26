"""CO-RE gripper demo: move a plate between carrier sites, then onto the
Inheco ODTC and back off it again, using the CoRe gripper (``use_arm=
"core"``) rather than the (separate, unmodeled-in-this-project) iSWAP arm.

No liquid handling here -- this demo exists purely to exercise the
CoRe-gripper integration (``VisualizerBackend.pick_up_resource()``/
``move_picked_up_resource()``/``drop_resource()``'s ``use_arm="core"``
branch, and ``frontend/gantry.js``'s gripper-pad glyphs + carried-plate
reparenting) on its own. See ``thermocycler_demo.py`` for the same ODTC
landing a plate the *ordinary* way (assigned directly at setup, never
picked up/moved), and ``core96_demo.py`` for the other, unrelated
"CO-RE" mechanism (the 96-head) this project also models.

Physically: two of the 8 pipetting channels (``front_channel``, default 7,
and ``back_channel = front_channel - 1``, i.e. 6) grab a pair of gripper
pads normally parked at the deck's own ``core_grippers`` fixture (every
``STARDeck``/``STARLetDeck``'s default -- see hamilton_decks.py), then
straddle the target plate's front/back edges to clamp and carry it --
``lh.move_plate(..., use_arm="core")`` is PyLabRobot's own real API for
this (a thin wrapper over ``move_resource()``'s
``pick_up_resource()``/``drop_resource()`` pair), no visualizer-specific
call needed. The first two moves below pass ``return_core_gripper=False``
so the pads stay clamped onto the same two channels across all three
moves instead of returning to ``core_grippers`` and re-attaching each
time (real hardware behavior for a multi-move sequence like this one --
see ``visualizer_backend.py``'s own ``_core_gripper_channels`` persistent-
attachment tracking, and its ``needs_attach`` event field, which stays
``False`` for the second and third pickups here as a result); only the
final move leaves it at PyLabRobot's own default (``True``), which is what
makes the pad glyphs disappear again at the very end.

Run it with:

    uv run python examples/core_gripper_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), and click
"Start Protocol" when ready. Click "Reset" once a run finishes to watch it
again with a completely fresh scene, the same "start the entire thing
over" pattern every other demo in this repo uses.
"""

from __future__ import annotations

import asyncio

from custom_labware import inheco_odtc_thermocycler
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  Coordinate,
  PLT_CAR_L5AC_A00,
  STARDeck,
  cor_96_wellplate_360uL_Fb,
)
from pylabrobot.thermocycling.chatterbox import ThermocyclerChatterboxBackend

from hamilton_visualizer import VisualizerBackend, VisualizerServer, VisualizerThermocyclerBackend


async def main() -> None:
  server = VisualizerServer()
  await server.start()

  # Wrapped in try/finally so Ctrl-C (or any other early exit) still lets
  # the visualizer server shut down cleanly -- server.stop() tells uvicorn
  # to release its socket instead of leaving it bound, which is what
  # produces a wall of tracebacks on Ctrl-C otherwise (asyncio.run()
  # abruptly cancelling the server's own still-running background task)
  # and also explains "port already in use" on the next run.
  try:
    await _run(server)
  finally:
    print("Shutting down the visualizer server...")
    await server.stop()


async def _run(server: VisualizerServer) -> None:
  # "Start the entire thing over" rebuilds a completely fresh deck/backend/
  # LiquidHandler each pass -- see picogreen_demo.py's own while True: loop
  # docstring for why (a clean slate for PyLabRobot's own resource tree,
  # which matters even more here than usual: this demo's whole point is
  # reparenting a plate around that tree, so a stale one from a previous
  # pass would be exactly the wrong thing to build on).
  while True:
    deck = STARDeck()

    plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
    plate = cor_96_wellplate_360uL_Fb(name="plate_1")
    plate_carrier[0] = plate
    deck.assign_child_resource(plate_carrier, rails=9)

    tc_name = "thermocycler_1"
    inner_tc = ThermocyclerChatterboxBackend(name=f"{tc_name}_chatter", num_zones=1)
    tc_backend = VisualizerThermocyclerBackend(inner_tc, server, resource_name=tc_name)
    tc = inheco_odtc_thermocycler(tc_name, backend=tc_backend)
    # Centered on the deck's own Y depth, same placement thermocycler_demo.py
    # uses (and for the same reason: reachable from either side, not tucked
    # against the front carrier band) -- far enough right (rails=20) to sit
    # clear of the plate carrier above.
    rails = 20
    rail_location = deck.rails_to_location(rails)
    centered_y = (deck.get_size_y() - tc.get_size_y()) / 2
    deck.assign_child_resource(
      tc, location=Coordinate(x=rail_location.x, y=centered_y, z=rail_location.z)
    )

    inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
    backend = VisualizerBackend(inner_backend, server)
    lh = LiquidHandler(backend=backend, deck=deck)
    await tc_backend.setup()
    await lh.setup()  # also broadcasts the scene and turns on tip/volume tracking -- see VisualizerBackend's docstring

    print("Open the visualizer, then click 'Start Protocol' when ready.")
    await backend.wait_for_start()
    print("Started.")

    print("Moving plate from carrier site 0 to carrier site 1 (CoRe gripper)...")
    await lh.move_plate(plate, plate_carrier[1], use_arm="core", return_core_gripper=False)

    # The lid starts *closed* by default (see thermocycler_demo.py's own
    # docstring) -- a real ODTC's lid has to be open before a plate can
    # land on the block at all, the same physical precondition
    # thermocycler_demo.py itself demonstrates (there, by opening it before
    # ever closing it). Left open afterward: nothing here ever closes it
    # again before the plate comes back off two moves later.
    print("Opening the thermocycler's lid to receive the plate...")
    await tc.open_lid()

    print("Moving plate onto the thermocycler (CoRe gripper, pads already attached)...")
    await lh.move_plate(plate, tc, use_arm="core", return_core_gripper=False)

    print("Moving plate back to carrier site 0 (CoRe gripper, returning the pads)...")
    await lh.move_plate(plate, plate_carrier[0], use_arm="core")

    print("CO-RE gripper demo finished.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await lh.stop()
    await tc_backend.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    print("\nStopped.")

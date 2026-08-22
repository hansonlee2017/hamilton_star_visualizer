"""Inheco on-deck thermal cycler (ODTC) demo: place it on a ``STARDeck``,
land a PCR plate on it, close the lid, run a real 3-stage/32-cycle
protocol, then open the lid again.

No liquid handling here -- this demo exists purely to exercise the
thermocycler integration (``examples/custom_labware.py``'s
``inheco_odtc_thermocycler()`` and
``hamilton_visualizer.VisualizerThermocyclerBackend``) on its own. See
``picogreen_demo.py``/``cherry_pick_demo.py`` for the liquid-handling side.

The ODTC is placed exactly 7 Hamilton deck rails wide (see
``inheco_odtc_thermocycler()``'s docstring for why: real dimensions round
to 156.5mm, widened 1mm to 157.5mm = 7 * 22.5mm so it seats flush against
a rail boundary like any other carrier) and centered on the deck's own Y
depth rather than the usual front carrier band, so it's reachable from
either side instead of tucked against the front edge.

Run it with:

    uv run python examples/thermocycler_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), and click
"Start Protocol" when ready. Click "Reset" (once a run finishes) to watch
it again with a completely fresh scene, the same "start the entire thing
over" pattern picogreen_demo.py uses -- deliberately *not* relying on
Replay for that: VisualizerServer caps a replayed gap between two events
at 2 real seconds (``MAX_REPLAY_GAP`` in server.py, so a genuinely long
real-world pause doesn't replay at 1:1 wall-clock speed), but this demo's
own 5-second shimmer-then-open pause (see ``main()``'s
``asyncio.sleep(5.0)``) is longer than that cap -- replaying it would fire
``open_lid()`` while the frontend's fixed 5-second shimmer animation is
still only 2 seconds in, undoing the very pacing fix that made the lid
visibly open *after* cycling rather than during it. A fresh live run has
no such cap.
"""

from __future__ import annotations

import asyncio

# Python adds a script's own directory to sys.path automatically when run
# directly (``python examples/thermocycler_demo.py``), so this sibling
# import just works -- no path hacking needed.
from custom_labware import inheco_odtc_thermocycler
from pylabrobot.resources import (
  Coordinate,
  STARDeck,
  TIP_CAR_480_A00,
  cor_96_wellplate_360uL_Fb,
  hamilton_96_tiprack_300uL_filter,
)
from pylabrobot.thermocycling.chatterbox import ThermocyclerChatterboxBackend
from pylabrobot.thermocycling.standard import Protocol, Stage, Step

from hamilton_visualizer import VisualizerServer, VisualizerThermocyclerBackend
from hamilton_visualizer.scene import build_scene

# A representative real-world protocol: initial denature, then 30 cycles of
# denature/anneal/extend, then a final extension -- exactly the shape a
# tooltip like this one exists to summarize at a glance.
PCR_PROTOCOL = Protocol(
  stages=[
    Stage(steps=[Step(temperature=[95.0], hold_seconds=300)], repeats=1),
    Stage(
      steps=[
        Step(temperature=[95.0], hold_seconds=30),
        Step(temperature=[55.0], hold_seconds=30),
        Step(temperature=[72.0], hold_seconds=60),
      ],
      repeats=30,
    ),
    Stage(steps=[Step(temperature=[72.0], hold_seconds=300)], repeats=1),
  ]
)


async def main() -> None:
  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()

  # "Start the entire thing over" (this module's docstring) rebuilds a
  # completely fresh deck/thermocycler/backend each pass, rather than
  # trying to hand-reset the previous run's lid/plate state in place -- the
  # same reasoning picogreen_demo.py's own while True: loop docstring gives.
  # For the thermocycler specifically this also matters for a reason that
  # demo doesn't have: the lid's open/closed position isn't part of the
  # cached "state" a fresh scene restores (unlike tip/volume state --
  # see resource-state.js), so without a full scene rebuild each pass, a
  # second run would start from wherever the *previous* run's lid was left,
  # not a clean closed default.
  while True:
    deck = STARDeck()

    tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
    tip_carrier[0] = hamilton_96_tiprack_300uL_filter(name="tip_rack_1")
    deck.assign_child_resource(tip_carrier, rails=1)

    tc_name = "thermocycler_1"
    inner_tc = ThermocyclerChatterboxBackend(name=f"{tc_name}_chatter", num_zones=1)
    tc_backend = VisualizerThermocyclerBackend(inner_tc, server, resource_name=tc_name)
    tc = inheco_odtc_thermocycler(tc_name, backend=tc_backend)

    # rails= alone only controls X (and pins Y to the standard front carrier
    # band) -- build the location by hand instead, so Y can be centered on
    # the deck's own depth (per user direction).
    rails = 30
    rail_location = deck.rails_to_location(rails)
    centered_y = (deck.get_size_y() - tc.get_size_y()) / 2
    deck.assign_child_resource(
      tc, location=Coordinate(x=rail_location.x, y=centered_y, z=rail_location.z)
    )

    plate = cor_96_wellplate_360uL_Fb(name="pcr_plate")
    tc.assign_child_resource(plate)

    await tc_backend.setup()
    # num_channels=8 -- matches a real STAR's 8-channel head, even though
    # this demo never uses it (kept for a consistent scene/HUD across every
    # demo in this repo; see picogreen_demo.py for one that actually does).
    await server.set_scene(build_scene(deck), num_channels=8)

    print("Open the visualizer, then click 'Start Protocol' when ready.")
    await server.wait_for_start()
    print("Started.")

    # Unlike a LiquidHandler's channels (each with its own real-paced
    # animation queue -- see cherry_pick_demo.py's docstring), the
    # thermocycler's lid-slide/shimmer animations are plain fire-and-forget
    # tweens with no queue behind them (deliberately -- see main.js's
    # "Thermocycler: lid slide + cycling shimmer" section), so calling these
    # back-to-back with no delay starts them all firing at once instead of
    # playing out in sequence. Since run_protocol() completes instantly
    # against the chatterbox backend (no real cycling time to wait on), the
    # sleeps below are standing in for that queue by hand, matched to
    # main.js's own THERMOCYCLER_LID_MS/THERMOCYCLER_SHIMMER_MS -- without
    # them, open_lid()'s animation starts before the close/shimmer ones have
    # visually finished, which reads as "the lid never opens" (user-reported:
    # it *does* fire, just buried under/before the still-playing shimmer).
    #
    # The lid starts *closed* by default (scene-builder.js's own initial
    # lidMesh position, baked in before any op event ever arrives -- there's
    # no "starts open" scene attribute), with the plate already sitting on
    # the block regardless (child_location parenting isn't tied to lid state
    # in this simplified model). Opening it first, before ever closing it,
    # is what makes the *close* below an animation you can actually see --
    # closing an already-closed lid is a no-op tween (same start and end
    # position) invisible in the browser. Without this, the only lid motion
    # visible in the whole run was the final open, which made the shimmer
    # look like it started *before* any lid movement at all (user-reported).
    print("Opening lid to load plate...")
    await tc.open_lid()
    await asyncio.sleep(0.6)  # THERMOCYCLER_LID_MS

    print("Closing lid...")
    await tc.close_lid()
    await asyncio.sleep(0.6)  # THERMOCYCLER_LID_MS

    print("Running protocol...")
    await tc.run_protocol(PCR_PROTOCOL, block_max_volume=25.0)
    await asyncio.sleep(5.0)  # THERMOCYCLER_SHIMMER_MS

    print("Opening lid...")
    await tc.open_lid()
    await asyncio.sleep(0.6)  # THERMOCYCLER_LID_MS -- let it finish before mark_finished()

    print("Thermocycler demo finished.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await tc_backend.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  asyncio.run(main())

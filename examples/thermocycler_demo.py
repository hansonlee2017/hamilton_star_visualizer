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
"Start Protocol" when ready.
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
  # -- deck layout: a tip carrier (just for visual context) + the ODTC ------
  deck = STARDeck()

  tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
  tip_carrier[0] = hamilton_96_tiprack_300uL_filter(name="tip_rack_1")
  deck.assign_child_resource(tip_carrier, rails=1)

  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()

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

  print("Closing lid...")
  await tc.close_lid()

  print("Running protocol...")
  await tc.run_protocol(PCR_PROTOCOL, block_max_volume=25.0)

  print("Opening lid...")
  await tc.open_lid()

  print("Thermocycler demo finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

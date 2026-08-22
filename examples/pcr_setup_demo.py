"""End-to-end PCR setup demo: fill a 96-well PCR plate with reagent, cap it
with its own lid, run it through a real thermal cycling protocol on the
Inheco ODTC, then put everything back where it started -- all via the
CoRe gripper (``use_arm="core"``).

Six steps (per user direction), each exercising a different part of this
project's own established machinery, combined here for the first time:

  1. **Fill**: 100uL of reagent into every one of the 96 wells, aspirated
     from a 60mL reservoir -- the same 8-channel batched aspirate/dispense
     pattern ``normalization_demo.py``'s own ``transfer_diluent_batch()``
     uses (see that script's own docstring for why sharing tips across
     wells is safe here: every aspirate/dispense moves the exact same
     shared liquid, nothing left behind in the tip between wells).
  2. **Cap**: the lid -- a real, separate ``Lid`` resource parked on its
     own carrier site, not yet attached to the plate -- moves onto the
     plate via ``lh.move_lid(lid, plate, use_arm="core")``. PyLabRobot's
     own ``Liddable``/``Lid`` machinery (see ``pylabrobot.resources.lid``)
     makes the lid a real child of the plate from this point on; nothing
     else in this script has to track that relationship by hand.
  3. **Load**: the ODTC's own door has to be open first (a real
     precondition -- see ``core_gripper_demo.py``'s own comment on this),
     then the capped plate moves onto the block.
  4. **Cycle**: door closes, a real 3-stage/32-cycle protocol runs (the
     same shape ``thermocycler_demo.py`` uses).
  5. **Unload**: door opens again, the plate (still capped) moves back to
     its original carrier site.
  6. **Uncap**: the lid moves back to its own original site, off the
     plate.

CoRe-gripper mechanics (moving a plate, a lid, or both) are covered in
full by ``core_gripper_demo.py``'s own docstring -- not repeated here.
One thing *is* new: in real PyLabRobot, moving a plate that already has a
lid seated on it (steps 3 and 5 above) moves the lid along "for free" --
the lid is a real child of the plate, so its absolute position simply
recomputes once the plate's own location changes, no separate backend
call needed (matches reality: a capped microplate is picked up and
carried by its own edges, with the lid just resting on top via friction,
not gripped separately). This project's own visualizer, though, only
ever animates a resource when it actually receives an "op" event for
it -- there's no mechanism (yet) for "this resource rides along
whenever *that other* resource moves" -- so this script issues one
extra, otherwise-redundant ``move_lid(plate.lid, plate, use_arm="core")``
call right after each of those two plate moves, re-seating the lid back
onto the very same plate it's already (data-model-wise) sitting on. It's
a genuine, valid PyLabRobot call (pick up the currently-seated lid, put
it right back down in the same relative spot) that changes nothing about
the final resource tree -- its only purpose is to give the frontend an
actual event to animate the lid visibly traveling along with the plate,
instead of being left behind, motionless, at the plate's old site.
``return_core_gripper=False`` on every leg of a capped-plate move except
the very last keeps the same two channels attached across both calls,
rather than returning and re-attaching the pads in between for no reason.

Run it with:

    uv run python examples/pcr_setup_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), and click
"Start Protocol" when ready. Click "Reset" once a run finishes to watch
it again with a completely fresh scene, the same "start the entire thing
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
  TIP_CAR_480_A00,
  Trough_CAR_5R60_A00,
  azenta_96_wellplate_200uL_Vb_4titudeframestar,
  cor_96_wellplate_360uL_Fb_lid,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_300uL_filter,
)
from pylabrobot.thermocycling.chatterbox import ThermocyclerChatterboxBackend
from pylabrobot.thermocycling.standard import Protocol, Stage, Step

from hamilton_visualizer import VisualizerBackend, VisualizerServer, VisualizerThermocyclerBackend

REAGENT_VOLUME_UL = 100.0
# 96 wells * 100uL = 9.6mL -- a fixed margin on top, not a tight computed
# minimum (unlike normalization_demo.py's own reservoir, this run's total
# draw never varies), well within a single 60mL trough either way.
RESERVOIR_FILL_UL = 15_000.0

# A representative real-world protocol: initial denature, then 30 cycles of
# denature/anneal/extend, then a final extension -- the same shape
# thermocycler_demo.py's own PCR_PROTOCOL uses.
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
  server = VisualizerServer()
  await server.start()

  # "Start the entire thing over" rebuilds a completely fresh deck/backend/
  # LiquidHandler each pass -- see core_gripper_demo.py's own while True:
  # loop docstring for why (a clean slate for PyLabRobot's own resource
  # tree, which this demo relies on even more than that one: the lid's own
  # parent/child relationship to the plate has to start fresh too).
  while True:
    deck = STARDeck()

    reagent_tip_carrier = TIP_CAR_480_A00(name="reagent_tip_carrier")
    reagent_tip_rack = hamilton_96_tiprack_300uL_filter(name="reagent_tip_rack")
    reagent_tip_carrier[0] = reagent_tip_rack
    deck.assign_child_resource(reagent_tip_carrier, rails=1)

    reagent_carrier = Trough_CAR_5R60_A00(name="reagent_carrier")
    reagent_reservoir = hamilton_1_trough_60mL_Vb(name="reagent_reservoir")
    reagent_carrier[2] = reagent_reservoir
    deck.assign_child_resource(reagent_carrier, rails=7)

    # Site 0: the PCR plate itself. Site 1: the lid's own home -- a real,
    # separate resource, not yet attached to the plate, until step 2 moves
    # it there.
    #
    # A real PCR plate (V-bottom wells, rigid frame for thermal cycling --
    # see azenta_96_wellplate_200uL_Vb_4titudeframestar's own docstring),
    # not the flat-bottom general-purpose plate every other demo in this
    # repo uses -- per user direction. It has no lid of its own in
    # PyLabRobot (`lid=None` unconditionally in its own factory, no
    # `with_lid` param at all, unlike e.g. cor_96_wellplate_360uL_Fb) --
    # cor_96_wellplate_360uL_Fb_lid's own footprint (127.76 x 85.48mm)
    # happens to match this plate's exactly (confirmed live), so it's
    # reused here rather than hand-building a new one from scratch (per
    # user direction: "If not, we can model the lid using
    # cor_96_wellplate_360uL_Fb_Lid"). Its nesting_z_height (7.6mm) was
    # measured against the Corning plate's own 14.2mm height, not this
    # plate's 16.1mm -- an approximation (the lid sits correspondingly a
    # touch higher than a real Azenta-brand lid would), not a claim about
    # the exact real seated depth.
    plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
    pcr_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="pcr_plate")
    lid = cor_96_wellplate_360uL_Fb_lid(name="pcr_plate_lid")
    plate_carrier[0] = pcr_plate
    plate_carrier[1] = lid
    deck.assign_child_resource(plate_carrier, rails=9)

    tc_name = "thermocycler_1"
    inner_tc = ThermocyclerChatterboxBackend(name=f"{tc_name}_chatter", num_zones=1)
    tc_backend = VisualizerThermocyclerBackend(inner_tc, server, resource_name=tc_name)
    tc = inheco_odtc_thermocycler(tc_name, backend=tc_backend)
    # Centered on the deck's own Y depth, same placement core_gripper_demo.py/
    # thermocycler_demo.py both use.
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

    # -- 1. Fill: 100uL reagent into every well, from the reservoir --------
    reagent_reservoir.tracker.set_volume(RESERVOIR_FILL_UL)
    await backend.broadcast_state()  # the reservoir's own fill wasn't part of the initial scene broadcast

    print(f"Filling all 96 wells with {REAGENT_VOLUME_UL:g}uL of reagent...")
    await lh.pick_up_tips(reagent_tip_rack["A1:H1"])
    for col in range(1, 13):
      wells = pcr_plate[f"A{col}:H{col}"]
      vols = [REAGENT_VOLUME_UL] * len(wells)
      await lh.aspirate([reagent_reservoir] * len(wells), vols=vols, spread="wide")
      await lh.dispense(wells, vols=vols)
    await lh.discard_tips()

    # -- 2. Cap: lid moves from its own site onto the plate ----------------
    print("Capping the plate with its lid...")
    await lh.move_lid(lid, pcr_plate, use_arm="core")

    # -- 3. Load: open the ODTC's door, then move the capped plate on ------
    print("Opening the thermocycler's lid to receive the plate...")
    await tc.open_lid()

    print("Moving the capped plate onto the thermocycler...")
    await lh.move_plate(pcr_plate, tc, use_arm="core", return_core_gripper=False)
    # Redundant re-seat, purely so the frontend animates the lid traveling
    # along too -- see this module's own docstring for why.
    await lh.move_lid(pcr_plate.lid, pcr_plate, use_arm="core", return_core_gripper=False)

    # -- 4. Cycle: close the door, run the real protocol --------------------
    print("Closing the thermocycler's lid...")
    await tc.close_lid()

    print("Running the thermal cycling protocol...")
    await tc.run_protocol(PCR_PROTOCOL, block_max_volume=REAGENT_VOLUME_UL)

    # -- 5. Unload: open the door, move the capped plate back ---------------
    print("Opening the thermocycler's lid...")
    await tc.open_lid()

    print("Moving the capped plate back to its carrier site...")
    await lh.move_plate(pcr_plate, plate_carrier[0], use_arm="core", return_core_gripper=False)
    await lh.move_lid(pcr_plate.lid, pcr_plate, use_arm="core", return_core_gripper=False)

    # -- 6. Uncap: lid moves back to its own original site -------------------
    print("Moving the lid back to its own site...")
    await lh.move_lid(pcr_plate.lid, plate_carrier[1], use_arm="core")

    print("PCR setup demo finished.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await lh.stop()
    await tc_backend.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  asyncio.run(main())

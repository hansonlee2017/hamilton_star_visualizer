"""SPRI (solid-phase reversible immobilization) bead cleanup demo: purifies
a PCR plate's worth of sample on an Alpaqua magnetic plate adapter and
elutes 20uL of each well's product into a fresh PCR plate.

Thirteen steps (per user direction), almost entirely via the CO-RE 96 head
(``pick_up_tips96``/``aspirate96``/``dispense96``/``discard_tips96``) --
one liquid-handling call touches every one of the plate's 96 wells at
once, instead of 8-at-a-time -- plus ``use_arm="core"`` plate moves onto
and off of the magnet:

  1. **Bind**: 88uL of SPRI bead suspension mixed into each of the 96
     sample wells. The *one* liquid-handling step in this protocol that
     does *not* use the 96 head: a real Alpaqua/Hamilton-style bead
     reservoir is a narrow ``Trough_CAR``-mounted trough -- only wide
     enough for 8-channel pipetting to reach into, not the 96 head's full
     -plate-width span (see ``reagent_carrier`` below) -- a deliberate
     choice per user direction, since SPRI beads are the one reagent here
     expensive enough that a trough's smaller dead volume is worth 8-
     channel's own extra couple of seconds. ``Mix`` (see
     ``pylabrobot.liquid_handling.standard``) fires on the dispense, so
     the visualizer's own cycling mix animation plays right after the
     beads land (``frontend/gantry.js``'s ``animateChannelOp()``). Fresh
     tips *per column* here, not once for the whole step -- per user
     direction: mixing means the tip actually dips into that column's own
     sample, so reusing it for the next column's own aspirate from the
     shared bead reservoir would carry sample back into the reservoir and
     contaminate every column drawn from it afterward.
  2. 5-minute bind incubation -- ``lh.sleep()``, not ``asyncio.sleep()``,
     see below.
  3. **Load**: the plate moves onto the Alpaqua magnetic rack.
  4. 5-minute magnetic separation incubation.
  5. **Remove supernatant**: fresh tips, aspirate every well's full 198uL
     (110uL original sample + 88uL beads) out, discard the tips with it.
  6. **Wash 1**: 200uL of 80% ethanol in (from a full-plate-footprint
     reservoir this time -- see below), a 30-minute incubation, then
     removed -- the *same* tips the whole way through (add, hold through
     the incubation, then remove), only discarded at the very end. Unlike
     step 5's own removal (which follows a *different* liquid -- the bead
     suspension -- so needs its own fresh tips), this tip never touches
     anything but ethanol and the plate the entire time, so reusing it
     costs nothing in contamination risk and saves a full 96-tip rack per
     wash. Per user direction.
  7. **Wash 2**: step 6, repeated once more.
  8. 1-minute dry incubation (open air, no lid -- this project doesn't
     model an ODTC-style lid for the Alpaqua rack).
  9. **Unload**: the plate moves back off the magnet, to its own original
     carrier site.
  10. **Elute**: 25uL of elution buffer in, with its own ``Mix`` to help
      resuspend the beads.
  11. 2-minute elution incubation, off the magnet.
  12. **Re-load**: back onto the magnet, 2 more minutes, to pull the beads
      back down and clarify the eluate.
  13. **Transfer**: 20uL of clarified eluate (of the 25uL added -- the
      remaining 5uL deliberately left behind, undisturbed, over the bead
      pellet) into a fresh PCR plate.

Two things new to this project, both exercised here for the first time:

**Incubation holds never literally block the demo.** Six separate holds
here span a real 1 to 30 minutes -- ``await asyncio.sleep(seconds)`` would
make this demo take that long to run (or, scaled by this project's own
playback-speed HUD control, still an uncomfortably long real wait for a
*visualizer*). ``attach_sleep(lh)`` (see ``hamilton_visualizer``) monkey
-patches ``lh.sleep(seconds, resource)`` onto this specific ``LiquidHandler``
instance -- it broadcasts a custom "incubate" op event
(``VisualizerBackend.incubate()``) and returns immediately; the frontend
renders one fixed-length cosmetic pulse (``frontend/incubate.js``)
regardless of the real ``seconds`` value, the same "animation timing is
decoupled from backend timing" idea ``ThermocyclerBackend.run_protocol()``'s
own fixed-length cycling shimmer already established for this project's
thermal-cycling demo.

**Two different reagent-container shapes, on purpose.** ``aspirate96``/
``dispense96`` need a container wide enough for the 96 head's full-plate
footprint to reach into everywhere at once -- a real narrow
``Trough_CAR``-mounted trough (``hamilton_1_trough_60mL_Vb``, the shape
``pcr_setup_demo.py``'s own reservoir uses) is real-hardware too narrow
for that, only 8-channel pipettes can reach it. ``nest_1_troughplate_
195000uL_Vb`` is PyLabRobot's real full-SBS-footprint counterpart -- "96
tiny holes, but one container" per its own docstring -- a genuine ``Plate``
(so it sits on a *plate* carrier site, not the trough carrier) that
``aspirate96``/``dispense96`` treat as a single shared container. Ethanol
and elution buffer (cheap -- a troughplate's larger dead volume doesn't
matter, and both need 96-head speed) get this shape; SPRI beads
(expensive -- worth the narrow trough's smaller dead volume, worth the
8-channel-only tradeoff) keep the plain trough.

Run it with:

    uv run python examples/spri_cleanup_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), and click
"Start Protocol" when ready. Click "Reset" once a run finishes to watch it
again with a completely fresh scene, the same "start the entire thing
over" pattern every other demo in this repo uses.
"""

from __future__ import annotations

import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.liquid_handling.standard import Mix
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  STARDeck,
  TIP_CAR_480_A00,
  Trough_CAR_5R60_A00,
  alpaqua_96_plateadapter_magnum_flx,
  azenta_96_wellplate_200uL_Vb_4titudeframestar,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_300uL_filter,
  nest_1_troughplate_195000uL_Vb,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer, attach_sleep

SAMPLE_VOLUME_UL = 110.0  # already in every well, pre-filled before Start
BEAD_VOLUME_UL = 88.0
POST_BEAD_VOLUME_UL = SAMPLE_VOLUME_UL + BEAD_VOLUME_UL  # 198uL -- step 5's own full removal
ETHANOL_VOLUME_UL = 200.0
ELUTION_VOLUME_UL = 25.0
TRANSFER_VOLUME_UL = 20.0  # of the 25uL eluted -- 5uL deliberately left over the bead pellet

# Fixed margins over what the run actually consumes, same reasoning as
# pcr_setup_demo.py's own RESERVOIR_FILL_UL: not a tight computed minimum,
# just comfortably more than 96 wells' worth.
BEAD_RESERVOIR_FILL_UL = 15_000.0  # 96 * 88uL = 8448uL
ETHANOL_RESERVOIR_FILL_UL = 60_000.0  # 96 * 200uL * 2 washes = 38400uL
ELUTION_RESERVOIR_FILL_UL = 5_000.0  # 96 * 25uL = 2400uL

# Real minutes, per the user's own step list -- never actually awaited in
# real time; see this module's own docstring for why (lh.sleep(), not
# asyncio.sleep()).
BIND_INCUBATION_S = 5 * 60
SEPARATION_INCUBATION_S = 5 * 60
WASH_INCUBATION_S = 30 * 60
DRY_INCUBATION_S = 1 * 60
ELUTION_INCUBATION_S = 2 * 60
CLARIFY_INCUBATION_S = 2 * 60

BEAD_MIX = Mix(volume=50.0, repetitions=8, flow_rate=100.0)
ELUTION_MIX = Mix(volume=15.0, repetitions=6, flow_rate=50.0)


async def main() -> None:
  server = VisualizerServer()
  await server.start()

  # "Start the entire thing over" rebuilds a completely fresh deck/backend/
  # LiquidHandler each pass -- see pcr_setup_demo.py's own while True: loop
  # docstring for why.
  while True:
    deck = STARDeck()

    # Six fresh 96-tip racks -- one per liquid-handling step that needs its
    # own fresh tips, per user direction ("fresh tips every step"): step
    # 5's removal, step 10's elution, and step 13's transfer each consume a
    # full 96 spots in one 96-head pickup; step 1's own rack also ends up
    # fully consumed, just 8 channels (one column) at a time, 12 times
    # over -- see that step's own comment below. Each ethanol wash (steps
    # 6-7) gets exactly *one* rack, not two: per user direction, the same
    # tips that add the ethanol are held through the wash incubation and
    # then used to remove it too, since nothing but ethanol and the plate
    # ever touches them (see steps 6/7's own comment above for why that's
    # safe here but not for step 5, which follows a *different* liquid).
    tip_carrier_1 = TIP_CAR_480_A00(name="tip_carrier_1")
    tip_carrier_2 = TIP_CAR_480_A00(name="tip_carrier_2")
    tip_rack_mix = hamilton_96_tiprack_300uL_filter(name="tip_rack_mix")
    tip_rack_remove_supernatant = hamilton_96_tiprack_300uL_filter(name="tip_rack_remove_supernatant")
    tip_rack_etoh1 = hamilton_96_tiprack_300uL_filter(name="tip_rack_etoh1")
    tip_rack_etoh2 = hamilton_96_tiprack_300uL_filter(name="tip_rack_etoh2")
    tip_rack_elution_add = hamilton_96_tiprack_300uL_filter(name="tip_rack_elution_add")
    tip_rack_transfer = hamilton_96_tiprack_300uL_filter(name="tip_rack_transfer")
    tip_carrier_1[0] = tip_rack_mix
    tip_carrier_1[1] = tip_rack_remove_supernatant
    tip_carrier_1[2] = tip_rack_etoh1
    tip_carrier_1[3] = tip_rack_etoh2
    tip_carrier_1[4] = tip_rack_elution_add
    tip_carrier_2[0] = tip_rack_transfer
    deck.assign_child_resource(tip_carrier_1, rails=1)
    deck.assign_child_resource(tip_carrier_2, rails=7)

    # SPRI beads: a narrow, 8-channel-only trough -- see this module's own
    # docstring for why beads specifically get the narrow-trough shape
    # instead of the full-footprint troughplate ethanol/elution use below.
    reagent_carrier = Trough_CAR_5R60_A00(name="reagent_carrier")
    bead_reservoir = hamilton_1_trough_60mL_Vb(name="bead_reservoir")
    reagent_carrier[0] = bead_reservoir
    deck.assign_child_resource(reagent_carrier, rails=13)

    # Site 0: the working PCR plate (sample, then beads, then washed, then
    # eluted). Site 1: the Alpaqua magnetic rack -- deck-mounted upfront,
    # like the thermocycler in pcr_setup_demo.py, so it renders correctly
    # from frame 0 even before any plate ever lands on it (see scene.py's
    # own _inject_child_location() -- its `dz` gives the frontend the same
    # "payload seat height while still empty" hint a ResourceHolder's own
    # child_location does). Site 2: the fresh output plate step 13 elutes
    # into. Sites 3-4: the ethanol/elution troughplates -- see this
    # module's own docstring for why these two specifically are full
    # -footprint Plates, not the narrow trough shape site 0's beads use.
    plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
    pcr_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="pcr_plate")
    alpaqua_rack = alpaqua_96_plateadapter_magnum_flx(name="alpaqua_rack")
    output_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="output_plate")
    ethanol_reservoir = nest_1_troughplate_195000uL_Vb(name="ethanol_reservoir")
    elution_reservoir = nest_1_troughplate_195000uL_Vb(name="elution_reservoir")
    plate_carrier[0] = pcr_plate
    plate_carrier[1] = alpaqua_rack
    plate_carrier[2] = output_plate
    plate_carrier[3] = ethanol_reservoir
    plate_carrier[4] = elution_reservoir
    deck.assign_child_resource(plate_carrier, rails=15)

    inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
    backend = VisualizerBackend(inner_backend, server)
    lh = LiquidHandler(backend=backend, deck=deck)
    attach_sleep(lh)  # lh.sleep(seconds, resource) -- see this module's own docstring
    await lh.setup()  # also broadcasts the scene and turns on tip/volume tracking -- see VisualizerBackend's docstring

    # Every sample well pre-filled, plus every reservoir -- backend.
    # wait_for_start() (not server.wait_for_start()) re-syncs state so all
    # of this is visible from the very first frame, same reasoning as
    # core96_demo.py's own pre-fill comment.
    for well in pcr_plate.get_all_items():
      well.set_volume(SAMPLE_VOLUME_UL)
    bead_reservoir.tracker.set_volume(BEAD_RESERVOIR_FILL_UL)
    ethanol_reservoir.get_item(0).tracker.set_volume(ETHANOL_RESERVOIR_FILL_UL)
    elution_reservoir.get_item(0).tracker.set_volume(ELUTION_RESERVOIR_FILL_UL)

    print("Open the visualizer, then click 'Start Protocol' when ready.")
    await backend.wait_for_start()
    print("Started.")

    # -- 1. Bind: 88uL SPRI beads mixed into every well, 8-channel -------
    # Fresh tips *per column*, not once for the whole step, unlike
    # pcr_setup_demo.py's own fill loop (which this was originally
    # modeled on): that loop's tips only ever touch the *same* shared
    # reagent, safe to reuse across columns, but Mix here means the tip
    # actually dips into each well's own sample during the mix cycles --
    # reusing it for the *next* column's own aspirate from the shared
    # bead reservoir would carry that column's sample back into the
    # reservoir, contaminating every column drawn from it afterward. Per
    # user direction. Consumes tip_rack_mix's full 96 spots (12 columns *
    # 8 channels), not just the 8 an earlier draft used.
    print(f"Mixing {BEAD_VOLUME_UL:g}uL of SPRI beads into every well...")
    for col in range(1, 13):
      wells = pcr_plate[f"A{col}:H{col}"]
      vols = [BEAD_VOLUME_UL] * len(wells)
      await lh.pick_up_tips(tip_rack_mix[f"A{col}:H{col}"])
      await lh.aspirate([bead_reservoir] * len(wells), vols=vols, spread="wide")
      await lh.dispense(wells, vols=vols, mix=[BEAD_MIX] * len(wells))
      await lh.discard_tips()

    print(f"Binding incubation ({BIND_INCUBATION_S // 60} min)...")
    await lh.sleep(BIND_INCUBATION_S, pcr_plate)

    # -- 2. Load onto the magnet, separate --------------------------------
    print("Moving the plate onto the magnetic rack...")
    await lh.move_plate(pcr_plate, alpaqua_rack, use_arm="core")

    print(f"Magnetic separation incubation ({SEPARATION_INCUBATION_S // 60} min)...")
    await lh.sleep(SEPARATION_INCUBATION_S, pcr_plate)

    # -- 3. Remove supernatant ---------------------------------------------
    print(f"Removing {POST_BEAD_VOLUME_UL:g}uL of supernatant from every well...")
    await lh.pick_up_tips96(tip_rack_remove_supernatant)
    await lh.aspirate96(pcr_plate, volume=POST_BEAD_VOLUME_UL)
    await lh.discard_tips96()

    # -- 4/5. Two ethanol washes --------------------------------------------
    # One tip rack per wash, not two: the same tips add the ethanol, sit
    # attached to the 96 head through the incubation (no discard in
    # between), then remove it -- see this module's own docstring and the
    # deck-setup comment above for why that's safe here (nothing but
    # ethanol and the plate ever touches them) but not for step 5's own
    # supernatant removal, which follows the bead suspension instead. Per
    # user direction.
    etoh_racks = [tip_rack_etoh1, tip_rack_etoh2]
    for wash_num in (1, 2):
      print(f"Wash {wash_num}: adding {ETHANOL_VOLUME_UL:g}uL of 80% ethanol to every well...")
      await lh.pick_up_tips96(etoh_racks[wash_num - 1])
      await lh.aspirate96(ethanol_reservoir, volume=ETHANOL_VOLUME_UL)
      await lh.dispense96(pcr_plate, volume=ETHANOL_VOLUME_UL)

      print(f"Wash {wash_num} incubation ({WASH_INCUBATION_S // 60} min)...")
      await lh.sleep(WASH_INCUBATION_S, pcr_plate)

      print(f"Wash {wash_num}: removing the ethanol from every well...")
      await lh.aspirate96(pcr_plate, volume=ETHANOL_VOLUME_UL)
      await lh.discard_tips96()

    print(f"Dry incubation ({DRY_INCUBATION_S // 60} min)...")
    await lh.sleep(DRY_INCUBATION_S, pcr_plate)

    # -- 6. Unload from the magnet ------------------------------------------
    print("Moving the plate back to its own carrier site...")
    await lh.move_plate(pcr_plate, plate_carrier[0], use_arm="core")

    # -- 7. Elute -------------------------------------------------------------
    print(f"Adding {ELUTION_VOLUME_UL:g}uL of elution buffer to every well...")
    await lh.pick_up_tips96(tip_rack_elution_add)
    await lh.aspirate96(elution_reservoir, volume=ELUTION_VOLUME_UL)
    await lh.dispense96(pcr_plate, volume=ELUTION_VOLUME_UL, mix=ELUTION_MIX)
    await lh.discard_tips96()

    print(f"Elution incubation ({ELUTION_INCUBATION_S // 60} min)...")
    await lh.sleep(ELUTION_INCUBATION_S, pcr_plate)

    print("Moving the plate back onto the magnetic rack to clarify the eluate...")
    await lh.move_plate(pcr_plate, alpaqua_rack, use_arm="core")

    print(f"Clarifying incubation ({CLARIFY_INCUBATION_S // 60} min)...")
    await lh.sleep(CLARIFY_INCUBATION_S, pcr_plate)

    # -- 8. Transfer the clarified eluate into a fresh plate -----------------
    print(f"Transferring {TRANSFER_VOLUME_UL:g}uL of eluate into the output plate...")
    await lh.pick_up_tips96(tip_rack_transfer)
    await lh.aspirate96(pcr_plate, volume=TRANSFER_VOLUME_UL)
    await lh.dispense96(output_plate, volume=TRANSFER_VOLUME_UL)
    await lh.discard_tips96()

    print("SPRI cleanup demo finished.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await lh.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  asyncio.run(main())

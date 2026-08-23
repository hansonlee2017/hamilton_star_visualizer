"""KAPA HyperPlus library prep demo: Roche's KAPA HyperPlus Kit Instructions
for Use (v12.0, August 2025), Chapters 3 & 4, automated on a Hamilton STAR
with an Inheco ODTC (thermal cycling) and an Alpaqua magnetic plate adapter
(SPRI bead cleanups) -- the same two devices ``pcr_setup_demo.py`` and
``spri_cleanup_demo.py`` each exercise separately, combined here into one
real, published wet-lab protocol for the first time.

Design choices made when the source IFU offers options (all confirmed with
the user before writing this file):
  - **KAPA UDI Adapters** (not KAPA Universal Adapter + KAPA UDI Primer
    Mixes) -- full-length, pre-indexed adapters, one already-unique
    reagent per well straight out of ligation, and a single shared
    Library Amplification Primer Mix for every sample during amplification.
  - **Library Amplification included** (Chapter 4 in full), not stopped
    after the PCR-free post-ligation cleanup.
  - **100 ng DNA input, ~350 bp fragmentation target**: 10 min at 37degC
    (Chapter 3, Step 1's own table) and, per Table 4, 2 of the 0-2 cycles
    the table allows to reach a 100 ng amplified library at this input
    (enough to actually exercise the cycling stage in
    ``AMPLIFICATION_PROTOCOL`` below).
  - **No double-sided size selection, no EDTA/Conditioning Solution
    handling** -- the plain Chapter 3/4 workflow only, input DNA assumed
    already in 10 mM Tris-HCl, pH 8.0-8.5.

Three corrections from an earlier draft of this file, all now load-bearing
in the design below:

  1. **Reagent premixes live in real Eppendorf tubes, not troughs.** The
     IFU's own four "combine and dispense in one pipetting step" premixes
     (Frag Buffer+Enzyme, End Repair & A-Tailing Buffer+Enzyme Mix,
     Ligation Buffer+DNA Ligase+water, KAPA HiFi HotStart ReadyMix+Library
     Amplification Primer Mix) are each a single Eppendorf tube, sized to
     what a 96-well run actually consumes: End Repair & A-Tailing Mix
     (960uL needed) fits comfortably in a 1.5mL tube
     (``eppendorf_tube_1500uL_Vb``, on
     ``hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL`` -- the same
     tube/carrier pair ``picogreen_demo.py`` already established in this
     repo); Frag Mix (1,440uL), Ligation Mix (4,320uL) and PCR Mix
     (2,880uL) all need a 5mL snap-cap tube instead
     (``eppendorf_tube_5mL_Vb_snapcap``, on a ``Tube_CAR_24_A00`` -- its
     14.5-18mm insert diameter fits the 5mL tube's own 16.7mm, unlike the
     32-site carrier's 10.8mm holes, which are sized for the 1.5mL tube
     only). Ligation Mix's own fill (4,700uL of a 5,000uL tube) is
     genuinely tight -- not a modeling shortcut: the kit's own 96-reaction
     component volumes (3.8mL Ligation Buffer + 1.26mL DNA Ligase, before
     the user's own water) already total just over 5mL, so a real
     automated run at this scale is right at a single 5mL Eppendorf's own
     limit.

     A real Eppendorf tube's ~10mm opening only fits one pipette tip at a
     time -- unlike the wide troughs used elsewhere in this file for
     bulk reagents (SPRI beads, ethanol, elution buffer), a shared tube
     can't take PyLabRobot's own multi-channel ``spread="wide"``
     aspirate. ``add_premix_from_tube()`` below instead has each of a
     column's (up to 8) channels aspirate from the tube one at a time in
     sequence, then dispenses all of them into their own column
     simultaneously -- the exact pattern ``picogreen_demo.py``'s own
     DNA-stock/TE-diluent tube draws already established in this repo.

  2. **The ODTC needs a real lid seated on the plate to run.** Every visit
     to the ODTC is now a full cap -> load -> cycle -> unload -> uncap
     sequence -- the same six-step shape ``pcr_setup_demo.py`` established
     for its own single visit (``cor_96_wellplate_360uL_Fb_lid``, moved via
     ``lh.move_lid()`` -- see that module's own docstring for the
     mechanics), just repeated by ``run_thermal_step()`` below for every
     one of this protocol's four thermal steps (fragmentation, End
     Repair/A-Tailing and ligation for ``working_plate``; amplification for
     ``amp_plate``). Each plate keeps its own dedicated lid, capped fresh
     before every visit and parked at its own site the rest of the time --
     never left seated on an idle plate. The ODTC's own door is explicitly
     closed again at the end of every visit (not left open between visits,
     unlike an earlier draft of this file), so it's back in a safe, idle
     default state and the *next* visit's own "open to receive" is a real,
     visible animation rather than a no-op on an already-open door.

  3. **No liquid handling happens with a plate sitting on the ODTC --
     except Enzymatic Fragmentation.** ``working_plate`` and ``amp_plate``
     each live at their own dedicated plate-carrier site the entire time
     reagents are being added for every *other* thermal step -- the ODTC is
     purely a destination a capped plate visits for cycling and then
     leaves, exactly like ``pcr_setup_demo.py``'s own single visit. The
     IFU calls out Enzymatic Fragmentation specifically as needing to be
     "assembled on ice" (Chapter 3, Step 1); per user direction, the ODTC's
     own pre-cooled block (``tc.set_block_temperature([4.0])``, run before
     the plate ever lands on it -- Chapter 3, Step 1's own "Pre-cool block:
     +4degC") substitutes for a benchtop ice bucket, so for this one step
     only, the bare uncapped plate loads onto the ODTC *first*, Frag Mix
     goes in while it sits there, and the lid goes on only afterward,
     immediately before cycling -- see the inline comment at that step in
     ``main()`` for the full sequence. Every other thermal step (End
     Repair/A-Tailing and Ligation for ``working_plate``; amplification for
     ``amp_plate``) keeps the original cap-then-load shape ``run_thermal_
     step()`` implements.

A fourth refinement, not a correction: **50uL tips for every transfer/mix
that never exceeds 50uL** (``hamilton_96_tiprack_50uL_filter``), 300uL
tips reserved for the larger-volume SPRI/ethanol steps that do -- the same
"smallest tip that comfortably holds the volume" idea
``picogreen_demo.py``'s own ``tier_for_volume()`` applies. Concretely:
every reagent-premix addition, the KAPA UDI Adapter transfer, both
elution-buffer additions, and the 50uL post-amplification bead addition
all get 50uL tips; the 88uL post-ligation bead addition, both supernatant
removals (198uL/100uL) and all four 200uL ethanol-wash steps keep 300uL
tips. Neither cleanup's own eluate transfer gets its own tip rack at all
any more -- see the next paragraph.

Both SPRI cleanups (post-ligation and post-amplification) are the same
13-step shape ``spri_cleanup_demo.py`` already established in full detail
(bind -> load -> separate -> remove supernatant -> 2x ethanol wash -> dry
-> unload -> elute -> incubate -> reload -> clarify -> transfer) -- see
that module's own docstring for the reasoning behind fresh-tips-per-step,
the narrow-trough-vs-troughplate reagent split (still used for SPRI beads/
ethanol/elution buffer -- bulk reagents, unaffected by the Eppendorf-tube
correction above, which only applies to the four low-volume enzyme
premixes), and ``lh.sleep()`` instead of ``asyncio.sleep()``. Reused here
verbatim except for volumes (0.8X/88uL beads post-ligation per the IFU's
110uL ligation product, 1.0X/50uL beads post-amplification per its 50uL
amplified library) and incubation times, which follow this kit's own
numbers exactly -- most notably the ethanol wash hold: the IFU specifies
"~=30 seconds", used here literally, not the 30-*minute* hold the original
SPRI demo used for a more generic/conservative protocol. Each cleanup's own
``home_site`` (where the plate sits between magnet visits) is simply that
plate's own dedicated carrier site -- no ODTC involvement at all, since
neither cleanup does any thermal cycling.

Two more corrections, both per user direction:

  - **The Alpaqua rack only ever holds one plate at a time.** An earlier
    draft left ``working_plate`` parked on the magnet after the
    post-ligation cleanup's own eluate transfer -- harmless on its own, but
    ``amp_plate`` then had nowhere to land for the post-amplification
    cleanup's own magnet visits, since the rack was still occupied.
    ``working_plate`` now explicitly moves back to its own site
    (``plate_carrier_1[0]``) immediately after that transfer, freeing the
    rack before Chapter 4 ever needs it.

  - **Elution-buffer tips are reused for the eluate transfer, not
    discarded and repicked.** ``run_spri_cleanup()``'s own elution-add
    tips only ever touch elution buffer (a clean shared reservoir) and
    then that specific plate's own wells -- the exact liquid lineage the
    later clarified-eluate aspirate draws from -- so they're held through
    both incubations and the magnet reload instead of being discarded,
    the same "add, hold, reuse" idea ``spri_cleanup_demo.py``'s own
    ethanol-wash tips already rely on. There's no separate "transfer" tip
    rack in this file any more as a result.

Run it with:

    uv run python examples/kapa_hyperplus_demo.py

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
from pylabrobot.liquid_handling.standard import Mix
from pylabrobot.resources import (
  Coordinate,
  PLT_CAR_L5AC_A00,
  STARDeck,
  TIP_CAR_480_A00,
  Trough_CAR_5R60_A00,
  Tube_CAR_24_A00,
  alpaqua_96_plateadapter_magnum_flx,
  azenta_96_wellplate_200uL_Vb_4titudeframestar,
  cor_96_wellplate_360uL_Fb_lid,
  eppendorf_tube_1500uL_Vb,
  eppendorf_tube_5mL_Vb_snapcap,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_50uL_filter,
  hamilton_96_tiprack_300uL_filter,
  hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL,
  nest_1_troughplate_195000uL_Vb,
)
from pylabrobot.thermocycling.chatterbox import ThermocyclerChatterboxBackend
from pylabrobot.thermocycling.standard import Protocol, Stage, Step

from hamilton_visualizer import VisualizerBackend, VisualizerServer, VisualizerThermocyclerBackend, attach_sleep

# -- Chapter 3: Prepare the Sample Library -- reaction volumes ---------------
# Every "*_MIX_UL" below is a premix of the two-or-more components the IFU
# itself says to combine and dispense in one pipetting step (see this
# module's own docstring). Running totals track the IFU's own per-step
# table exactly (e.g. 35uL DNA + 5uL Frag Buffer + 10uL Frag Enzyme = 50uL).
DNA_INPUT_UL = 35.0  # diluted dsDNA sample, already in the working plate pre-Start (Figure 1)
FRAG_MIX_UL = 15.0  # 5uL KAPA Frag Buffer (10X) + 10uL KAPA Frag Enzyme
POST_FRAG_UL = DNA_INPUT_UL + FRAG_MIX_UL  # 50uL

ERAT_MIX_UL = 10.0  # 7uL End Repair & A-Tailing Buffer + 3uL End Repair & A-Tailing Enzyme Mix
POST_ERAT_UL = POST_FRAG_UL + ERAT_MIX_UL  # 60uL

ADAPTER_UL = 5.0  # KAPA UDI Adapter, 1:1 well-matched transfer from the adapter plate
LIGATION_MIX_UL = 45.0  # 5uL PCR-grade water + 30uL Ligation Buffer + 10uL DNA Ligase
POST_LIGATION_UL = POST_ERAT_UL + ADAPTER_UL + LIGATION_MIX_UL  # 110uL

# -- Chapter 3, Step 4: post-ligation SPRI cleanup (KAPA HyperPure Beads) ----
# 0.8X bead ratio on the 110uL ligation product -- same shape as
# spri_cleanup_demo.py's own single cleanup, reused twice in this file (see
# run_spri_cleanup() below) with each call's own volumes.
BEAD_RATIO_POST_LIGATION_UL = 88.0
POST_LIGATION_BEAD_TOTAL_UL = POST_LIGATION_UL + BEAD_RATIO_POST_LIGATION_UL  # 198uL
POST_LIGATION_ELUTION_UL = 25.0
POST_LIGATION_TRANSFER_UL = 20.0  # of the 25uL eluted; 5uL deliberately left over the bead pellet

# -- Chapter 4: Amplify the Sample Library -----------------------------------
PCR_MIX_UL = 30.0  # 25uL KAPA HiFi HotStart ReadyMix (2X) + 5uL Library Amplification Primer Mix (10X)
POST_PCR_MIX_UL = POST_LIGATION_TRANSFER_UL + PCR_MIX_UL  # 50uL

# -- Chapter 4, Step 3a: post-amplification SPRI cleanup ---------------------
# 1.0X bead ratio on the 50uL amplified library.
BEAD_RATIO_POST_AMP_UL = 50.0
POST_AMP_BEAD_TOTAL_UL = POST_PCR_MIX_UL + BEAD_RATIO_POST_AMP_UL  # 100uL
POST_AMP_ELUTION_UL = 25.0
POST_AMP_TRANSFER_UL = 20.0  # final, sequencing-ready library

ETHANOL_VOLUME_UL = 200.0  # per wash, both cleanups -- IFU Chapter 3 Step 4 / Chapter 4 Step 3a

# -- Reagent-tube fills -- see this module's own docstring for why each
# premix gets the tube size it does (1.5mL vs 5mL), and why Ligation Mix's
# own fill is deliberately tight against its tube's 5,000uL cap.
FRAG_MIX_TUBE_FILL_UL = 2_000.0  # 5mL tube; 96 * 15uL = 1,440uL needed
ERAT_MIX_TUBE_FILL_UL = 1_200.0  # 1.5mL tube; 96 * 10uL = 960uL needed
LIGATION_MIX_TUBE_FILL_UL = 4_700.0  # 5mL tube; 96 * 45uL = 4,320uL needed -- see docstring
PCR_MIX_TUBE_FILL_UL = 3_200.0  # 5mL tube; 96 * 30uL = 2,880uL needed

# Fixed margins over what the run actually consumes -- same reasoning as
# pcr_setup_demo.py's own RESERVOIR_FILL_UL, not a tight computed minimum.
# Shared across both cleanups: 96 * (88 + 50)uL = 13,248uL total draw.
BEAD_RESERVOIR_FILL_UL = 18_000.0
# Shared across both cleanups' 2 washes each: 96 * 200uL * 4 = 76,800uL total draw.
ETHANOL_RESERVOIR_FILL_UL = 90_000.0
# Shared across both cleanups' single elution each: 96 * 25uL * 2 = 4,800uL total draw.
ELUTION_RESERVOIR_FILL_UL = 6_000.0
ADAPTER_PLATE_FILL_UL = 20.0  # per well -- matches the real KAPA UDI Adapter Kit's own 96 x 20uL

# Real minutes/seconds, per the IFU's own step-by-step tables -- never
# actually awaited in real time; see this module's own docstring and
# spri_cleanup_demo.py's for why (lh.sleep(), not asyncio.sleep()).
BIND_INCUBATION_S = 5 * 60  # Chapter 3/4 cleanup Step 3: "Incubate... for 5 minutes"
SEPARATION_INCUBATION_S = 5 * 60  # "Incubate until the liquid is clear" -- not separately timed in the IFU
WASH_INCUBATION_S = 30  # "Incubate... for >=30 seconds" -- literal, both cleanups
DRY_INCUBATION_S = 3 * 60  # "sufficiently for all the ethanol to evaporate" -- not separately timed
ELUTION_INCUBATION_S = 2 * 60  # "Incubate... for 2 minutes to allow the sample library to elute"
CLARIFY_INCUBATION_S = 2 * 60  # re-magnet incubation before the eluate transfer, matches elution's own hold

# -- Thermal protocols, one per Chapter 3/4 step run on the ODTC ------------
# Timing here is entirely cosmetic (see VisualizerThermocyclerBackend's own
# docstring: run_protocol() completes instantly, the frontend plays a fixed
# 5-second shimmer regardless), so every value below is the IFU's own real
# number, not a demo-friendly approximation.
FRAGMENTATION_PROTOCOL = Protocol(
  stages=[Stage(steps=[Step(temperature=[37.0], hold_seconds=600)], repeats=1)]
)  # 10 min at 37degC -> ~350bp mode fragment length, for 100ng input (Chapter 3, Step 1's own table)

ERAT_PROTOCOL = Protocol(
  stages=[Stage(steps=[Step(temperature=[65.0], hold_seconds=1800)], repeats=1)]
)  # 30 min at 65degC (Chapter 3, Step 2's own table)

LIGATION_PROTOCOL = Protocol(
  stages=[Stage(steps=[Step(temperature=[20.0], hold_seconds=900)], repeats=1)]
)  # 15 min at 20degC -- the IFU calls for this "on a thermocycler" explicitly (Chapter 3, Step 3)

AMPLIFICATION_PROTOCOL = Protocol(
  stages=[
    Stage(steps=[Step(temperature=[98.0], hold_seconds=45)], repeats=1),
    Stage(
      steps=[
        Step(temperature=[98.0], hold_seconds=15),
        Step(temperature=[60.0], hold_seconds=30),
        Step(temperature=[72.0], hold_seconds=30),
      ],
      repeats=2,  # Table 4: 0-2 cycles for a 100ng amplified library from 100ng input; 2 used (see docstring)
    ),
    Stage(steps=[Step(temperature=[72.0], hold_seconds=60)], repeats=1),
  ]
)  # Chapter 4, Step 2's own table

# In-tip mix cycles, one per reagent addition that the IFU calls "mix
# thoroughly" -- sized well under each step's own post-addition well volume
# (see the "POST_*_UL" constants above) and under the 50uL tips' own real
# ~60uL capacity (confirmed live), same idea as spri_cleanup_demo.py's own
# BEAD_MIX/ELUTION_MIX.
FRAG_MIX_MIX = Mix(volume=25.0, repetitions=5, flow_rate=75.0)  # well at 50uL after
ERAT_MIX_MIX = Mix(volume=30.0, repetitions=5, flow_rate=75.0)  # well at 60uL after
LIGATION_MIX_MIX = Mix(volume=50.0, repetitions=6, flow_rate=75.0)  # well at 110uL after
PCR_MIX_MIX = Mix(volume=25.0, repetitions=5, flow_rate=75.0)  # well at 50uL after
BEAD_MIX_POST_LIGATION = Mix(volume=50.0, repetitions=8, flow_rate=100.0)  # well at 198uL after; 88uL transfer -> 300uL tips
BEAD_MIX_POST_AMP = Mix(volume=40.0, repetitions=8, flow_rate=100.0)  # well at 100uL after; 50uL transfer -> 50uL tips
ELUTION_MIX = Mix(volume=15.0, repetitions=6, flow_rate=50.0)  # both cleanups, well at 25uL after


async def add_premix_from_tube(
  lh: LiquidHandler,
  *,
  plate,
  tube,
  tip_rack,
  volume_ul: float,
  mix: Mix,
) -> None:
  """Adds ``volume_ul`` of a single shared Eppendorf tube's contents into
  every well of ``plate``, one column (8 channels) at a time. A real
  Eppendorf tube's ~10mm opening only fits one pipette tip at a time --
  unlike the wide troughs elsewhere in this file (SPRI beads, ethanol,
  elution buffer), a tube can't take PyLabRobot's own multi-channel
  ``spread="wide"`` aspirate. So each of a column's (up to 8) channels
  aspirates from the tube one at a time in sequence -- the others simply
  wait, tips still attached -- then a single ``dispense()`` call sends
  every channel to its own well simultaneously. The exact pattern
  ``picogreen_demo.py``'s own DNA-stock/TE-diluent tube draws already
  established in this repo.

  Fresh tips *per column*, not once for the whole addition: the IFU calls
  every one of these additions "mix thoroughly", so each tip dips into
  that column's own sample during ``mix``'s in-tip cycles -- reusing it
  for the next column's own aspirate from the shared tube would carry
  sample back into it (same reasoning spri_cleanup_demo.py's own bind step
  gives for its narrow-trough beads).
  """
  for col in range(1, 13):
    wells = plate[f"A{col}:H{col}"]
    n = len(wells)
    channels = list(range(n))
    await lh.pick_up_tips(tip_rack[f"A{col}:H{col}"])
    for channel in channels:
      await lh.aspirate([tube], vols=[volume_ul], use_channels=[channel])
    await lh.dispense(wells, vols=[volume_ul] * n, mix=[mix] * n, use_channels=channels)
    await lh.discard_tips()


async def run_thermal_step(
  lh: LiquidHandler,
  tc,
  *,
  plate,
  plate_home_site,
  lid,
  lid_home_site,
  protocol: Protocol,
  block_max_volume: float,
  label: str,
) -> None:
  """One full visit to the ODTC -- cap, load, cycle, unload, uncap -- the
  same six-step shape ``pcr_setup_demo.py`` established for its own single
  visit (see this module's own docstring for why every visit needs this
  now, not just one). The plate never receives any reagent while sitting
  on the ODTC; every addition happens before this function is called, back
  at ``plate_home_site``.

  The ODTC's own door is explicitly closed again once the plate is back at
  its own site (not left open between visits) -- a safe, idle default
  state, and it means the *next* call's own "open to receive" is a real,
  visible animation rather than a no-op on an already-open door. Since
  that close happens *after* the unload (not immediately before the next
  cap), the unload's own ``move_plate`` doesn't get
  ``return_core_gripper=False`` the way ``pcr_setup_demo.py``'s single-visit
  unload does -- the immediately-following op here is the door close, not
  another CoRe-gripper move, so there'd be nothing to save.
  """
  print(f"Capping {plate.name} with its lid...")
  await lh.move_lid(lid, plate, use_arm="core", return_core_gripper=False)

  print("Opening the ODTC's lid to receive the plate...")
  await tc.open_lid()

  print(f"Moving {plate.name} onto the ODTC...")
  await lh.move_plate(plate, tc, use_arm="core")

  print("Closing the ODTC's lid...")
  await tc.close_lid()

  print(f"Running the {label} protocol...")
  await tc.run_protocol(protocol, block_max_volume=block_max_volume)

  print("Opening the ODTC's lid...")
  await tc.open_lid()

  print(f"Moving {plate.name} back to its own carrier site...")
  await lh.move_plate(plate, plate_home_site, use_arm="core")

  print("Closing the ODTC's lid...")
  await tc.close_lid()

  print(f"Uncapping {plate.name}...")
  await lh.move_lid(plate.lid, lid_home_site, use_arm="core")


async def run_spri_cleanup(
  lh: LiquidHandler,
  *,
  plate,
  home_site,
  alpaqua_rack,
  bead_reservoir,
  ethanol_reservoir,
  elution_reservoir,
  bead_volume_ul: float,
  bead_mix: Mix,
  bead_tip_rack,
  post_bead_volume_ul: float,
  elution_volume_ul: float,
  transfer_volume_ul: float,
  output_plate,
  tip_rack_remove_supernatant,
  tip_racks_etoh: list,
  tip_rack_elution_add,
) -> None:
  """One full KAPA HyperPure Beads SPRI cleanup, the same 13-step shape
  ``spri_cleanup_demo.py`` established (see this module's own docstring) --
  factored out here since this protocol runs it twice (post-ligation and
  post-amplification) with different volumes/tip racks/reservoirs each
  time. ``home_site`` is ``plate``'s own dedicated carrier site -- neither
  cleanup ever visits the ODTC, since neither does any thermal cycling
  (see this module's own docstring, correction 3).

  The elution-buffer tips are never discarded after adding it -- they're
  held through the elution incubation and the move back onto the magnet,
  then reused directly to aspirate the clarified eluate for the final
  transfer (per user direction). Same reasoning ``spri_cleanup_demo.py``'s
  own ethanol-wash tips already rely on: these tips only ever touch
  elution buffer (from a clean shared reservoir) and then this specific
  plate's own wells -- the very same liquid lineage the later aspirate
  draws from -- so a fresh pickup for that aspirate would discard perfectly
  good tips for no contamination benefit. There is no longer a separate
  "transfer" tip rack at all.
  """

  # -- Bind: beads mixed directly into every well, 8-channel, per column ----
  print(f"Mixing {bead_volume_ul:g}uL of SPRI beads into every well...")
  for col in range(1, 13):
    wells = plate[f"A{col}:H{col}"]
    vols = [bead_volume_ul] * len(wells)
    await lh.pick_up_tips(bead_tip_rack[f"A{col}:H{col}"])
    await lh.aspirate([bead_reservoir] * len(wells), vols=vols, spread="wide")
    await lh.dispense(wells, vols=vols, mix=[bead_mix] * len(wells))
    await lh.discard_tips()

  print(f"Binding incubation ({BIND_INCUBATION_S // 60} min)...")
  await lh.sleep(BIND_INCUBATION_S, plate)

  print("Moving the plate onto the magnetic rack...")
  await lh.move_plate(plate, alpaqua_rack, use_arm="core")

  print(f"Magnetic separation incubation ({SEPARATION_INCUBATION_S // 60} min)...")
  await lh.sleep(SEPARATION_INCUBATION_S, plate)

  print(f"Removing {post_bead_volume_ul:g}uL of supernatant from every well...")
  await lh.pick_up_tips96(tip_rack_remove_supernatant)
  await lh.aspirate96(plate, volume=post_bead_volume_ul)
  await lh.discard_tips96()

  for wash_num, tip_rack_etoh in enumerate(tip_racks_etoh, start=1):
    print(f"Wash {wash_num}: adding {ETHANOL_VOLUME_UL:g}uL of 80% ethanol to every well...")
    await lh.pick_up_tips96(tip_rack_etoh)
    await lh.aspirate96(ethanol_reservoir, volume=ETHANOL_VOLUME_UL)
    await lh.dispense96(plate, volume=ETHANOL_VOLUME_UL)

    print(f"Wash {wash_num} incubation ({WASH_INCUBATION_S} sec)...")
    await lh.sleep(WASH_INCUBATION_S, plate)

    print(f"Wash {wash_num}: removing the ethanol from every well...")
    await lh.aspirate96(plate, volume=ETHANOL_VOLUME_UL)
    await lh.discard_tips96()

  print(f"Dry incubation ({DRY_INCUBATION_S // 60} min)...")
  await lh.sleep(DRY_INCUBATION_S, plate)

  print("Moving the plate back to its own home site...")
  await lh.move_plate(plate, home_site, use_arm="core")

  print(f"Adding {elution_volume_ul:g}uL of elution buffer to every well...")
  await lh.pick_up_tips96(tip_rack_elution_add)
  await lh.aspirate96(elution_reservoir, volume=elution_volume_ul)
  await lh.dispense96(plate, volume=elution_volume_ul, mix=ELUTION_MIX)
  # Tips deliberately NOT discarded here -- held through both incubations
  # below and reused to aspirate the clarified eluate directly (see this
  # function's own docstring).

  print(f"Elution incubation ({ELUTION_INCUBATION_S // 60} min)...")
  await lh.sleep(ELUTION_INCUBATION_S, plate)

  print("Moving the plate back onto the magnetic rack to clarify the eluate...")
  await lh.move_plate(plate, alpaqua_rack, use_arm="core")

  print(f"Clarifying incubation ({CLARIFY_INCUBATION_S // 60} min)...")
  await lh.sleep(CLARIFY_INCUBATION_S, plate)

  print(f"Transferring {transfer_volume_ul:g}uL of eluate into the next plate...")
  await lh.aspirate96(plate, volume=transfer_volume_ul)
  await lh.dispense96(output_plate, volume=transfer_volume_ul)
  await lh.discard_tips96()


async def main() -> None:
  server = VisualizerServer()
  await server.start()

  # "Start the entire thing over" rebuilds a completely fresh deck/backend/
  # LiquidHandler/thermocycler each pass -- same reasoning every other demo
  # in this repo's own while True: loop docstring gives.
  while True:
    deck = STARDeck()

    # -- Tip carriers: one fresh 96-rack per liquid-transfer step (15 total,
    # 4 carriers of up to 5 racks each) -- per this repo's established
    # "fresh tips every step" convention (see spri_cleanup_demo.py's own
    # docstring). No dedicated "transfer" rack any more: each SPRI cleanup's
    # own eluate transfer reuses the elution-buffer-add tips instead (per
    # user direction -- see run_spri_cleanup()'s own docstring). Grouped by
    # tip size across carriers, not by which step they belong to --
    # carriers 1-2 hold every 50uL rack, carriers 3-4 hold every 300uL rack
    # -- so loading/unloading tips at the deck only ever means visiting
    # "the 50uL carriers" or "the 300uL carriers", per user direction,
    # rather than every carrier stocking a mix of both.
    tip_carrier_1 = TIP_CAR_480_A00(name="tip_carrier_1")
    tip_rack_frag_mix = hamilton_96_tiprack_50uL_filter(name="tip_rack_frag_mix")  # 15uL transfer, 25uL mix
    tip_rack_erat_mix = hamilton_96_tiprack_50uL_filter(name="tip_rack_erat_mix")  # 10uL transfer, 30uL mix
    tip_rack_adapter = hamilton_96_tiprack_50uL_filter(name="tip_rack_adapter")  # 5uL transfer, no mix
    tip_rack_ligation_mix = hamilton_96_tiprack_50uL_filter(name="tip_rack_ligation_mix")  # 45uL transfer, 50uL mix
    tip_rack_elution_add_1 = hamilton_96_tiprack_50uL_filter(name="tip_rack_elution_add_1")  # 25uL transfer, 15uL mix, reused for the 20uL eluate transfer
    tip_carrier_1[0] = tip_rack_frag_mix
    tip_carrier_1[1] = tip_rack_erat_mix
    tip_carrier_1[2] = tip_rack_adapter
    tip_carrier_1[3] = tip_rack_ligation_mix
    tip_carrier_1[4] = tip_rack_elution_add_1
    deck.assign_child_resource(tip_carrier_1, rails=1)

    tip_carrier_2 = TIP_CAR_480_A00(name="tip_carrier_2")
    tip_rack_pcr_mix = hamilton_96_tiprack_50uL_filter(name="tip_rack_pcr_mix")  # 30uL transfer, 25uL mix
    tip_rack_bead_2 = hamilton_96_tiprack_50uL_filter(name="tip_rack_bead_2")  # 50uL transfer, 40uL mix
    tip_rack_elution_add_2 = hamilton_96_tiprack_50uL_filter(name="tip_rack_elution_add_2")  # 25uL transfer, 15uL mix, reused for the final eluate transfer
    tip_carrier_2[0] = tip_rack_pcr_mix
    tip_carrier_2[1] = tip_rack_bead_2
    tip_carrier_2[2] = tip_rack_elution_add_2
    deck.assign_child_resource(tip_carrier_2, rails=7)

    tip_carrier_3 = TIP_CAR_480_A00(name="tip_carrier_3")
    tip_rack_bead_1 = hamilton_96_tiprack_300uL_filter(name="tip_rack_bead_1")  # 88uL transfer
    tip_rack_remove_sup_1 = hamilton_96_tiprack_300uL_filter(name="tip_rack_remove_sup_1")  # 198uL
    tip_rack_etoh1_1 = hamilton_96_tiprack_300uL_filter(name="tip_rack_etoh1_1")  # 200uL
    tip_rack_etoh2_1 = hamilton_96_tiprack_300uL_filter(name="tip_rack_etoh2_1")  # 200uL
    tip_rack_remove_sup_2 = hamilton_96_tiprack_300uL_filter(name="tip_rack_remove_sup_2")  # 100uL
    tip_carrier_3[0] = tip_rack_bead_1
    tip_carrier_3[1] = tip_rack_remove_sup_1
    tip_carrier_3[2] = tip_rack_etoh1_1
    tip_carrier_3[3] = tip_rack_etoh2_1
    tip_carrier_3[4] = tip_rack_remove_sup_2
    deck.assign_child_resource(tip_carrier_3, rails=13)

    tip_carrier_4 = TIP_CAR_480_A00(name="tip_carrier_4")
    tip_rack_etoh1_2 = hamilton_96_tiprack_300uL_filter(name="tip_rack_etoh1_2")  # 200uL
    tip_rack_etoh2_2 = hamilton_96_tiprack_300uL_filter(name="tip_rack_etoh2_2")  # 200uL
    tip_carrier_4[0] = tip_rack_etoh1_2
    tip_carrier_4[1] = tip_rack_etoh2_2
    deck.assign_child_resource(tip_carrier_4, rails=19)

    # -- Reagent tubes: the four premixes, each in its own Eppendorf tube --
    # see this module's own docstring for why ERAT Mix gets a 1.5mL tube
    # while Frag/Ligation/PCR Mix each need a 5mL snap-cap tube instead.
    # Placed from site 6 onward on each carrier, not the front-most sites
    # (0-4) -- per user direction: an 8-channel head can't align onto a
    # site that close to the carrier's own front edge, the same reasoning
    # picogreen_demo.py's own tube placement (site 6/7 of its 32-site
    # carrier, never site 0) already follows in this repo.
    tube_carrier_small = hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL(name="tube_carrier_small")
    erat_mix_tube = eppendorf_tube_1500uL_Vb(name="erat_mix_tube")
    tube_carrier_small[6] = erat_mix_tube
    deck.assign_child_resource(tube_carrier_small, rails=25)

    tube_carrier_large = Tube_CAR_24_A00(name="tube_carrier_large")
    frag_mix_tube = eppendorf_tube_5mL_Vb_snapcap(name="frag_mix_tube")
    ligation_mix_tube = eppendorf_tube_5mL_Vb_snapcap(name="ligation_mix_tube")
    pcr_mix_tube = eppendorf_tube_5mL_Vb_snapcap(name="pcr_mix_tube")
    tube_carrier_large[6] = frag_mix_tube
    tube_carrier_large[7] = ligation_mix_tube
    tube_carrier_large[8] = pcr_mix_tube
    deck.assign_child_resource(tube_carrier_large, rails=26)

    # -- SPRI bead trough: still a bulk reagent (13,248uL total draw across
    # both cleanups), unaffected by the Eppendorf-tube correction above --
    # narrow/8-channel-only, same as spri_cleanup_demo.py's own bead trough.
    # Site 1, not site 0 -- per user direction, same front-edge reach
    # concern as the tubes above.
    reagent_carrier = Trough_CAR_5R60_A00(name="reagent_carrier")
    bead_reservoir = hamilton_1_trough_60mL_Vb(name="bead_reservoir")
    reagent_carrier[1] = bead_reservoir
    deck.assign_child_resource(reagent_carrier, rails=27)

    # -- Plate carrier 1: working_plate and its own lid, the Alpaqua
    # magnetic rack, amp_plate and its own lid. Each plate keeps a
    # dedicated lid, capped fresh before every ODTC visit and parked here
    # the rest of the time (see this module's own docstring, correction 2).
    plate_carrier_1 = PLT_CAR_L5AC_A00(name="plate_carrier_1")
    working_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="working_plate")
    working_plate_lid = cor_96_wellplate_360uL_Fb_lid(name="working_plate_lid")
    alpaqua_rack = alpaqua_96_plateadapter_magnum_flx(name="alpaqua_rack")
    amp_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="amp_plate")
    amp_plate_lid = cor_96_wellplate_360uL_Fb_lid(name="amp_plate_lid")
    plate_carrier_1[0] = working_plate
    plate_carrier_1[1] = working_plate_lid
    plate_carrier_1[2] = alpaqua_rack
    plate_carrier_1[3] = amp_plate
    plate_carrier_1[4] = amp_plate_lid
    deck.assign_child_resource(plate_carrier_1, rails=28)

    # -- Plate carrier 2: the adapter plate, the final output plate, and
    # the ethanol/elution troughplates (full-footprint, 96-head -- see this
    # module's own docstring for why these stay this shape).
    plate_carrier_2 = PLT_CAR_L5AC_A00(name="plate_carrier_2")
    # A real KAPA UDI Adapter Kit plate is a 96-well PCR plate, not a
    # flat-bottom one -- corrected per user direction; same plate type as
    # working_plate/amp_plate/output_plate below.
    adapter_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="adapter_plate")
    output_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="output_plate")
    ethanol_reservoir = nest_1_troughplate_195000uL_Vb(name="ethanol_reservoir")
    elution_reservoir = nest_1_troughplate_195000uL_Vb(name="elution_reservoir")
    plate_carrier_2[0] = adapter_plate
    plate_carrier_2[1] = output_plate
    plate_carrier_2[2] = ethanol_reservoir
    plate_carrier_2[3] = elution_reservoir
    deck.assign_child_resource(plate_carrier_2, rails=35)

    # -- Inheco ODTC: a pure cycling destination now -- no resident plate,
    # no reagent addition ever happens here (see this module's own
    # docstring, correction 3). Placed exactly like thermocycler_demo.py's/
    # pcr_setup_demo.py's own ODTC.
    tc_name = "thermocycler_1"
    inner_tc = ThermocyclerChatterboxBackend(name=f"{tc_name}_chatter", num_zones=1)
    tc_backend = VisualizerThermocyclerBackend(inner_tc, server, resource_name=tc_name)
    tc = inheco_odtc_thermocycler(tc_name, backend=tc_backend)
    rails = 42
    rail_location = deck.rails_to_location(rails)
    centered_y = (deck.get_size_y() - tc.get_size_y()) / 2
    deck.assign_child_resource(tc, location=Coordinate(x=rail_location.x, y=centered_y, z=rail_location.z))

    inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
    backend = VisualizerBackend(inner_backend, server)
    lh = LiquidHandler(backend=backend, deck=deck)
    attach_sleep(lh)  # lh.sleep(seconds, resource) -- see spri_cleanup_demo.py's own docstring
    await tc_backend.setup()
    await lh.setup()  # also broadcasts the scene and turns on tip/volume tracking

    # Every sample well and every reservoir/tube pre-filled before Start,
    # same reasoning as every other demo in this repo (visible from frame 0).
    for well in working_plate.get_all_items():
      well.set_volume(DNA_INPUT_UL)
    for well in adapter_plate.get_all_items():
      well.set_volume(ADAPTER_PLATE_FILL_UL)
    bead_reservoir.tracker.set_volume(BEAD_RESERVOIR_FILL_UL)
    frag_mix_tube.tracker.set_volume(FRAG_MIX_TUBE_FILL_UL)
    erat_mix_tube.tracker.set_volume(ERAT_MIX_TUBE_FILL_UL)
    ligation_mix_tube.tracker.set_volume(LIGATION_MIX_TUBE_FILL_UL)
    pcr_mix_tube.tracker.set_volume(PCR_MIX_TUBE_FILL_UL)
    ethanol_reservoir.get_item(0).tracker.set_volume(ETHANOL_RESERVOIR_FILL_UL)
    elution_reservoir.get_item(0).tracker.set_volume(ELUTION_RESERVOIR_FILL_UL)
    await backend.broadcast_state()  # these fills weren't part of the initial scene broadcast

    print("Open the visualizer, then click 'Start Protocol' when ready.")
    await backend.wait_for_start()
    print("Started.")

    # ============================================================
    # Chapter 3: Prepare the Sample Library
    # ============================================================

    # -- Step 1. Enzymatic Fragmentation -------------------------------------
    # The IFU calls for this specific reaction to be "assembled on ice"
    # (Chapter 3, Step 1, item 2) -- per user direction, the ODTC's own
    # pre-cooled block substitutes for a benchtop ice bucket here: the bare,
    # uncapped plate lands on the block first, Frag Mix goes in directly
    # while it sits there (cold the entire time the reagents combine), and
    # only then does the lid go on, immediately before cycling starts. Every
    # other thermal step in this file still keeps reagent addition off the
    # ODTC entirely (see this module's own docstring, correction 3) --
    # fragmentation is the one exception, since it's the only step the IFU
    # specifically calls out as cold-sensitive during assembly (ERAT and
    # Ligation are each assembled at room temperature, then a separate
    # capped ODTC visit follows).
    print("Pre-cooling the ODTC block to 4degC...")
    await tc.set_block_temperature([4.0])  # Chapter 3, Step 1, item 4a ("Pre-cool block: +4degC")
    # No visualizer event for this call -- a real, silent low-level
    # primitive, same as run_thermal_step()'s own open_lid/close_lid calls
    # forward internally (see VisualizerThermocyclerBackend's own docstring).

    print("Opening the ODTC's lid to receive the plate...")
    await tc.open_lid()

    print("Moving working_plate onto the pre-cooled ODTC, uncapped...")
    await lh.move_plate(working_plate, tc, use_arm="core")

    print(f"Mixing {FRAG_MIX_UL:g}uL of KAPA Frag Buffer + Enzyme into every well (on the ODTC block)...")
    await add_premix_from_tube(
      lh, plate=working_plate, tube=frag_mix_tube, tip_rack=tip_rack_frag_mix, volume_ul=FRAG_MIX_UL, mix=FRAG_MIX_MIX
    )

    print("Capping working_plate with its lid...")
    await lh.move_lid(working_plate_lid, working_plate, use_arm="core")

    print("Closing the ODTC's lid...")
    await tc.close_lid()

    print("Running the fragmentation protocol (10 min at 37degC)...")
    await tc.run_protocol(FRAGMENTATION_PROTOCOL, block_max_volume=POST_FRAG_UL)

    print("Opening the ODTC's lid...")
    await tc.open_lid()

    print("Moving working_plate back to its own carrier site...")
    await lh.move_plate(working_plate, plate_carrier_1[0], use_arm="core")

    print("Closing the ODTC's lid...")
    await tc.close_lid()

    print("Uncapping working_plate...")
    await lh.move_lid(working_plate.lid, plate_carrier_1[1], use_arm="core")

    # -- Step 2. End Repair and A-Tailing -------------------------------------
    print(f"Mixing {ERAT_MIX_UL:g}uL of End Repair & A-Tailing Buffer + Enzyme Mix into every well...")
    await add_premix_from_tube(
      lh, plate=working_plate, tube=erat_mix_tube, tip_rack=tip_rack_erat_mix, volume_ul=ERAT_MIX_UL, mix=ERAT_MIX_MIX
    )

    await run_thermal_step(
      lh,
      tc,
      plate=working_plate,
      plate_home_site=plate_carrier_1[0],
      lid=working_plate_lid,
      lid_home_site=plate_carrier_1[1],
      protocol=ERAT_PROTOCOL,
      block_max_volume=POST_ERAT_UL,
      label="End Repair & A-Tailing (30 min at 65degC)",
    )

    # -- Step 3. Adapter Ligation ----------------------------------------------
    # KAPA UDI Adapters must be added before the ligation reagents -- a
    # single CO-RE 96 head pickup, since it's a real 1:1 well-to-well
    # transfer (see this module's own docstring).
    print(f"Transferring {ADAPTER_UL:g}uL of KAPA UDI Adapter into every well...")
    await lh.pick_up_tips96(tip_rack_adapter)
    await lh.aspirate96(adapter_plate, volume=ADAPTER_UL)
    await lh.dispense96(working_plate, volume=ADAPTER_UL)
    await lh.discard_tips96()

    print(f"Mixing {LIGATION_MIX_UL:g}uL of Ligation Buffer + DNA Ligase + water into every well...")
    await add_premix_from_tube(
      lh,
      plate=working_plate,
      tube=ligation_mix_tube,
      tip_rack=tip_rack_ligation_mix,
      volume_ul=LIGATION_MIX_UL,
      mix=LIGATION_MIX_MIX,
    )

    await run_thermal_step(
      lh,
      tc,
      plate=working_plate,
      plate_home_site=plate_carrier_1[0],
      lid=working_plate_lid,
      lid_home_site=plate_carrier_1[1],
      protocol=LIGATION_PROTOCOL,
      block_max_volume=POST_LIGATION_UL,
      label="Adapter Ligation (15 min at 20degC)",
    )

    # -- Step 4. Purify the Sample Library using KAPA HyperPure Beads --------
    print("Post-ligation SPRI cleanup...")
    await run_spri_cleanup(
      lh,
      plate=working_plate,
      home_site=plate_carrier_1[0],
      alpaqua_rack=alpaqua_rack,
      bead_reservoir=bead_reservoir,
      ethanol_reservoir=ethanol_reservoir,
      elution_reservoir=elution_reservoir,
      bead_volume_ul=BEAD_RATIO_POST_LIGATION_UL,
      bead_mix=BEAD_MIX_POST_LIGATION,
      bead_tip_rack=tip_rack_bead_1,
      post_bead_volume_ul=POST_LIGATION_BEAD_TOTAL_UL,
      elution_volume_ul=POST_LIGATION_ELUTION_UL,
      transfer_volume_ul=POST_LIGATION_TRANSFER_UL,
      output_plate=amp_plate,
      tip_rack_remove_supernatant=tip_rack_remove_sup_1,
      tip_racks_etoh=[tip_rack_etoh1_1, tip_rack_etoh2_1],
      tip_rack_elution_add=tip_rack_elution_add_1,
    )
    # working_plate's own run is functionally done here -- amp_plate now
    # holds the purified, adapter-ligated library and takes over as this
    # protocol's own focus -- but working_plate itself is still parked on
    # the Alpaqua rack with its spent beads. It has to come off before
    # Chapter 4's own post-amplification cleanup can put amp_plate onto
    # that same rack (per user direction: only one plate fits the magnet
    # at a time).
    print("Moving working_plate off the magnetic rack to free it for amp_plate...")
    await lh.move_plate(working_plate, plate_carrier_1[0], use_arm="core")

    # ============================================================
    # Chapter 4: Amplify the Sample Library
    # ============================================================

    # -- Step 1. Prepare the Library Amplification Reaction -------------------
    print(f"Mixing {PCR_MIX_UL:g}uL of KAPA HiFi HotStart ReadyMix + Primer Mix into every well...")
    await add_premix_from_tube(
      lh, plate=amp_plate, tube=pcr_mix_tube, tip_rack=tip_rack_pcr_mix, volume_ul=PCR_MIX_UL, mix=PCR_MIX_MIX
    )

    # -- Step 2. Perform the Library Amplification -----------------------------
    await run_thermal_step(
      lh,
      tc,
      plate=amp_plate,
      plate_home_site=plate_carrier_1[3],
      lid=amp_plate_lid,
      lid_home_site=plate_carrier_1[4],
      protocol=AMPLIFICATION_PROTOCOL,
      block_max_volume=POST_PCR_MIX_UL,
      label="library amplification (2 cycles)",
    )

    # -- Step 3. Purify the Amplified Sample Library using KAPA HyperPure Beads
    print("Post-amplification SPRI cleanup...")
    await run_spri_cleanup(
      lh,
      plate=amp_plate,
      home_site=plate_carrier_1[3],
      alpaqua_rack=alpaqua_rack,
      bead_reservoir=bead_reservoir,
      ethanol_reservoir=ethanol_reservoir,
      elution_reservoir=elution_reservoir,
      bead_volume_ul=BEAD_RATIO_POST_AMP_UL,
      bead_mix=BEAD_MIX_POST_AMP,
      bead_tip_rack=tip_rack_bead_2,
      post_bead_volume_ul=POST_AMP_BEAD_TOTAL_UL,
      elution_volume_ul=POST_AMP_ELUTION_UL,
      transfer_volume_ul=POST_AMP_TRANSFER_UL,
      output_plate=output_plate,
      tip_rack_remove_supernatant=tip_rack_remove_sup_2,
      tip_racks_etoh=[tip_rack_etoh1_2, tip_rack_etoh2_2],
      tip_rack_elution_add=tip_rack_elution_add_2,
    )

    print("KAPA HyperPlus demo finished -- sequencing-ready library in output_plate.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await lh.stop()
    await tc_backend.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  asyncio.run(main())

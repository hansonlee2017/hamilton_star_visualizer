"""PicoGreen dsDNA quantitation demo: prepare an 8-point standard curve by
2-fold serial dilution, then transfer both unknown samples and standards
into an assay plate and add PicoGreen working reagent to each.

Two run parameters are entered in the visualizer's HUD, next to "Start
Protocol", instead of being hardcoded (see index.html's ``#run-params``):

  - **Sample volume** (1-20uL): how much sample/standard goes into each
    assay well. PicoGreen working solution then makes up the rest of a
    fixed 200uL total -- ``200 - sample_volume`` -- so every assay well
    ends up at the same total volume regardless of the split; this is a
    derived HUD readout, not its own input.
  - **Sample count** (1-88): how many unknown samples to run, placed
    column-wise on the sample plate starting at A1 (see
    ``sample_column_groups()``). 88 = 11 full columns of 8 -- the most
    that leaves column 12 free for the standard curve.

Both are read from ``VisualizerServer.wait_for_start()``'s return value
(whatever dict the "Start Protocol" click sent) once the button is clicked,
and can't change after that -- the server itself ignores a second
"start_protocol" message once one's been accepted (see
``VisualizerServer.wait_for_start()``'s docstring), and the HUD inputs are
locked in lockstep. A "Reset" button (locked until the run finishes --
``VisualizerServer.mark_finished()``/``wait_for_reset()``) tears the whole
thing down and loops back to a fresh deck with new parameters -- see
``main()``'s ``while True:`` below.

Deck layout (see the rails= values below for exact positions):
  - Unknown samples in columns 1-11 of a 96-well PCR plate, column-wise
    from A1 (up to 88 of them -- see ``sample_column_groups()``).
  - An 8-point 2-fold dilution series, prepared from a 100 ng/uL DNA stock
    and a TE diluent (site 7 and site 8 of one 32-tube carrier), directly
    into column 12 of that *same* PCR plate -- rows A-G hold the dilution
    series (A neat, each subsequent well half the concentration of the one
    before it), row H is left as pure diluent (the blank).
  - A Corning 360uL flat-bottom assay plate, empty until the transfers
    below fill it.
  - A 60mL Hamilton reservoir (site 2 of its carrier) holding PicoGreen
    working solution.
  - Two tip racks -- one 50uL, one 300uL (see ``fresh_tip_spots()``): a
    real protocol picks the smallest tip that comfortably holds a given
    transfer, not one size for everything. Only the sample/standard
    transfer (step 3 below) needs a fresh tip per column; the PicoGreen
    transfer (step 2) reuses a single tip pick-up for its entire stage (see
    that step), so even at the maximum sample count this protocol only
    ever needs 2 fresh 300uL columns total -- nowhere near one rack's 12.

Protocol:
  1. Prepare the standard curve. Diluent goes into every well but the top
     standard (including the blank, H12) via 7 channels (1-7) at once:
     each channel visits the tiny single-tube diluent source in turn (only
     one channel fits its ~10mm opening at a time -- see
     ``frontend/main.js``'s ``planGantryPasses()``), then all 7 dispense
     into their own row's well simultaneously, since B12-H12 share a
     column. Channel 0 alone then does the neat stock -> A12 transfer and
     the serial 2-fold dilution (A->B->...->F->G) -- both are inherently
     sequential (each step depends on the well before it), so one channel
     doing it with one tip is the realistic way, not a limitation. The
     other 7 channels aren't idle bystanders here, either: still holding
     their own tips, they physically travel along with channel 0 the whole
     time (planGantryPasses() drags any tip-loaded channel to wherever the
     arm goes, whether or not this specific call targets it).
  2. For each sample/standard column that matters, an up-to-8-channel
     transfer (the last sample column may be partial -- see
     ``sample_column_groups()``) adds PicoGreen working solution from the
     reservoir into the assay plate first -- all channels aspirate from
     the one reservoir simultaneously (``spread="wide"``, PyLabRobot's own
     idiom for multiple channels sharing a single large container; see
     ``LiquidHandler.aspirate()``'s docstring), rather than separate
     single-channel round trips. One tip pick-up covers every column in
     this stage -- the source (the reservoir) and the state of the
     destination (always empty) never change, so there's nothing a fresh
     tip would be protecting against.
  3. For those same columns, a transfer then moves the sample volume from
     the PCR plate on top -- the larger-volume reagent goes in first, so
     the small sample volume lands in (and mixes into) a substantial
     existing volume rather than the other way around. Unlike step 2, this
     one *does* get a fresh tip per column: each column's source is a
     different sample (or a different point on the standard curve), so
     reusing a tip across them would carry residue from one into the next.

Every transfer here is an ordinary ``LiquidHandler`` call -- no gantry-
planning code in this file at all; see ``frontend/main.js``'s
``planGantryPasses()`` for how the visualizer works out real motion
(including which channels are dragged along versus idle) on its own.

Run it with:

    uv run python examples/picogreen_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Tuple

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARLetDeck,
  Deck,
  Trough_CAR_5R60_A00,
  TipRack,
  azenta_96_wellplate_200uL_Vb_4titudeframestar,
  cor_96_wellplate_360uL_Fb,
  eppendorf_tube_1500uL_Vb,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_50uL_filter,
  hamilton_96_tiprack_300uL_filter,
  hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL,
)
from pylabrobot.resources.trough import Trough
from pylabrobot.resources.tube import Tube
from pylabrobot.resources.plate import Plate

from hamilton_visualizer import VisualizerBackend, VisualizerServer

STANDARD_COLUMN = "12"
ROWS = "ABCDEFGH"

DILUTION_VOLUME = 100.0  # uL per standard-curve well, fixed regardless of run params

# Every assay well ends up at this total volume -- PicoGreen working
# solution makes up whatever the sample volume doesn't. Matches
# frontend/main.js's ASSAY_TOTAL_VOLUME_UL (the HUD's derived readout).
ASSAY_TOTAL_VOLUME_UL = 200.0

# Matches index.html's #sample-volume-input/#sample-count-input min/max/
# value attributes -- kept in sync by hand, same as every other place a
# real quantity appears in both the Python protocol and the JS HUD.
MIN_SAMPLE_VOLUME_UL, MAX_SAMPLE_VOLUME_UL, DEFAULT_SAMPLE_VOLUME_UL = 1.0, 20.0, 5.0
# 88 = 11 full columns of 8 -- the most that still leaves column 12 free
# for the standard curve (see sample_column_groups()).
MIN_SAMPLE_COUNT, MAX_SAMPLE_COUNT, DEFAULT_SAMPLE_COUNT = 1, 88, 24


@dataclass
class Resources:
  """Every resource the protocol body below needs a direct handle to,
  bundled so ``build_deck()`` can hand them all back at once. Rebuilt fresh
  each pass through ``main()``'s loop -- see that function's docstring for
  why reusing one set of PyLabRobot resources/trackers across a Reset would
  be more fragile than just building new ones.
  """

  sample_plate: Plate
  assay_plate: Plate
  picogreen_reservoir: Trough
  dna_stock: Tube
  te_diluent: Tube
  tip_rack_50uL: TipRack
  tip_rack_300uL: TipRack


def build_deck() -> Tuple[Deck, Resources]:
  deck = STARLetDeck()

  # 50uL tips for the 1-20uL sample/standard transfer; 300uL tips for
  # everything else (the 100-200uL dilution stage, and the 180-199uL
  # PicoGreen transfer). Just one of each -- the PicoGreen transfer reuses
  # a single tip pick-up across every column (see the reuse comment where
  # that loop picks up tips, in main()) rather than one fresh column per
  # transfer stage, so even at the maximum sample count this protocol only
  # ever needs 2 fresh 300uL columns total (1 for the dilution stage, 1 for
  # the whole PicoGreen stage) -- nowhere near one rack's 12.
  tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
  tip_rack_50uL = hamilton_96_tiprack_50uL_filter(name="tip_rack_50uL")
  tip_rack_300uL = hamilton_96_tiprack_300uL_filter(name="tip_rack_300uL")
  tip_carrier[0] = tip_rack_50uL
  tip_carrier[1] = tip_rack_300uL
  deck.assign_child_resource(tip_carrier, rails=1)

  # Both the PCR sample plate and the Corning assay plate live on the same
  # carrier -- mirrors how demo_protocol.py/cherry_pick_demo.py pair a
  # source and destination plate.
  plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier_1")
  sample_plate = azenta_96_wellplate_200uL_Vb_4titudeframestar(name="sample_plate")
  assay_plate = cor_96_wellplate_360uL_Fb(name="assay_plate")
  plate_carrier[0] = sample_plate
  plate_carrier[1] = assay_plate
  deck.assign_child_resource(plate_carrier, rails=7)

  # Site 2 (1-indexed -- carrier[1] in PyLabRobot's own 0-indexed API) of
  # its carrier, not a deck rail -- "slot" here means a site *within* the
  # carrier.
  reservoir_carrier = Trough_CAR_5R60_A00(name="reservoir_carrier_1")
  picogreen_reservoir = hamilton_1_trough_60mL_Vb(name="picogreen_reservoir")
  reservoir_carrier[1] = picogreen_reservoir
  deck.assign_child_resource(reservoir_carrier, rails=13)

  # Both tubes on one 32-site carrier -- site 7 and site 8 (1-indexed:
  # carrier[6]/carrier[7]), again a site *within* the carrier, not a rail.
  tube_carrier = hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL(name="tube_carrier_1")
  dna_stock = eppendorf_tube_1500uL_Vb(name="dna_stock_100nguL")
  te_diluent = eppendorf_tube_1500uL_Vb(name="te_diluent")
  tube_carrier[6] = dna_stock
  tube_carrier[7] = te_diluent
  deck.assign_child_resource(tube_carrier, rails=14)

  return deck, Resources(
    sample_plate=sample_plate,
    assay_plate=assay_plate,
    picogreen_reservoir=picogreen_reservoir,
    dna_stock=dna_stock,
    te_diluent=te_diluent,
    tip_rack_50uL=tip_rack_50uL,
    tip_rack_300uL=tip_rack_300uL,
  )


def sample_column_groups(sample_count: int) -> List[Tuple[str, str]]:
  """Column-wise placement starting at A1: full 8-row columns until the
  last one, which may be partial -- e.g. 20 samples is columns 1-2 full
  (16) plus rows A-D of column 3 (4 more). Returns ``(column, rows)``
  pairs; ``rows`` is a prefix of ``ROWS`` (1-8 letters long).

  ``sample_count`` is capped at ``MAX_SAMPLE_COUNT`` (88 = 11 full
  columns), so this never reaches column 12 -- the standard curve's column
  -- regardless of what a caller passes in.
  """

  groups: List[Tuple[str, str]] = []
  remaining = min(sample_count, MAX_SAMPLE_COUNT)
  col = 1
  while remaining > 0:
    n = min(len(ROWS), remaining)
    groups.append((str(col), ROWS[:n]))
    remaining -= n
    col += 1
  return groups


def _clamped_param(params: Dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
  """Read ``key`` out of the "Start Protocol" click's params dict, falling
  back to ``default`` for anything missing or unparseable, and clamping to
  ``[lo, hi]`` regardless -- the value crossed a websocket from a browser,
  so it's treated the same as any other untrusted external input (argv, a
  config file) rather than trusted outright.
  """

  try:
    value = float(params.get(key, default))
  except (TypeError, ValueError):
    value = default
  return max(lo, min(hi, value))


def rack_column_stream(racks: List[TipRack]) -> Iterator[Tuple[TipRack, int]]:
  """Yield ``(rack, column)`` pairs across one or more same-size racks, one
  fresh column at a time -- moving on to the next rack once the current
  one's 12 columns (a 96-tip rack only has 12) are used up. Takes a list
  so a caller with more fresh-tip pickups than one rack can hold isn't
  stuck raising ``StopIteration``/a PLR "no tip" error partway through a
  run; this protocol currently never needs more than one rack per tier
  (see this module's docstring), but the stream doesn't assume that.
  """

  for rack in racks:
    for col in range(1, 13):
      yield rack, col


async def main() -> None:
  server = VisualizerServer()
  await server.start()

  # "Start the entire thing over" (this module's docstring) rebuilds a
  # completely fresh deck/backend/LiquidHandler each pass, rather than
  # trying to hand-reset every tracker on the previous run's resources in
  # place -- PyLabRobot's tip/volume trackers, well contents, and
  # VisualizerBackend's per-resource state callbacks all get a clean slate
  # this way, for free, the same way restarting the whole script would give
  # you, just without actually restarting the process or the HTTP server.
  while True:
    deck, res = build_deck()

    inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
    backend = VisualizerBackend(inner_backend, server)
    lh = LiquidHandler(backend=backend, deck=deck)
    await lh.setup()  # also turns on tip/volume tracking -- see VisualizerBackend docstring

    # Reagents that don't depend on the run's parameters get pre-filled
    # right away, before waiting for "Start Protocol" -- so, like every
    # other demo in this repo, you can review them in the visualizer before
    # clicking it. The sample plate and PicoGreen reservoir *do* depend on
    # the sample count/volume entered in the HUD right next to that button,
    # so they can't be filled until after it's clicked -- see below.
    res.dna_stock.tracker.set_volume(500.0)
    res.te_diluent.tracker.set_volume(1000.0)

    # server.wait_for_start() (not backend.wait_for_start()) deliberately
    # skips backend's usual post-click state resync here -- this protocol
    # still has param-dependent pre-filling to do first (below), and that
    # resync is a one-shot broadcast of *current* state, not a live feed
    # (see _LIVE_CALLBACK_EXCLUDED_CATEGORIES's docstring): doing it now
    # would broadcast the not-yet-filled sample plate/reservoir, and
    # nothing would ever correct it. backend.broadcast_state() below does
    # the same resync once the fill is actually done.
    print("Open the visualizer, then click 'Start Protocol' when ready.")
    params = await server.wait_for_start()
    sample_volume = _clamped_param(
      params, "sample_volume_ul", DEFAULT_SAMPLE_VOLUME_UL, MIN_SAMPLE_VOLUME_UL, MAX_SAMPLE_VOLUME_UL
    )
    sample_count = int(
      _clamped_param(params, "sample_count", DEFAULT_SAMPLE_COUNT, MIN_SAMPLE_COUNT, MAX_SAMPLE_COUNT)
    )
    picogreen_volume = ASSAY_TOTAL_VOLUME_UL - sample_volume
    print(
      f"Started: {sample_count} sample(s) at {sample_volume}uL each "
      f"({picogreen_volume}uL PicoGreen per well)."
    )

    sample_groups = sample_column_groups(sample_count)
    for col, rows in sample_groups:
      for well in res.sample_plate[f"{rows[0]}{col}:{rows[-1]}{col}"]:
        well.set_volume(50.0)  # comfortably above the 1-20uL max sample transfer

    # Enough PicoGreen for every sample/standard well this run actually
    # uses (picogreen_volume uL x each of sample_count sample wells + the
    # 8 standard wells), plus a fixed 1000uL left over at the end -- not a
    # flat guess at the *starting* fill, a guaranteed *residual*, so there's
    # always a known amount of working solution still in the reservoir once
    # the run finishes, regardless of how much a given run actually used.
    # Capped at the trough's real 60mL capacity even though the true
    # maximum (88 samples, 199uL/well) comes nowhere close to it.
    RESIDUAL_PICOGREEN_UL = 1000.0
    required_picogreen = (sample_count + len(ROWS)) * picogreen_volume + RESIDUAL_PICOGREEN_UL
    res.picogreen_reservoir.tracker.set_volume(min(required_picogreen, 60_000.0))

    await backend.broadcast_state()

    # 1-50uL -> the 50uL rack, everything else -> a 300uL rack: the
    # smallest tip that comfortably holds the volume, same as real
    # practice.
    def tier_for_volume(volume_ul: float) -> str:
      return "50" if volume_ul <= 50 else "300"

    tip_streams = {
      "50": rack_column_stream([res.tip_rack_50uL]),
      "300": rack_column_stream([res.tip_rack_300uL]),
    }

    def fresh_tip_spots(tier: str, rows: str):
      rack, col = next(tip_streams[tier])
      return rack[f"{rows[0]}{col}:{rows[-1]}{col}"]

    standard_wells = res.sample_plate[[f"{row}{STANDARD_COLUMN}" for row in ROWS]]

    # Real STARBackend.aspirate()/dispense() kwargs -- minimum_traverse_
    # height_at_beginning_of_a_command (how high to rise before moving in
    # X/Y) and min_z_endpos (how high to retract to afterward). Both
    # default, on real hardware, to a conservative global "clear the whole
    # deck" height (STARBackend's own default is 245mm); every aspirate/
    # dispense below only ever needs to clear the *specific* resource it's
    # working with, not the whole deck -- the diluent tube, the DNA stock
    # tube, the sample plate (both the dilution stage's own wells and the
    # sample/standard transfer's source), and the assay plate never move
    # out from under a channel mid-stage, so none of them need the global
    # safe height. Grounded in this run's actual resources, not guessed:
    # each resource's own real top surface plus a small clearance margin.
    # A demo-only quirk: LiquidHandlerChatterboxBackend has no motion model
    # to begin with (it just prints a table row -- see chatterbox.py), so
    # this has no effect on how long the *backend* call takes here or on a
    # real robot's *pipetting* time either; it's genuinely a real-hardware
    # optimization for the seconds a physical arm would otherwise spend
    # traveling to and from a needlessly high safe height between
    # transfers. The visualizer *does* render it, though -- see events.py's
    # channel_ops_event() and frontend/main.js's animateChannelOp() for the
    # rest of this path.
    TRAVERSE_CLEARANCE_MM = 5.0

    def traverse_height_for(resource) -> float:
      return resource.get_absolute_location(z="top").z + TRAVERSE_CLEARANCE_MM

    sample_plate_traverse_height = traverse_height_for(res.sample_plate)
    assay_plate_traverse_height = traverse_height_for(res.assay_plate)
    reservoir_traverse_height = traverse_height_for(res.picogreen_reservoir)
    dna_stock_traverse_height = traverse_height_for(res.dna_stock)
    te_diluent_traverse_height = traverse_height_for(res.te_diluent)

    # -- standard curve: 2-fold serial dilution --------------------------------
    # All the dilution-stage volumes (100-200uL) call for 300uL tips. One
    # column, all 8 rows -> channels 0-7 -- picked up once, then used
    # selectively below (channel 0 alone for the sequential steps, channels
    # 1-7 together for the diluent distribution) rather than picking up
    # per-step.
    await lh.pick_up_tips(fresh_tip_spots(tier_for_volume(DILUTION_VOLUME), ROWS))
    await asyncio.sleep(0.3)

    # Diluent into every well but the top standard, including the blank
    # (H12) -- channels 1-7 each independently visit the tiny diluent tube
    # in turn (only one channel fits its ~10mm opening at a time), then all
    # 7 dispense into their own row's well simultaneously, since B12-H12
    # share a column.
    for channel in range(1, 8):
      await lh.aspirate(
        [res.te_diluent],
        vols=[DILUTION_VOLUME],
        use_channels=[channel],
        minimum_traverse_height_at_beginning_of_a_command=te_diluent_traverse_height,
        min_z_endpos=te_diluent_traverse_height,
      )
    await lh.dispense(
      standard_wells[1:],
      vols=[DILUTION_VOLUME] * 7,
      use_channels=list(range(1, 8)),
      minimum_traverse_height_at_beginning_of_a_command=sample_plate_traverse_height,
      min_z_endpos=sample_plate_traverse_height,
    )
    await asyncio.sleep(0.3)

    # Top standard: the neat 100 ng/uL stock, no dilution -- channel 0. *2x*
    # the other wells' volume, since the very next step pulls DILUTION_VOLUME
    # back out of it for the A->B transfer. Without the extra headroom, A12
    # would be left at 0uL: enough to make the dilution series arithmetic
    # work, but nothing left for this well's own assay-plate transfer later.
    await lh.aspirate(
      [res.dna_stock],
      vols=[DILUTION_VOLUME * 2],
      use_channels=[0],
      minimum_traverse_height_at_beginning_of_a_command=dna_stock_traverse_height,
      min_z_endpos=dna_stock_traverse_height,
    )
    await lh.dispense(
      [standard_wells[0]],
      vols=[DILUTION_VOLUME * 2],
      use_channels=[0],
      minimum_traverse_height_at_beginning_of_a_command=sample_plate_traverse_height,
      min_z_endpos=sample_plate_traverse_height,
    )
    await asyncio.sleep(0.3)

    # Serial 2-fold dilution across A12-G12 -- channel 0 alone, continuing
    # with the same tip it started with (descending concentration the whole
    # way, so no cross-contamination concern). H12 is deliberately never
    # touched again here, so it stays pure diluent (the blank). Source and
    # destination are both sample_plate wells throughout, so both legs use
    # the same traverse height.
    for source, target in zip(standard_wells[:-2], standard_wells[1:-1]):
      await lh.aspirate(
        [source],
        vols=[DILUTION_VOLUME],
        use_channels=[0],
        minimum_traverse_height_at_beginning_of_a_command=sample_plate_traverse_height,
        min_z_endpos=sample_plate_traverse_height,
      )
      await lh.dispense(
        [target],
        vols=[DILUTION_VOLUME],
        use_channels=[0],
        minimum_traverse_height_at_beginning_of_a_command=sample_plate_traverse_height,
        min_z_endpos=sample_plate_traverse_height,
      )
      await asyncio.sleep(0.2)

    await lh.discard_tips()
    # A real Hamilton's 8 channels share one arm (see frontend/main.js's
    # planGantryPasses() docstring): even with channels 1-7 dragged along
    # for realism during the steps above, the *whole arm* was still tied up
    # the entire time -- dragging a channel along still takes as long as
    # doing real work, it just isn't idle-and-ignored the way an earlier
    # version of this demo left it. So this wait is still the real time
    # nothing else could start, not a workaround: every channel ends this
    # stage with exactly 24 legs of animation (pick-up, 7 diluent-
    # distribution stops -- one real aspirate each, dragged along for the
    # other 6 -- the shared dispense, top-standard aspirate+dispense, 6
    # serial aspirate/dispense pairs, discard), each a full rise+x+y+
    # descend+hold+retract cycle. Only pick_up_tips/discard_tips (2 of the
    # 24) still rise/retract to the full global safe height (~1.6s/leg);
    # the other 22 all pass the traverse-height overrides above, so their
    # rise/retract legs are shorter -- ~1.1s/leg is an estimate (X/Y/
    # descend/hold are unaffected; only rise+retract shrink, by a fraction
    # that depends on each resource's own top height, verified live this
    # round -- see docs/PLAN.md's "Review round 23"). Still an estimate,
    # not a computed guarantee (this wait can't read the
    # frontend's actual per-op fraction), so it keeps the same proportional
    # safety margin round 9's cherry-pick demo found necessary, just
    # applied to a smaller, more accurate base instead of scaling up a
    # uniform 1.6s/leg across every leg regardless of whether it actually
    # still takes that long.
    dilution_stage_legs_full_height = 2  # pick_up_tips, discard_tips
    dilution_stage_legs_reduced_height = 22
    seconds_per_leg_full_height = 1.6
    seconds_per_leg_reduced_height = 1.1
    await asyncio.sleep(
      (
        dilution_stage_legs_full_height * seconds_per_leg_full_height
        + dilution_stage_legs_reduced_height * seconds_per_leg_reduced_height
      )
      * 1.3
    )

    # -- add PicoGreen working solution, then samples/standards ---------------
    # Added *before* the smaller-volume sample/standard transfer below --
    # dispensing the larger-volume reagent first means the small sample
    # volume lands in (and mixes into) a substantial existing volume,
    # rather than the other way around.
    transfer_groups = [*sample_groups, (STANDARD_COLUMN, ROWS)]

    # One tip pick-up for this *entire* stage, reused across every column --
    # unlike the sample/standard transfer below, every aspirate here draws
    # from the same single reservoir and every dispense lands in a still-
    # empty assay well, so there's no cross-contamination risk a fresh tip
    # per column would be guarding against (real practice: reuse a tip
    # freely when neither what it picks up nor what it lands in ever
    # changes). Picked up for all 8 channels regardless of the first
    # group's own size, since a later group may need more than an earlier
    # partial one did.
    picogreen_tier = tier_for_volume(picogreen_volume)
    await lh.pick_up_tips(fresh_tip_spots(picogreen_tier, ROWS))

    for col, rows in transfer_groups:
      n = len(rows)
      dest_wells = res.assay_plate[f"{rows[0]}{col}:{rows[-1]}{col}"]
      await lh.aspirate(
        [res.picogreen_reservoir] * n,
        vols=[picogreen_volume] * n,
        spread="wide",
        minimum_traverse_height_at_beginning_of_a_command=reservoir_traverse_height,
        min_z_endpos=reservoir_traverse_height,
      )
      await lh.dispense(
        dest_wells,
        vols=[picogreen_volume] * n,
        minimum_traverse_height_at_beginning_of_a_command=assay_plate_traverse_height,
        min_z_endpos=assay_plate_traverse_height,
      )
      await asyncio.sleep(0.3)
    await lh.discard_tips()

    # Samples/standards *do* need a fresh tip per column -- each one is a
    # different source (a different sample, or a different point on the
    # standard curve), so reusing a tip across them would carry residue
    # from one into the next.
    sample_tier = tier_for_volume(sample_volume)
    for col, rows in transfer_groups:
      n = len(rows)
      source_wells = res.sample_plate[f"{rows[0]}{col}:{rows[-1]}{col}"]
      dest_wells = res.assay_plate[f"{rows[0]}{col}:{rows[-1]}{col}"]
      await lh.pick_up_tips(fresh_tip_spots(sample_tier, rows))
      await lh.aspirate(
        source_wells,
        vols=[sample_volume] * n,
        minimum_traverse_height_at_beginning_of_a_command=sample_plate_traverse_height,
        min_z_endpos=sample_plate_traverse_height,
      )
      await lh.dispense(
        dest_wells,
        vols=[sample_volume] * n,
        minimum_traverse_height_at_beginning_of_a_command=assay_plate_traverse_height,
        min_z_endpos=assay_plate_traverse_height,
      )
      await lh.discard_tips()
      await asyncio.sleep(0.3)

    print("PicoGreen assay setup finished.")
    await server.mark_finished()
    print("Click 'Reset' in the visualizer to run again with new parameters, or Ctrl+C to exit.")
    await server.wait_for_reset()
    await lh.stop()
    await server.reset_for_new_run()
    print("Reset -- waiting for a new run.")


if __name__ == "__main__":
  asyncio.run(main())

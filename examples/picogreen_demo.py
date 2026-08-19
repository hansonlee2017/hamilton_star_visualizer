"""PicoGreen dsDNA quantitation demo: prepare an 8-point standard curve by
2-fold serial dilution, then transfer both unknown samples and standards
into an assay plate and add PicoGreen working reagent to each.

Deck layout (see the rails= values below for exact positions):
  - 24 unknown samples in columns 1-3 of a 96-well PCR plate (8 rows x 3
    columns).
  - An 8-point 2-fold dilution series, prepared from a 100 ng/uL DNA stock
    and a TE diluent (site 7 and site 8 of one 32-tube carrier), directly
    into column 12 of that *same* PCR plate -- rows A-G hold the dilution
    series (A neat, each subsequent well half the concentration of the one
    before it), row H is left as pure diluent (the blank).
  - A Corning 360uL flat-bottom assay plate, empty until the transfers
    below fill it.
  - A 60mL Hamilton reservoir (site 2 of its carrier) holding PicoGreen
    working solution.
  - Two tip rack sizes (50/300uL) -- see ``tip_rack_for_volume()``: a real
    protocol picks the smallest tip that comfortably holds a given
    transfer, not one size for everything (this protocol's volumes -
    5-200uL - never call for a 1000uL tip).

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
  2. For each of the 4 columns that matter (sample columns 1-3, standard
     column 12), an 8-channel transfer adds 195uL of PicoGreen working
     solution from the reservoir into the assay plate first -- all 8
     channels aspirate from the one reservoir simultaneously
     (``spread="wide"``, PyLabRobot's own idiom for multiple channels
     sharing a single large container; see ``LiquidHandler.aspirate()``'s
     docstring), rather than 8 separate single-channel round trips.
  3. For those same 4 columns, an 8-channel transfer then moves 5uL from
     the PCR plate on top -- the larger-volume reagent goes in first, so
     the small sample volume lands in (and mixes into) a substantial
     existing volume rather than the other way around.

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

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARLetDeck,
  Trough_CAR_5R60_A00,
  azenta_96_wellplate_200uL_Vb_4titudeframestar,
  cor_96_wellplate_360uL_Fb,
  eppendorf_tube_1500uL_Vb,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_50uL_filter,
  hamilton_96_tiprack_300uL_filter,
  hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer

STANDARD_COLUMN = "12"
SAMPLE_COLUMNS = ["1", "2", "3"]
ROWS = "ABCDEFGH"

DILUTION_VOLUME = 100.0  # uL per standard-curve well
SAMPLE_TRANSFER_VOLUME = 5.0  # uL of sample/standard into the assay plate
PICOGREEN_VOLUME = 195.0  # uL of working reagent per assay well


async def main() -> None:
  # -- deck layout ------------------------------------------------------------
  deck = STARLetDeck()

  # Every tip size this protocol needs lives on one carrier -- pick the
  # smallest tip that comfortably holds a given transfer (tip_rack_for_
  # volume() below), the same way a real protocol would, rather than
  # reaching for one size for everything. No 1000uL rack -- nothing here
  # ever aspirates/dispenses more than 200uL, so it would just sit unused.
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

  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()

  inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
  backend = VisualizerBackend(inner_backend, server)
  lh = LiquidHandler(backend=backend, deck=deck)
  await lh.setup()  # also turns on tip/volume tracking -- see VisualizerBackend docstring

  # -- pre-fill reagents/samples -----------------------------------------------
  for well in sample_plate["A1:H3"]:
    well.set_volume(50.0)
  dna_stock.tracker.set_volume(500.0)
  te_diluent.tracker.set_volume(1000.0)
  picogreen_reservoir.tracker.set_volume(10_000.0)

  # Wait for you to open the visualizer, check the initial state, and click
  # "Start Protocol" -- see demo_protocol.py for why backend.wait_for_start()
  # (not server.wait_for_start()) matters here: it re-syncs state so the
  # pre-fill above is visible from the very first frame.
  print("Open the visualizer, then click 'Start Protocol' when ready.")
  await backend.wait_for_start()
  print("Started.")

  # 1-50uL -> 50uL tips, 50-300uL -> 300uL tips: the smallest tip that
  # comfortably holds the volume, same as real practice. No volume in this
  # protocol exceeds 300uL, so there's no third tier here -- see the deck
  # layout above for why there's no 1000uL rack to fall back to anyway.
  def tip_rack_for_volume(volume_ul: float):
    if volume_ul <= 50:
      return tip_rack_50uL
    return tip_rack_300uL

  # A fresh tip-rack column per pipetting stage below, tracked separately
  # per rack size, so nothing ever tries to pick up from a spot an earlier
  # stage already emptied.
  tip_columns = {tip_rack_50uL: iter(range(1, 13)), tip_rack_300uL: iter(range(1, 13))}

  def fresh_tip_column(rack) -> str:
    return str(next(tip_columns[rack]))

  standard_wells = sample_plate[[f"{row}{STANDARD_COLUMN}" for row in ROWS]]

  # -- standard curve: 2-fold serial dilution ----------------------------------
  # All the dilution-stage volumes (100-200uL) call for 300uL tips. One
  # column, all 8 rows -> channels 0-7 -- picked up once, then used
  # selectively below (channel 0 alone for the sequential steps, channels
  # 1-7 together for the diluent distribution) rather than picking up
  # per-step.
  dilution_tip_rack = tip_rack_for_volume(DILUTION_VOLUME)
  tc = fresh_tip_column(dilution_tip_rack)
  await lh.pick_up_tips(dilution_tip_rack[f"A{tc}:H{tc}"])
  await asyncio.sleep(0.3)

  # Diluent into every well but the top standard, including the blank
  # (H12) -- channels 1-7 each independently visit the tiny diluent tube
  # in turn (only one channel fits its ~10mm opening at a time), then all
  # 7 dispense into their own row's well simultaneously, since B12-H12
  # share a column.
  for channel in range(1, 8):
    await lh.aspirate([te_diluent], vols=[DILUTION_VOLUME], use_channels=[channel])
  await lh.dispense(standard_wells[1:], vols=[DILUTION_VOLUME] * 7, use_channels=list(range(1, 8)))
  await asyncio.sleep(0.3)

  # Top standard: the neat 100 ng/uL stock, no dilution -- channel 0. *2x*
  # the other wells' volume, since the very next step pulls DILUTION_VOLUME
  # back out of it for the A->B transfer. Without the extra headroom, A12
  # would be left at 0uL: enough to make the dilution series arithmetic
  # work, but nothing left for this well's own 5uL assay-plate transfer
  # later.
  await lh.aspirate([dna_stock], vols=[DILUTION_VOLUME * 2], use_channels=[0])
  await lh.dispense([standard_wells[0]], vols=[DILUTION_VOLUME * 2], use_channels=[0])
  await asyncio.sleep(0.3)

  # Serial 2-fold dilution across A12-G12 -- channel 0 alone, continuing
  # with the same tip it started with (descending concentration the whole
  # way, so no cross-contamination concern). H12 is deliberately never
  # touched again here, so it stays pure diluent (the blank).
  for source, target in zip(standard_wells[:-2], standard_wells[1:-1]):
    await lh.aspirate([source], vols=[DILUTION_VOLUME], use_channels=[0])
    await lh.dispense([target], vols=[DILUTION_VOLUME], use_channels=[0])
    await asyncio.sleep(0.2)

  await lh.discard_tips()
  # A real Hamilton's 8 channels share one arm (see frontend/main.js's
  # planGantryPasses() docstring): even with channels 1-7 dragged along
  # for realism during the steps above, the *whole arm* was still tied up
  # the entire time -- dragging a channel along still takes the same
  # ~1.6s/leg as doing real work, it just isn't idle-and-ignored the way
  # an earlier version of this demo left it. So this wait is still the
  # real time nothing else could start, not a workaround: every channel
  # ends this stage with exactly 24 legs of animation (pick-up, 7 diluent-
  # distribution stops -- one real aspirate each, dragged along for the
  # other 6 -- the shared dispense, top-standard aspirate+dispense, 6
  # serial aspirate/dispense pairs, discard), each a full rise+x+y+
  # descend+hold+retract cycle (~1.6s at 1x), plus a margin (round 9's
  # cherry-pick demo found even a ~500ms/1.6s margin on a *single* pass
  # needed live tuning -- scaling that same proportion up over this many
  # legs is safer than guessing).
  dilution_stage_legs = 24
  seconds_per_leg = 1.6
  await asyncio.sleep(dilution_stage_legs * seconds_per_leg * 1.3)

  # -- add PicoGreen working solution -------------------------------------------
  # 195uL calls for 300uL tips. Added *before* the smaller-volume sample/
  # standard transfer below -- dispensing the larger-volume reagent first
  # means the small sample volume lands in (and mixes into) a substantial
  # existing volume, rather than the other way around.
  for col in [*SAMPLE_COLUMNS, STANDARD_COLUMN]:
    dest_wells = assay_plate[f"A{col}:H{col}"]
    tc = fresh_tip_column(tip_rack_300uL)
    await lh.pick_up_tips(tip_rack_300uL[f"A{tc}:H{tc}"])
    await lh.aspirate([picogreen_reservoir] * 8, vols=[PICOGREEN_VOLUME] * 8, spread="wide")
    await lh.dispense(dest_wells, vols=[PICOGREEN_VOLUME] * 8)
    await lh.discard_tips()
    await asyncio.sleep(0.3)

  # -- transfer samples + standards into the assay plate -----------------------
  # 5uL calls for 50uL tips.
  for col in [*SAMPLE_COLUMNS, STANDARD_COLUMN]:
    source_wells = sample_plate[f"A{col}:H{col}"]
    dest_wells = assay_plate[f"A{col}:H{col}"]
    tc = fresh_tip_column(tip_rack_50uL)
    await lh.pick_up_tips(tip_rack_50uL[f"A{tc}:H{tc}"])
    await lh.aspirate(source_wells, vols=[SAMPLE_TRANSFER_VOLUME] * 8)
    await lh.dispense(dest_wells, vols=[SAMPLE_TRANSFER_VOLUME] * 8)
    await lh.discard_tips()
    await asyncio.sleep(0.3)

  print("PicoGreen assay setup finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

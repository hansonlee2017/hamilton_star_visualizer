"""PicoGreen dsDNA quantitation demo: prepare an 8-point standard curve by
2-fold serial dilution, then transfer both unknown samples and standards
into an assay plate and add PicoGreen working reagent to each.

Deck layout:
  - 24 unknown samples in columns 1-3 of a 96-well PCR plate (8 rows x 3
    columns).
  - An 8-point 2-fold dilution series, prepared from a 100 ng/uL DNA stock
    and a TE diluent (each a 1.5mL Eppendorf tube on a 32-tube carrier),
    directly into column 12 of that *same* PCR plate -- rows A-G hold the
    dilution series (A neat, each subsequent well half the concentration
    of the one before it), row H is left as pure diluent (the blank).
  - A Corning 360uL flat-bottom assay plate, empty until the transfers
    below fill it.
  - A 60mL Hamilton reservoir holding PicoGreen working solution.

Protocol:
  1. Prepare the standard curve: a single channel/tip moves the neat stock
     into A12, distributes diluent to B12-H12, then serially transfers half
     the volume down the column (A->B->...->F->G), leaving H12 untouched
     beyond its initial diluent fill.
  2. For each of the 4 columns that matter (sample columns 1-3, standard
     column 12), an 8-channel transfer moves 5uL from the PCR plate into
     the matching column of the assay plate.
  3. For those same 4 columns, an 8-channel transfer adds 195uL of
     PicoGreen working solution from the reservoir on top -- all 8
     channels aspirate from the one reservoir simultaneously
     (``spread="wide"``, PyLabRobot's own idiom for multiple channels
     sharing a single large container; see ``LiquidHandler.aspirate()``'s
     docstring), rather than 8 separate single-channel round trips.

Every transfer here is an ordinary single ``LiquidHandler`` call -- no
gantry-planning code in this file at all; see
``frontend/main.js``'s ``planGantryPasses()`` for how the visualizer works
out real column-by-column motion for the calls whose targets don't share
an x (mirroring ``examples/cherry_pick_demo.py``).

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
  hamilton_96_tiprack_1000uL_filter,
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

  tip_carrier = TIP_CAR_480_A00(name="tip_carrier_1")
  tip_rack = hamilton_96_tiprack_1000uL_filter(name="tip_rack_1000uL")
  tip_carrier[0] = tip_rack
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

  reservoir_carrier = Trough_CAR_5R60_A00(name="reservoir_carrier_1")
  picogreen_reservoir = hamilton_1_trough_60mL_Vb(name="picogreen_reservoir")
  reservoir_carrier[0] = picogreen_reservoir
  deck.assign_child_resource(reservoir_carrier, rails=13)

  tube_carrier = hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL(name="tube_carrier_1")
  dna_stock = eppendorf_tube_1500uL_Vb(name="dna_stock_100nguL")
  te_diluent = eppendorf_tube_1500uL_Vb(name="te_diluent")
  tube_carrier[0] = dna_stock
  tube_carrier[1] = te_diluent
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

  # A fresh tip-rack column per pipetting stage below, so nothing ever tries
  # to pick up from a spot an earlier stage already emptied.
  tip_columns = iter(range(1, 13))

  def fresh_tip_column() -> str:
    return str(next(tip_columns))

  standard_wells = sample_plate[[f"{row}{STANDARD_COLUMN}" for row in ROWS]]

  # -- standard curve: 2-fold serial dilution, one channel --------------------
  await lh.pick_up_tips(tip_rack[f"A{fresh_tip_column()}"])
  await asyncio.sleep(0.3)

  # Top standard: the neat 100 ng/uL stock, no dilution -- *2x* the other
  # wells' volume, since the very next step pulls DILUTION_VOLUME back out
  # of it for the A->B transfer. Without the extra headroom, A12 would be
  # left at 0uL: enough to make the dilution series arithmetic work, but
  # nothing left for this well's own 5uL assay-plate transfer later.
  await lh.aspirate([dna_stock], vols=[DILUTION_VOLUME * 2])
  await lh.dispense([standard_wells[0]], vols=[DILUTION_VOLUME * 2])
  await asyncio.sleep(0.3)

  # Diluent into every other well, including the blank (H12) -- one
  # aspirate, then a dispense per well, the same "multi-dispense" technique
  # a real Hamilton uses to distribute a reagent from a single pickup.
  await lh.aspirate([te_diluent], vols=[DILUTION_VOLUME * (len(standard_wells) - 1)])
  for well in standard_wells[1:]:
    await lh.dispense([well], vols=[DILUTION_VOLUME])
  await asyncio.sleep(0.3)

  # Serial 2-fold dilution across A12-G12 -- H12 is deliberately never
  # touched again here, so it stays pure diluent (the blank).
  for source, target in zip(standard_wells[:-2], standard_wells[1:-1]):
    await lh.aspirate([source], vols=[DILUTION_VOLUME])
    await lh.dispense([target], vols=[DILUTION_VOLUME])
    await asyncio.sleep(0.2)

  await lh.discard_tips()
  # A real Hamilton's 8 channels are all bolted to one arm (see
  # frontend/main.js's planGantryPasses() docstring): while channel 0 alone
  # was off doing this single-channel dilution, channels 1-7 physically
  # couldn't have started anything else, wherever they're needed next --
  # they're all tied to the same x motor. So this wait isn't just cosmetic
  # pacing, it's the real time the whole arm was unavailable: 24 single-
  # channel legs (pick-up, top-standard aspirate+dispense, diluent
  # aspirate+7 dispenses, 6 serial aspirate+dispense pairs, discard), each
  # a full rise+x+y+descend+hold+retract cycle (~1.6s at 1x -- see
  # frontend/main.js's RISE_MS/X_MOVE_MS/Y_MOVE_MS/DESCEND_MS/HOLD_MS/
  # RETRACT_MS), plus a margin (round 9's cherry-pick demo found even a
  # ~500ms/1.6s margin on a *single* pass needed live tuning -- scaling
  # that same proportion up over this many legs is safer than guessing).
  dilution_stage_legs = 24
  seconds_per_leg = 1.6
  await asyncio.sleep(dilution_stage_legs * seconds_per_leg * 1.3)

  # -- transfer samples + standards into the assay plate -----------------------
  for col in [*SAMPLE_COLUMNS, STANDARD_COLUMN]:
    source_wells = sample_plate[f"A{col}:H{col}"]
    dest_wells = assay_plate[f"A{col}:H{col}"]
    tc = fresh_tip_column()
    await lh.pick_up_tips(tip_rack[f"A{tc}:H{tc}"])
    await lh.aspirate(source_wells, vols=[SAMPLE_TRANSFER_VOLUME] * 8)
    await lh.dispense(dest_wells, vols=[SAMPLE_TRANSFER_VOLUME] * 8)
    await lh.discard_tips()
    await asyncio.sleep(0.3)

  # -- add PicoGreen working solution -------------------------------------------
  for col in [*SAMPLE_COLUMNS, STANDARD_COLUMN]:
    dest_wells = assay_plate[f"A{col}:H{col}"]
    tc = fresh_tip_column()
    await lh.pick_up_tips(tip_rack[f"A{tc}:H{tc}"])
    await lh.aspirate([picogreen_reservoir] * 8, vols=[PICOGREEN_VOLUME] * 8, spread="wide")
    await lh.dispense(dest_wells, vols=[PICOGREEN_VOLUME] * 8)
    await lh.discard_tips()
    await asyncio.sleep(0.3)

  print("PicoGreen assay setup finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())

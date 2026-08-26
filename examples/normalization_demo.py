"""Normalization protocol demo: read a 96-well plate's current
concentrations/volumes from a CSV, and dilute each sample down to one
target concentration in one final volume -- both entered in the HUD, not
hardcoded.

All of the actual "how much sample, how much diluent, in what order, or
should this well be skipped entirely" decision-making lives in
``hamilton_visualizer.normalization`` -- a small, pure module with no
PyLabRobot dependency at all (see its own docstring for the full rule
set), unit-tested on its own in ``tests/test_normalization.py``. This
script is deliberately just the PyLabRobot/visualizer plumbing on top of
that module's decisions -- it never recomputes or second-guesses a volume
or a flag, only acts on what ``compute_normalization()`` already decided.

HUD inputs (see ``VisualizerServer.set_run_params()``'s docstring for the
field schema):

  - **Target conc.**: the concentration every well should end up at.
  - **Final vol.** (50-200uL): the total volume (sample + diluent) each
    well ends up at.

Deck layout (see the rails= values below for exact positions):
  - Two separate 300uL tip racks -- one for sample transfers, one for
    diluent transfers (see "Tip strategy" below for why they can't share
    one).
  - A source plate, pre-filled from the CSV (before "Start Protocol", like
    every other demo in this repo -- see picogreen_demo.py's docstring for
    why only the *params-independent* setup can happen that early).
  - A destination plate, empty until the transfers below fill it.
  - A 60mL diluent reservoir, pre-filled *after* "Start Protocol" -- how
    much diluent the run needs depends on the target concentration/final
    volume just chosen, so (like picogreen_demo.py's own reservoir) it
    can't be filled any earlier.

Tip strategy: a fresh tip pair per *sample* transfer -- distinct
biological samples, cross-contamination-sensitive -- but diluent transfers
share tips across every well within a phase (see below), not a fresh pair
each time. That's safe here in a way it wouldn't be for the sample tips:
every diluent aspirate/dispense moves *exactly* the volume that well needs
(no leftover, unlike the ink demos' uniform-volume multi-dispense
pattern), so there's nothing left in the tip between wells for a later
well to inherit, and it's the same one shared liquid every time anyway.

Batched 8 channels at a time, but not indiscriminately: a real 8-channel
head does the same action (aspirate/dispense the same liquid type) on
every active channel in one command, so wells only batch together when
they agree on ``transfer_order`` (see normalization.py's docstring) --
three groups (sample-first, diluent-first, sample-only), each batched on
its own in chunks of up to 8, with per-channel volumes (PyLabRobot's
``vols=[...]`` already supports a different volume per channel in one
call -- no special-casing needed for that part).

Processed in three phases, not run group-by-group with the two liquids
interleaved per well -- a real channel can only hold *one* tip at a time,
so the diluent tips (shared across many wells) and the sample tips (fresh
every batch) can never both be mounted on the same channels at once (this
was tried and confirmed live: interleaving raises PyLabRobot's own
``HasTipError`` the moment a sample pick-up tries to use a channel a
diluent tip is still sitting on). So: **phase A** -- every diluent-first
well's diluent step (one shared tip pick-up covering the whole phase).
**Phase B** -- every well's sample step (diluent-first wells finishing
their sequence, sample-first/sample-only wells starting/finishing theirs;
fresh tips every batch, same as always). **Phase C** -- every sample-first
well's diluent step, finishing their sequence (a second shared tip
pick-up, from a different tip-rack column than phase A used). Splitting
sample-first's diluent step into its own later phase doesn't break rule
3's per-well ordering: diluent still lands in every diluent-first well
before phase B's sample step ever touches it, and sample still lands in
every sample-first well before phase C's diluent step ever touches it --
what matters is the order two liquids arrive in *the same well*, not
which tip-rack column happened to supply them.

Deliberately no ``asyncio.sleep()`` calls anywhere in this script -- see
picogreen_demo.py's module docstring for the full reasoning.

Run it with:

    uv run python examples/normalization_demo.py

then open the printed URL (defaults to http://127.0.0.1:8765), pick a
target concentration and final volume in the HUD, and click "Start
Protocol". A results CSV (every well's computed volumes and any flag) is
written next to this script once the run finishes.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
  PLT_CAR_L5AC_A00,
  TIP_CAR_480_A00,
  STARLetDeck,
  Trough_CAR_5R60_A00,
  cor_96_wellplate_360uL_Fb,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tiprack_300uL_filter,
)

from hamilton_visualizer import VisualizerBackend, VisualizerServer
from hamilton_visualizer.normalization import (
  NormalizationResult,
  compute_normalization,
  load_samples_csv,
  write_results_csv,
)

CSV_PATH = Path(__file__).parent / "normalization_samples.csv"
RESULTS_CSV_PATH = Path(__file__).parent / "normalization_results.csv"

# Matches index.html's HUD target-concentration/final-volume inputs' min/
# max/default -- built directly from these constants by
# server.set_run_params() below, so there's nothing to keep in sync by hand.
MIN_TARGET_CONCENTRATION, MAX_TARGET_CONCENTRATION, DEFAULT_TARGET_CONCENTRATION = 1.0, 1000.0, 50.0
MIN_FINAL_VOLUME_UL, MAX_FINAL_VOLUME_UL, DEFAULT_FINAL_VOLUME_UL = 50.0, 200.0, 100.0

BATCH_SIZE = 8  # one 8-channel call per batch

# A generous fixed margin on top of the run's exact computed diluent need
# (see main() for that computation) -- not a "some left over" guarantee
# like picogreen_demo.py's reservoir, just headroom for rounding.
DILUENT_MARGIN_UL = 2_000.0
TROUGH_MAX_VOLUME_UL = 60_000.0


def chunked(seq: list, n: int) -> list[list]:
  return [seq[i : i + n] for i in range(0, len(seq), n)]


def _clamped_param(params: Dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
  """Read ``key`` out of the "Start Protocol" click's params dict, falling
  back to ``default`` for anything missing or unparseable, and clamping to
  ``[lo, hi]`` regardless -- same helper picogreen_demo.py/pixel_art_demo.py
  use for their own numeric HUD fields.
  """

  try:
    value = float(params.get(key, default))
  except (TypeError, ValueError):
    value = default
  return max(lo, min(hi, value))


async def main() -> None:
  # -- wire up the visualizer -------------------------------------------------
  server = VisualizerServer()
  await server.start()
  await server.set_run_params(
    [
      {
        "id": "target_concentration",
        "type": "number",
        "label": "Target conc.",
        "min": MIN_TARGET_CONCENTRATION,
        "max": MAX_TARGET_CONCENTRATION,
        "step": 1,
        "default": DEFAULT_TARGET_CONCENTRATION,
        "title": "Concentration every sample should be normalized to",
      },
      {
        "id": "final_volume_ul",
        "type": "number",
        "label": "Final vol.",
        "min": MIN_FINAL_VOLUME_UL,
        "max": MAX_FINAL_VOLUME_UL,
        "step": 1,
        "default": DEFAULT_FINAL_VOLUME_UL,
        "suffix": "µL",
        "title": (
          f"Total volume (sample + diluent) each well ends up at "
          f"({MIN_FINAL_VOLUME_UL:g}-{MAX_FINAL_VOLUME_UL:g}uL)"
        ),
      },
    ]
  )

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
  # -- deck layout ----------------------------------------------------------
  deck = STARLetDeck()

  sample_tip_carrier = TIP_CAR_480_A00(name="sample_tip_carrier")
  sample_tip_rack = hamilton_96_tiprack_300uL_filter(name="sample_tip_rack")
  sample_tip_carrier[0] = sample_tip_rack
  deck.assign_child_resource(sample_tip_carrier, rails=1)

  diluent_tip_carrier = TIP_CAR_480_A00(name="diluent_tip_carrier")
  diluent_tip_rack = hamilton_96_tiprack_300uL_filter(name="diluent_tip_rack")
  diluent_tip_carrier[0] = diluent_tip_rack
  deck.assign_child_resource(diluent_tip_carrier, rails=7)

  source_plate_carrier = PLT_CAR_L5AC_A00(name="source_plate_carrier")
  source_plate = cor_96_wellplate_360uL_Fb(name="source_plate")
  source_plate_carrier[0] = source_plate
  deck.assign_child_resource(source_plate_carrier, rails=13)

  dest_plate_carrier = PLT_CAR_L5AC_A00(name="dest_plate_carrier")
  dest_plate = cor_96_wellplate_360uL_Fb(name="dest_plate")
  dest_plate_carrier[0] = dest_plate
  deck.assign_child_resource(dest_plate_carrier, rails=19)

  diluent_carrier = Trough_CAR_5R60_A00(name="diluent_carrier")
  diluent_reservoir = hamilton_1_trough_60mL_Vb(name="diluent_reservoir")
  diluent_carrier[2] = diluent_reservoir
  deck.assign_child_resource(diluent_carrier, rails=25)

  inner_backend = LiquidHandlerChatterboxBackend(num_channels=8)
  backend = VisualizerBackend(inner_backend, server)
  lh = LiquidHandler(backend=backend, deck=deck)
  await lh.setup()  # also turns on tip/volume tracking -- see VisualizerBackend docstring

  samples = load_samples_csv(CSV_PATH)

  # Source plate pre-filled straight from the CSV -- doesn't depend on the
  # HUD's target/final-volume params, so (like every other demo in this
  # repo) it's visible in the visualizer before "Start Protocol" is even
  # clicked.
  for s in samples:
    source_plate[s.well][0].set_volume(s.volume)

  # server.wait_for_start() (not backend.wait_for_start()) deliberately
  # skips backend's usual post-click state resync here -- the diluent
  # reservoir's required fill depends on the target/final-volume params
  # just chosen and can't be computed until after the click (see below).
  # backend.broadcast_state() does the same resync once that fill is
  # actually done -- same pattern picogreen_demo.py/pixel_art_demo.py use
  # for their own param-dependent reservoirs.
  print("Open the visualizer, then click 'Start Protocol' when ready.")
  params = await server.wait_for_start()
  target_concentration = _clamped_param(
    params, "target_concentration", DEFAULT_TARGET_CONCENTRATION, MIN_TARGET_CONCENTRATION, MAX_TARGET_CONCENTRATION
  )
  final_volume = _clamped_param(
    params, "final_volume_ul", DEFAULT_FINAL_VOLUME_UL, MIN_FINAL_VOLUME_UL, MAX_FINAL_VOLUME_UL
  )
  print(f"Started: target={target_concentration:g}, final_volume={final_volume:g}uL")

  results: List[NormalizationResult] = [
    compute_normalization(s, target_concentration, final_volume) for s in samples
  ]

  counts = Counter(r.flag or "ok" for r in results)
  for flag in ("ok", "diluent_skipped", "too_dilute_concentration", "insufficient_sample_volume", "too_concentrated"):
    if counts.get(flag):
      print(f"  {flag}: {counts[flag]}")

  # Enough diluent for every well this specific run actually needs, plus a
  # fixed margin -- not a flat guess (impossible now that both the target
  # concentration and final volume vary), and not the more elaborate
  # "cover the single largest in-flight draw" accounting pixel_art_demo.py
  # needs either: every diluent aspirate here moves *exactly* one well's
  # own diluent volume and dispenses all of it right away (no leftover
  # ever sits in a tip -- see this module's docstring), so there's no
  # momentary over-draw to cover, just the run's real total.
  total_diluent_needed = sum(r.diluent_volume_ul for r in results)
  diluent_reservoir.tracker.set_volume(min(total_diluent_needed + DILUENT_MARGIN_UL, TROUGH_MAX_VOLUME_UL))
  await backend.broadcast_state()

  write_results_csv(RESULTS_CSV_PATH, results)
  print(f"Wrote results to {RESULTS_CSV_PATH}")

  active = [r for r in results if not r.skipped]
  sample_first = [r for r in active if r.transfer_order == ("sample", "diluent")]
  diluent_first = [r for r in active if r.transfer_order == ("diluent", "sample")]
  sample_only = [r for r in active if r.transfer_order == ("sample",)]

  # One tip-rack column per sample batch -- fresh tips every time, see this
  # module's docstring for why.
  sample_tip_column = 0

  async def transfer_sample_batch(batch: List[NormalizationResult]) -> None:
    nonlocal sample_tip_column
    sample_tip_column += 1
    n = len(batch)
    await lh.pick_up_tips(sample_tip_rack[f"A{sample_tip_column}:H{sample_tip_column}"][:n])
    src_wells = source_plate[[r.well for r in batch]]
    dst_wells = dest_plate[[r.well for r in batch]]
    vols = [r.sample_volume_ul for r in batch]
    await lh.aspirate(src_wells, vols=vols)
    await lh.dispense(dst_wells, vols=vols)
    await lh.discard_tips()

  async def transfer_diluent_batch(batch: List[NormalizationResult]) -> None:
    n = len(batch)
    dst_wells = dest_plate[[r.well for r in batch]]
    vols = [r.diluent_volume_ul for r in batch]
    await lh.aspirate([diluent_reservoir] * n, vols=vols, spread="wide")
    await lh.dispense(dst_wells, vols=vols)

  # Three phases, not an interleaved "diluent batch, sample batch, diluent
  # batch, ..." loop: a real 8-channel head can only hold *one* tip per
  # channel at a time, so the diluent tips (held across many wells -- see
  # this module's docstring) and the sample tips (fresh every batch) can
  # never both be mounted at once. Splitting sample_first's own diluent
  # step into its own later phase (instead of picking the diluent tips up
  # once for the whole run) still gets every well its correct per-well
  # order -- diluent lands in a diluent_first well before phase B's sample
  # step touches it either way, and phase B's sample lands in a
  # sample_first well before phase C's diluent step touches it either way
  # (confirmed live: interleaving them raised `HasTipError: Channel has
  # tip` the first time phase B tried to pick up sample tips while phase
  # A's diluent tips were still mounted on the same channels).

  # Phase A: diluent_first wells' diluent step.
  if diluent_first:
    await lh.pick_up_tips(diluent_tip_rack["A1:H1"])
    for batch in chunked(diluent_first, BATCH_SIZE):
      await transfer_diluent_batch(batch)
    await lh.discard_tips()

  # Phase B: every well's sample step -- diluent_first wells finishing
  # their sequence, sample_first/sample_only wells starting/finishing
  # theirs.
  for batch in chunked(diluent_first, BATCH_SIZE):
    await transfer_sample_batch(batch)
  for batch in chunked(sample_first, BATCH_SIZE):
    await transfer_sample_batch(batch)
  for batch in chunked(sample_only, BATCH_SIZE):
    await transfer_sample_batch(batch)

  # Phase C: sample_first wells' diluent step, finishing their sequence --
  # a fresh tip-rack column, since column 1's spots were already discarded
  # in phase A and can't be re-picked from.
  if sample_first:
    await lh.pick_up_tips(diluent_tip_rack["A2:H2"])
    for batch in chunked(sample_first, BATCH_SIZE):
      await transfer_diluent_batch(batch)
    await lh.discard_tips()

  print("Normalization demo finished. Leaving the server up -- Ctrl+C to exit.")
  await asyncio.Event().wait()


if __name__ == "__main__":
  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    print("\nStopped.")

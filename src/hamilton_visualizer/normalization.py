"""Pure, PyLabRobot-free normalization-protocol logic: given a sample's
current concentration/volume, a target concentration, and a desired final
volume, work out how much sample and diluent to combine -- and whether
that's even possible with a real pipette.

Kept deliberately free of any PyLabRobot/asyncio dependency so it's cheap
to unit test in isolation (see ``tests/test_normalization.py``) -- the
demo script (``examples/normalization_demo.py``) is a thin PyLabRobot/
visualizer layer built on top of this module's pure functions, not the
other way around.

The math: diluting a sample never changes how much *solute* is in it, only
how much liquid it's spread across, so taking ``sample_volume_ul`` of a
``concentration``-strength sample and topping it up to ``final_volume_ul``
with plain diluent gives a final concentration of ``concentration *
sample_volume_ul / final_volume_ul``. Solving that for the target
concentration gives the one formula everything else here is built around::

    sample_volume_ul = target_concentration * final_volume_ul / concentration

Decision rules (checked in this order for every well):

1. **Achievability.** Diluting only ever *lowers* concentration, so if the
   sample's own ``concentration`` is already below ``target_concentration``,
   no amount of it (short of more than exists) could ever reach the target
   within ``final_volume_ul`` -- flagged ``TOO_DILUTE_CONCENTRATION``. If
   the concentration *would* work but the well doesn't actually hold
   enough of it (``sample_volume_ul > volume``), that's a distinct failure
   mode -- flagged ``INSUFFICIENT_SAMPLE_VOLUME`` -- since it's a "put more
   sample in this well" problem, not a "this sample can never work"
   problem. Both skip the well entirely (no transfer at all).
2. **Minimum pipettable volume** (``min_pipette_volume_ul``, 5uL by
   default): a real pipette can't reliably move less than this.
   - If the *sample* volume needed rounds to less than that, the sample is
     too concentrated to dose accurately -- flagged ``TOO_CONCENTRATED``,
     well skipped entirely (no transfer at all, same as rule 1's failures).
   - If the *diluent* volume needed rounds to less than that, the diluent
     addition is skipped (not the whole well) -- flagged
     ``DILUENT_SKIPPED``, and only the sample gets transferred, at the
     volume rule 1 already confirmed is available. The resulting well ends
     up slightly more concentrated than ``target_concentration`` (missing
     that sub-5uL top-up), accepted as the cost of not pipetting an
     unreliable volume.
3. **Transfer order.** Whichever of the two volumes being transferred is
   larger goes first -- returned as ``transfer_order``, e.g. ``("sample",
   "diluent")`` or ``("diluent", "sample")``. A well with only a sample
   transfer (rule 2's ``DILUENT_SKIPPED`` case) is just ``("sample",)``; a
   fully skipped well is ``()``.

All computed volumes are rounded to ``precision`` decimal places (0.1uL by
default, matching real pipetting resolution) *before* any of the above
threshold checks run, since those checks are about what would actually get
pipetted, not the unrounded theoretical value.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

MIN_PIPETTE_VOLUME_UL = 5.0
ROUND_PRECISION_UL = 1  # decimal places -- 0.1uL resolution

# -- flag reasons -------------------------------------------------------------
TOO_DILUTE_CONCENTRATION = "too_dilute_concentration"
INSUFFICIENT_SAMPLE_VOLUME = "insufficient_sample_volume"
TOO_CONCENTRATED = "too_concentrated"
DILUENT_SKIPPED = "diluent_skipped"

# Reasons that leave the well untouched entirely -- no sample or diluent
# transfer happens at all. DILUENT_SKIPPED is deliberately not in this set:
# that well still gets its sample transferred, just not the diluent.
SKIP_REASONS = frozenset({TOO_DILUTE_CONCENTRATION, INSUFFICIENT_SAMPLE_VOLUME, TOO_CONCENTRATED})


@dataclass(frozen=True)
class WellSample:
  """One row of the input CSV: a well's current state, before normalization."""

  sample_name: str
  well: str
  concentration: float
  volume: float


@dataclass(frozen=True)
class NormalizationResult:
  """The normalization decision for one well -- what (if anything) to
  transfer, in what order, and why (if anything went wrong).
  """

  sample_name: str
  well: str
  concentration: float
  volume: float
  target_concentration: float
  final_volume_ul: float
  sample_volume_ul: float  # 0.0 if the well is fully skipped
  diluent_volume_ul: float  # 0.0 if skipped, or if DILUENT_SKIPPED
  transfer_order: Tuple[str, ...]  # subset/permutation of ("sample", "diluent")
  flag: Optional[str]  # None if this well is a plain, unremarkable success

  @property
  def skipped(self) -> bool:
    """True if this well gets no liquid handling at all (rule 1's two
    failure modes, or rule 2's TOO_CONCENTRATED) -- False for a normal
    success *or* DILUENT_SKIPPED, both of which still transfer the sample.
    """

    return self.flag in SKIP_REASONS


def compute_normalization(
  sample: WellSample,
  target_concentration: float,
  final_volume_ul: float,
  *,
  min_pipette_volume_ul: float = MIN_PIPETTE_VOLUME_UL,
  precision: int = ROUND_PRECISION_UL,
) -> NormalizationResult:
  """Work out one well's normalization transfer -- see this module's
  docstring for the full rule set."""

  base = dict(
    sample_name=sample.sample_name,
    well=sample.well,
    concentration=sample.concentration,
    volume=sample.volume,
    target_concentration=target_concentration,
    final_volume_ul=final_volume_ul,
  )

  # Rule 1a: concentration itself is too low -- no volume of it (short of
  # more than physically exists) could ever reach target_concentration
  # within final_volume_ul. Guards concentration <= 0 too (undiluted
  # sample would need to be "more concentrated than infinity").
  if sample.concentration <= 0 or sample.concentration < target_concentration:
    return NormalizationResult(
      **base, sample_volume_ul=0.0, diluent_volume_ul=0.0, transfer_order=(), flag=TOO_DILUTE_CONCENTRATION
    )

  raw_sample_volume = target_concentration * final_volume_ul / sample.concentration
  sample_volume = round(raw_sample_volume, precision)

  # Rule 1b: the concentration would work, but this well doesn't actually
  # hold enough of it.
  if sample_volume > sample.volume:
    return NormalizationResult(
      **base, sample_volume_ul=0.0, diluent_volume_ul=0.0, transfer_order=(), flag=INSUFFICIENT_SAMPLE_VOLUME
    )

  # Rule 2a: the sample volume needed is too small to pipette accurately.
  if sample_volume < min_pipette_volume_ul:
    return NormalizationResult(
      **base, sample_volume_ul=0.0, diluent_volume_ul=0.0, transfer_order=(), flag=TOO_CONCENTRATED
    )

  # diluent_volume computed from the already-rounded sample_volume (not
  # the raw one) so the two actually-pipetted volumes sum to
  # round(final_volume_ul, precision) instead of drifting apart from two
  # independently-rounded numbers. Clamped at 0 -- rounding sample_volume
  # up can, in a rare edge case, push this a hair negative even though
  # sample_volume <= sample.volume was already confirmed above.
  diluent_volume = max(0.0, round(final_volume_ul - sample_volume, precision))

  # Rule 2b: the diluent top-up is too small to pipette accurately -- skip
  # just the diluent, not the whole well.
  if diluent_volume < min_pipette_volume_ul:
    return NormalizationResult(
      **base,
      sample_volume_ul=sample_volume,
      diluent_volume_ul=0.0,
      transfer_order=("sample",),
      flag=DILUENT_SKIPPED,
    )

  # Rule 3: larger volume first.
  order = ("sample", "diluent") if sample_volume >= diluent_volume else ("diluent", "sample")
  return NormalizationResult(
    **base, sample_volume_ul=sample_volume, diluent_volume_ul=diluent_volume, transfer_order=order, flag=None
  )


# -- CSV I/O ------------------------------------------------------------------
# Both plain functions over stdlib csv -- no PyLabRobot dependency, so
# these are just as unit-testable as compute_normalization() above.

INPUT_CSV_FIELDS = ["sample_name", "well", "concentration", "volume"]
RESULT_CSV_FIELDS = [
  "sample_name",
  "well",
  "concentration",
  "volume",
  "target_concentration",
  "final_volume_ul",
  "sample_volume_ul",
  "diluent_volume_ul",
  "transfer_order",
  "flag",
  "skipped",
]


def load_samples_csv(path: Union[str, Path]) -> List[WellSample]:
  """Read a ``sample_name,well,concentration,volume`` CSV (header row
  required) into a list of :class:`WellSample`."""

  samples = []
  with open(path, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    missing = set(INPUT_CSV_FIELDS) - set(reader.fieldnames or [])
    if missing:
      raise ValueError(f"{path}: missing required column(s): {sorted(missing)}")
    for row in reader:
      samples.append(
        WellSample(
          sample_name=row["sample_name"],
          well=row["well"],
          concentration=float(row["concentration"]),
          volume=float(row["volume"]),
        )
      )
  return samples


def write_results_csv(path: Union[str, Path], results: List[NormalizationResult]) -> None:
  """Write one row per well's normalization decision, including flags --
  the run's full audit trail, not just what got pipetted."""

  with open(path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=RESULT_CSV_FIELDS)
    writer.writeheader()
    for r in results:
      writer.writerow(
        {
          "sample_name": r.sample_name,
          "well": r.well,
          "concentration": r.concentration,
          "volume": r.volume,
          "target_concentration": r.target_concentration,
          "final_volume_ul": r.final_volume_ul,
          "sample_volume_ul": r.sample_volume_ul,
          "diluent_volume_ul": r.diluent_volume_ul,
          "transfer_order": "+".join(r.transfer_order),
          "flag": r.flag or "",
          "skipped": r.skipped,
        }
      )

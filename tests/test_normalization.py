"""Unit tests for ``hamilton_visualizer.normalization`` -- pure logic, no
PyLabRobot/asyncio involved (see that module's docstring for why). Run
with:

    uv run pytest
"""

from __future__ import annotations

import pytest

from hamilton_visualizer.normalization import (
  DILUENT_SKIPPED,
  INSUFFICIENT_SAMPLE_VOLUME,
  TOO_CONCENTRATED,
  TOO_DILUTE_CONCENTRATION,
  NormalizationResult,
  WellSample,
  compute_normalization,
  load_samples_csv,
  write_results_csv,
)


def sample(concentration: float, volume: float, *, name: str = "s1", well: str = "A1") -> WellSample:
  return WellSample(sample_name=name, well=well, concentration=concentration, volume=volume)


# -----------------------------------------------------------------------
# The plain success case
# -----------------------------------------------------------------------


def test_normal_case_computes_both_volumes():
  # concentration=200 (2x target), final_volume=100 -> needs 50uL sample,
  # 50uL diluent to hit target_concentration=100 in 100uL total.
  result = compute_normalization(sample(200.0, 80.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag is None
  assert result.skipped is False
  assert result.sample_volume_ul == pytest.approx(50.0)
  assert result.diluent_volume_ul == pytest.approx(50.0)
  # sample + diluent always sums to the (rounded) final volume for a
  # normal, unflagged well.
  assert result.sample_volume_ul + result.diluent_volume_ul == pytest.approx(100.0)


def test_result_carries_the_input_fields_through_unchanged():
  s = sample(200.0, 80.0, name="patient_7", well="C3")
  result = compute_normalization(s, target_concentration=100.0, final_volume_ul=100.0)
  assert result.sample_name == "patient_7"
  assert result.well == "C3"
  assert result.concentration == 200.0
  assert result.volume == 80.0
  assert result.target_concentration == 100.0
  assert result.final_volume_ul == 100.0


# -----------------------------------------------------------------------
# Rule 1a: TOO_DILUTE_CONCENTRATION -- concentration itself is too low,
# no achievable volume could ever reach target_concentration.
# -----------------------------------------------------------------------


def test_concentration_below_target_is_too_dilute():
  result = compute_normalization(sample(50.0, 100.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag == TOO_DILUTE_CONCENTRATION
  assert result.skipped is True
  assert result.sample_volume_ul == 0.0
  assert result.diluent_volume_ul == 0.0
  assert result.transfer_order == ()


def test_concentration_exactly_equal_to_target_is_not_too_dilute():
  # concentration == target is the boundary -- achievable (100% sample,
  # 0 diluent), not a TOO_DILUTE_CONCENTRATION failure.
  result = compute_normalization(sample(100.0, 100.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag != TOO_DILUTE_CONCENTRATION


def test_zero_concentration_is_too_dilute_not_a_crash():
  result = compute_normalization(sample(0.0, 100.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag == TOO_DILUTE_CONCENTRATION
  assert result.skipped is True


def test_negative_concentration_is_too_dilute_not_a_crash():
  result = compute_normalization(sample(-5.0, 100.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag == TOO_DILUTE_CONCENTRATION


# -----------------------------------------------------------------------
# Rule 1b: INSUFFICIENT_SAMPLE_VOLUME -- concentration is fine, but the
# well doesn't actually hold enough of it.
# -----------------------------------------------------------------------


def test_not_enough_sample_volume_available():
  # Needs 50uL (same as the normal case above) but the well only has 30uL.
  result = compute_normalization(sample(200.0, 30.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag == INSUFFICIENT_SAMPLE_VOLUME
  assert result.skipped is True
  assert result.sample_volume_ul == 0.0
  assert result.diluent_volume_ul == 0.0
  assert result.transfer_order == ()


def test_exactly_enough_sample_volume_is_not_insufficient():
  # volume == the exact amount needed is the boundary -- achievable.
  result = compute_normalization(sample(200.0, 50.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag != INSUFFICIENT_SAMPLE_VOLUME
  assert result.sample_volume_ul == pytest.approx(50.0)


def test_insufficient_volume_is_distinguished_from_too_dilute():
  # Same shortfall in absolute terms, but two different root causes should
  # produce two different flags.
  dilute = compute_normalization(sample(50.0, 100.0), target_concentration=100.0, final_volume_ul=100.0)
  insufficient = compute_normalization(sample(200.0, 30.0), target_concentration=100.0, final_volume_ul=100.0)
  assert dilute.flag == TOO_DILUTE_CONCENTRATION
  assert insufficient.flag == INSUFFICIENT_SAMPLE_VOLUME
  assert dilute.flag != insufficient.flag


# -----------------------------------------------------------------------
# Rule 2a: TOO_CONCENTRATED -- sample volume needed rounds below the
# minimum pipettable volume. Whole well skipped.
# -----------------------------------------------------------------------


def test_too_concentrated_sample_is_skipped():
  # target=10, final=100, concentration=1000 -> needs 1uL sample, well
  # under the 5uL floor.
  result = compute_normalization(sample(1000.0, 50.0), target_concentration=10.0, final_volume_ul=100.0)
  assert result.flag == TOO_CONCENTRATED
  assert result.skipped is True
  assert result.sample_volume_ul == 0.0
  assert result.diluent_volume_ul == 0.0
  assert result.transfer_order == ()


def test_sample_volume_exactly_at_minimum_is_not_too_concentrated():
  # target * final / concentration == 5.0 exactly -- the boundary passes.
  result = compute_normalization(sample(20.0, 50.0), target_concentration=1.0, final_volume_ul=100.0)
  assert result.sample_volume_ul == pytest.approx(5.0)
  assert result.flag != TOO_CONCENTRATED


def test_sample_volume_just_under_minimum_is_too_concentrated():
  # 1.0 * 100 / 21 = 4.7619... -> rounds to 4.8, under the 5uL floor.
  result = compute_normalization(sample(21.0, 50.0), target_concentration=1.0, final_volume_ul=100.0)
  assert result.sample_volume_ul == 0.0  # skipped wells report 0, not the pre-flag value
  assert result.flag == TOO_CONCENTRATED


# -----------------------------------------------------------------------
# Rule 2b: DILUENT_SKIPPED -- diluent volume needed rounds below the
# minimum. Only the diluent step is skipped; sample still transfers.
# -----------------------------------------------------------------------


def test_diluent_skipped_still_transfers_sample():
  # target=97, final=100, concentration=100 -> sample=97uL, diluent=3uL
  # (under the 5uL floor).
  result = compute_normalization(sample(100.0, 100.0), target_concentration=97.0, final_volume_ul=100.0)
  assert result.flag == DILUENT_SKIPPED
  assert result.skipped is False  # NOT a full skip -- sample still moves
  assert result.sample_volume_ul == pytest.approx(97.0)
  assert result.diluent_volume_ul == 0.0
  assert result.transfer_order == ("sample",)


def test_diluent_volume_exactly_at_minimum_is_not_skipped():
  # target=95, final=100, concentration=100 -> sample=95uL, diluent=5uL
  # exactly -- boundary passes, both legs happen.
  result = compute_normalization(sample(100.0, 100.0), target_concentration=95.0, final_volume_ul=100.0)
  assert result.diluent_volume_ul == pytest.approx(5.0)
  assert result.flag != DILUENT_SKIPPED
  assert result.transfer_order == ("sample", "diluent")


def test_no_diluent_needed_at_all_is_diluent_skipped():
  # concentration == target -> the whole final volume is sample, 0uL
  # diluent -- also falls under "diluent step doesn't happen".
  result = compute_normalization(sample(100.0, 100.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.flag == DILUENT_SKIPPED
  assert result.sample_volume_ul == pytest.approx(100.0)
  assert result.diluent_volume_ul == 0.0
  assert result.transfer_order == ("sample",)


# -----------------------------------------------------------------------
# Rule 3: transfer order -- larger volume first.
# -----------------------------------------------------------------------


def test_larger_sample_volume_transfers_first():
  # sample=80uL, diluent=20uL.
  result = compute_normalization(sample(125.0, 90.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.sample_volume_ul > result.diluent_volume_ul
  assert result.transfer_order == ("sample", "diluent")


def test_larger_diluent_volume_transfers_first():
  # sample=20uL, diluent=80uL.
  result = compute_normalization(sample(500.0, 30.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.diluent_volume_ul > result.sample_volume_ul
  assert result.transfer_order == ("diluent", "sample")


def test_equal_volumes_default_to_sample_first():
  # sample=50uL, diluent=50uL exactly.
  result = compute_normalization(sample(200.0, 60.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.sample_volume_ul == result.diluent_volume_ul == pytest.approx(50.0)
  assert result.transfer_order == ("sample", "diluent")


# -----------------------------------------------------------------------
# Rounding
# -----------------------------------------------------------------------


def test_volumes_round_to_declared_precision():
  # target*final/concentration = 100*100/300 = 33.333... -> rounds to 33.3.
  result = compute_normalization(sample(300.0, 50.0), target_concentration=100.0, final_volume_ul=100.0)
  assert result.sample_volume_ul == pytest.approx(33.3)
  # diluent computed from the *rounded* sample volume, so the two still
  # sum to exactly the final volume instead of drifting from independent
  # rounding.
  assert result.diluent_volume_ul == pytest.approx(66.7)
  assert result.sample_volume_ul + result.diluent_volume_ul == pytest.approx(100.0)


def test_custom_precision_is_respected():
  result = compute_normalization(
    sample(300.0, 50.0), target_concentration=100.0, final_volume_ul=100.0, precision=2
  )
  assert result.sample_volume_ul == pytest.approx(33.33)


def test_custom_min_pipette_volume_is_respected():
  # 3uL would normally pass (>= default 5uL floor is not the point here --
  # it's below it), but with a lowered floor of 1uL it should succeed.
  result = compute_normalization(
    sample(1000.0, 50.0), target_concentration=30.0, final_volume_ul=100.0, min_pipette_volume_ul=1.0
  )
  assert result.sample_volume_ul == pytest.approx(3.0)
  assert result.flag != TOO_CONCENTRATED


# -----------------------------------------------------------------------
# CSV I/O
# -----------------------------------------------------------------------


def test_load_samples_csv_round_trip(tmp_path):
  csv_path = tmp_path / "samples.csv"
  csv_path.write_text("sample_name,well,concentration,volume\ns1,A1,200.5,45.0\ns2,B1,80,60\n", encoding="utf-8")

  samples = load_samples_csv(csv_path)

  assert samples == [
    WellSample(sample_name="s1", well="A1", concentration=200.5, volume=45.0),
    WellSample(sample_name="s2", well="B1", concentration=80.0, volume=60.0),
  ]


def test_load_samples_csv_missing_column_raises(tmp_path):
  csv_path = tmp_path / "bad.csv"
  csv_path.write_text("sample_name,well,concentration\ns1,A1,200.5\n", encoding="utf-8")

  with pytest.raises(ValueError, match="volume"):
    load_samples_csv(csv_path)


def test_write_results_csv_includes_flags(tmp_path):
  results = [
    compute_normalization(sample(200.0, 80.0, name="ok", well="A1"), target_concentration=100.0, final_volume_ul=100.0),
    compute_normalization(sample(50.0, 100.0, name="dilute", well="B1"), target_concentration=100.0, final_volume_ul=100.0),
  ]
  out_path = tmp_path / "results.csv"

  write_results_csv(out_path, results)

  rows = out_path.read_text(encoding="utf-8").splitlines()
  assert rows[0] == (
    "sample_name,well,concentration,volume,target_concentration,final_volume_ul,"
    "sample_volume_ul,diluent_volume_ul,transfer_order,flag,skipped"
  )
  assert "ok,A1" in rows[1]
  assert "sample+diluent" in rows[1]
  assert ",False" in rows[1]
  assert "dilute,B1" in rows[2]
  assert "too_dilute_concentration" in rows[2]
  assert ",True" in rows[2]

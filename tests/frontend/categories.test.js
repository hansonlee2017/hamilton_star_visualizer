// Unit tests for frontend/categories.js's tip-capacity color bucketing.
// Run with:
//
//     node --test tests/frontend/

import { test } from "node:test";
import assert from "node:assert/strict";
import { tipColorForVolume } from "../../frontend/categories.js";

test("tipColorForVolume buckets by nameplate capacity", () => {
  assert.equal(tipColorForVolume(10), 0xf48fb1); // pink, <=50uL
  assert.equal(tipColorForVolume(50), 0xf48fb1); // boundary: inclusive
  assert.equal(tipColorForVolume(51), 0xffd54f); // yellow, <=300uL
  assert.equal(tipColorForVolume(300), 0xffd54f); // boundary: inclusive
  assert.equal(tipColorForVolume(301), 0xffffff); // white, everything larger
  assert.equal(tipColorForVolume(1000), 0xffffff);
});

test("tipColorForVolume falls back to the old flat amber for an unknown capacity", () => {
  assert.equal(tipColorForVolume(null), 0xe0b23d);
  assert.equal(tipColorForVolume(undefined), 0xe0b23d);
});

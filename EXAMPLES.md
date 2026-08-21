# Demo Examples

Five examples demonstrating the usefulness of PyLabRobot, Python, and AI
agents in lab automation — designed to run against the Hamilton Visualizer
so each one has a visual payoff, not just a printed log.

Suggested presentation order: **1 → 3 → 2 → 4 → 5** (instant payoff → relatable
pain → the "oh, that's useful" moment → real-infrastructure credibility →
the automated-safety-net callback). Numbering below follows the order they
were scoped in, not the presentation order.

---

## 1. Normalization worklist generation

**File:** `examples/normalization_demo.py`

Demonstrates: generating a worklist that vendor software makes tedious —
variable per-well volumes computed from arbitrary source data.

- Fake a plate-reader/Nanodrop export: a CSV of 96 wells with randomized
  concentrations (e.g. 20-800 ng/uL), some intentionally messy (a few wells
  already below target, one way above range).
- Pure-Python calc (no PyLabRobot needed for this part): `target_conc`,
  `target_vol` -> `sample_vol`, `diluent_vol` per well, with explicit
  handling of edge cases:
  - already at target -> skip
  - below target -> flag "fails QC" instead of a negative diluent volume
  - above capacity -> flag, don't silently clip
- Execute: diluent first into destination plate, then variable per-well
  sample transfer from source. The gantry pulling a *different* volume at
  every well is the visually compelling part — exactly what's tedious to
  encode in a GUI worklist editor and trivial in five lines of pandas.
- **AI-agent beat:** ask Claude Code, live, to "retarget to 50 ng/uL and cap
  diluent at 180 uL" — watch it edit the calc function and rerun in front
  of people. Good opener; most immediately legible win.

---

## 2. Version control + AI diff explanation

**Files:** `examples/vcs_demo/protocol.py` (+ its own git history)

Demonstrates: real diffable history, and an AI agent reading that history
to explain operational impact — something no vendor tool offers.

- `git init`, write a minimal single-channel transfer (fixed volume, no
  error handling), commit ("v1").
- Edit it: add a volume-insufficiency check, switch tip type, add a wash
  step. Commit ("v2").
- Ask the agent: "diff these two commits and explain what changed and why
  it matters operationally." Payoff line — this is exactly what nobody can
  do with HSL/FluentControl's binary/DB-stored methods.
- Make it *behaviorally* visible, not just textual: run v1 against a source
  well that's short on volume (crashes ugly), then run v2 against the same
  starting state (catches it, reports cleanly). Since Replay already
  exists, show both recordings back to back — same starting deck state,
  different outcome, diff on screen explains why.

---

## 3. Debugging / error handling

**File:** `examples/error_handling_demo.py`

Demonstrates: real, specific exceptions vs. vendor software's vague error
text, plus structured logging/notification instead of a silent crash.

- Deliberately underfill a source well relative to what the protocol will
  try to pull (e.g. 3x aspirations of 100 uL from a well with 50 uL left).
  With `enable_tracking=True` on by default in `VisualizerBackend`,
  PyLabRobot raises a real, specific exception.
- Nice direct contrast: show a vendor-style vague error ("invalid well
  offset," "enter a valid tip selection") next to PyLabRobot's actual
  traceback (resource, well, shortfall amount).
- Wrap in try/except that logs structured context (well ID, resource,
  timestamp, shortfall amount) instead of dying silently; optionally
  "notify" (mock Slack-style printed message) — makes the "push/SMS/Slack
  on error" pain point tangible.
- Visual hook: the gantry stops right at the well that failed, so the room
  sees exactly where and why, not just a log line.

---

## 4. LIMS/ELN integration (mock service)

**Files:** `examples/mock_lims/` (small FastAPI + SQLite service)

Demonstrates: the protocol pulling sample data from and pushing results
back to external infrastructure — without needing real LIMS access.

Two options depending on time budget:

- **Simplest:** a `mock_lims.json` file the protocol reads/writes. Shows
  "data comes from somewhere external" but doesn't demonstrate the API
  pattern.
- **Better for the demo:** a ~30-line FastAPI + SQLite service with
  `GET /samples` (returns sample IDs, target concentrations, well
  assignments) and `POST /results` (accepts well-level outcomes). Wire the
  normalization demo (#1) to pull its concentration data from `GET
  /samples` instead of a CSV, and push final volumes/QC flags back via
  `POST /results` on completion.

**Key point to make explicit to the audience:** the protocol code doesn't
know or care that this is a mock — swap the base URL and auth header and
the same code talks to Benchling, LabVantage, or whatever the org actually
runs. Directly answers the gap where neither the LIMS nor the liquid
handler software can version-control the integration code, so it has to
live somewhere else.

---

## 5. Unit testing / CI

**Files:** `tests/test_normalization.py`, `.github/workflows/test.yml`

Demonstrates: a mechanism that structurally can't exist in VENUS or
FluentControl — catching a regression before it ever reaches a run.

This is the one demo that deliberately does **not** use the visualizer —
that's the teaching point.

- `pytest` tests for the pure calculation logic from #1: target-equals-
  current (no dilution), below-target (flagged, not negative), way-above-
  range (exceeds well capacity, should raise). None of this touches
  hardware or even the simulator.
- One tier up: a smoke test that runs the full protocol against the
  simulator backend with tracking on and just asserts it completes without
  raising — a cheap "did we just break something" check.
- A `.github/workflows/test.yml` that runs `uv run pytest` on every push.
  Doesn't need to be fancy — the point is the mechanism exists at all.
- **Best narrative beat:** deliberately reintroduce a bug into the
  normalization calc (drop the below-target guard) and show the CI test
  catching it — red X on the PR — before it would ever have reached a run,
  simulated or otherwise. Closes the loop with #2 and #3: version control
  lets you see the change, tests catch the regression before it executes,
  and the visualizer is what you'd have needed to *notice* the bug the old
  way.

---

## Optional extras (not yet scoped)

Two additional ideas that scored well in earlier research and are cheap to
build on top of what exists, if more slots are needed:

- **Plate randomization/layout design** — generate a randomized/blocked
  plate map (numpy) that avoids edge wells for controls, feed it straight
  into the normalization demo's destination assignments. Fast to build,
  visually distinct (non-trivial well pattern), and a documented,
  underserved gap (mostly R-only tooling currently).
- **Liquid-class-style parameter sweep** — probably skip unless the
  simulator models aspirate/dispense physics; without that it wouldn't
  visually differ from a normal transfer, so it wouldn't earn its slot in a
  visual-first demo.

**Deliberately left out:** computer-vision error detection — needs a camera
feed the simulator doesn't have, and faking it would undercut the
"everything you're seeing is real code" credibility that makes the rest of
this convincing.

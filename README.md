# Hamilton Visualizer

A browser-based isometric visualizer for [PyLabRobot](https://github.com/PyLabRobot/pylabrobot)
Hamilton STAR runs: deck, carriers, tip racks, and plates rendered at their
real coordinates, with the 8-channel pipetting gantry animated live as your
protocol runs (tip pickup, aspirate, dispense, drop tip).

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture and rationale, and
[docs/PLAN.md](docs/PLAN.md) for the phased build plan / status.

Moving plates (iSWAP / CO-RE gripper) is out of scope -- see DESIGN.md
section 4.

## Install

Into your own protocol's environment, straight from GitHub:

```bash
uv add "git+https://github.com/hansonlee2017/hamilton_star_visualizer"
```

or with pip:

```bash
pip install "git+https://github.com/hansonlee2017/hamilton_star_visualizer"
```

That pulls in `hamilton_visualizer` (server, backend wrappers, and the
bundled browser frontend) plus its dependencies. Pin a tag or commit with
`@<ref>` on the end of the URL if you want a fixed version. Requires Python
3.14+.

## Quick start

To run the bundled demos, work from a checkout of this repo (they live in
`examples/`, which isn't part of the installed package). Requires
[`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python examples/demo_protocol.py
```

Then open the printed URL (`http://127.0.0.1:8765` by default) in a browser.
The demo sets up the deck and waits -- check the initial deck/tip/liquid
state looks right, then click **Start Protocol** in the top-left whenever
you're ready; nothing runs before that. No PyLabRobot hardware is involved --
the demo runs against `LiquidHandlerChatterboxBackend`, which just prints
what it's doing.

## Using it in your own protocol

```python
from pylabrobot.liquid_handling import LiquidHandler
from hamilton_visualizer import VisualizerBackend, VisualizerServer

server = VisualizerServer()
await server.start()  # prints the URL to open

real_backend = STARBackend()  # or STARChatterboxBackend() for dry-run testing
lh = LiquidHandler(backend=VisualizerBackend(real_backend, server), deck=deck)
await lh.setup()

# Optional but recommended: block until someone clicks "Start Protocol" in
# the browser, instead of guessing how long setup/connecting will take.
await server.wait_for_start()

... run your protocol as normal ...
```

`VisualizerBackend` wraps any `LiquidHandlerBackend` (real hardware or a
Chatterbox backend) and forwards every call to it unchanged, so this is a
drop-in wrapper -- your protocol logic doesn't change.

**Note:** `VisualizerBackend` turns on PyLabRobot's tip/volume tracking by
default (`enable_tracking=True`), since tip-presence and liquid-volume
visualization are inert without it -- see the class docstring in
[`visualizer_backend.py`](src/hamilton_visualizer/visualizer_backend.py) for
what that changes about your protocol's runtime behavior (it becomes
stricter: mismatched pick-ups/insufficient volume will now raise).

## How it works, briefly

- `VisualizerServer` is a small FastAPI + websocket server that runs inside
  your protocol's own asyncio event loop (no separate process to manage).
- `VisualizerBackend` is a `LiquidHandlerBackend` decorator: it forwards
  every call to a wrapped backend and streams a structured JSON event for
  each one (resource, channel, real coordinates, volume) -- see
  [`docs/DESIGN.md`](docs/DESIGN.md) for why this is more reliable than
  parsing Chatterbox's printed/logged output.
- The frontend is a [TypeScript](https://www.typescriptlang.org/) +
  [Three.js](https://threejs.org/) app (source in `frontend/`, built with
  [Vite](https://vite.dev/)), rendering everything as simple boxes from an
  orthographic camera set to a fixed isometric angle. Its production build
  is committed to `src/hamilton_visualizer/frontend/` and served straight
  from the installed package, so running the visualizer never needs Node.

Live mode only: open the browser *before* running your protocol to watch it
happen. If you missed it (or just want to watch again), the **Replay**
button in the top-left re-sends everything the server has recorded so far,
paced to approximate the original timing. This is in-memory only -- it does
not survive restarting the Python process (see DESIGN.md's "Future /
stretch" section for a durable, capture-to-file version).

## Project layout

```
docs/                              design doc + phased plan
src/hamilton_visualizer/           server.py, visualizer_backend.py, scene.py, events.py
src/hamilton_visualizer/frontend/  committed Vite build output (index.html + assets/);
                                    packaged with the wheel and served by the server
frontend/                          the frontend's TypeScript source (Vite project) --
                                    src/*.ts, test/*.test.ts; dev only, not in the wheel
examples/demo_protocol.py          runnable, hardware-free demo
examples/cherry_pick_demo.py       cherry-picking demo: an ordinary lh.dispense() onto a
                                    scattered smiley-face pattern, animated column-by-column
                                    the way a real Hamilton STAR's shared-x gantry actually
                                    would -- the visualizer works this out on its own
examples/picogreen_demo.py         PicoGreen dsDNA quantitation demo: an 8-point 2-fold
                                    serial dilution standard curve (single channel, tube ->
                                    plate and well -> well), then 8-channel sample/standard
                                    and PicoGreen-reagent transfers into an assay plate --
                                    exercises a reservoir, Eppendorf tubes, and a second
                                    plate type alongside the usual carriers/tip racks
examples/pixel_art_demo.py         pixel-art demo: prints any 5-character word (A-Z0-9,
                                    entered in the HUD) across 5 x 96-well Corning plates in
                                    portrait orientation via a real Hamilton multi-dispense
                                    pattern (aspirate 300uL once, dispense back out in several
                                    equal steps, returning each channel's exact leftover to
                                    the shared reservoir with empty=True instead of discarding
                                    tips) -- all 36 characters' bitmaps are pre-generated, not
                                    drawn at runtime
examples/custom_labware.py         a real custom Plate definition (a Cellvis 384-well
                                    glass-bottom plate) not yet in PyLabRobot's own catalog,
                                    built the same way its own catalog entries are
examples/normalization_demo.py     normalization-protocol demo: dilutes a 96-well plate's
                                    samples (read from a CSV) to one target concentration and
                                    final volume (both HUD inputs) -- the actual decision
                                    logic (how much sample/diluent, in what order, or whether
                                    to flag/skip a well) lives in
                                    src/hamilton_visualizer/normalization.py, a small
                                    PyLabRobot-free module unit-tested in tests/
examples/thermocycler_demo.py      Inheco on-deck thermal cycler demo: opens the lid to load
                                    a plate, closes it, runs a real 3-stage/32-cycle PCR
                                    protocol (a fixed-duration shimmer stands in for real
                                    cycling time), opens it again -- exercises
                                    VisualizerThermocyclerBackend on its own, no liquid
                                    handling
examples/core96_demo.py            CO-RE 96 head demo: picks up all 96 tips from a full rack
                                    at once, aspirates from every well of a source plate
                                    simultaneously, dispenses into a destination plate, drops
                                    tips back onto the rack -- exercises the 96-head
                                    (pick_up_tips96/aspirate96/dispense96/drop_tips96) on its
                                    own, independent of and coexisting with the 8-channel side
```

## Development

Running a demo (no Node needed -- it serves the committed frontend build):

```bash
uv run python examples/demo_protocol.py
```

### Working on the frontend

The frontend source is a Vite + TypeScript project in [`frontend/`](frontend/)
(see its own [README](frontend/README.md)). None of this is needed just to
*run* the visualizer -- the built bundle is committed and served from the
package -- only to change the UI.

**One-time setup** (needs [Node](https://nodejs.org/) 20.19+ / 22.12+, per
Vite 7; installs into `frontend/node_modules/`, which is git-ignored):

```bash
npm --prefix frontend install
```

For a live-reloading loop, run the demo (for the websocket data) and Vite
(for the UI) side by side:

```bash
uv run python examples/demo_protocol.py    # terminal 1 -- the protocol + server on :8765
npm --prefix frontend run dev              # terminal 2 -- open the printed :5173 URL
```

Vite proxies `/ws` through to the running protocol, so edits to
`frontend/src/*.ts` hot-reload against live data. When you're done, rebuild
the committed bundle that the package actually ships and serves, and commit
the regenerated `src/hamilton_visualizer/frontend/`:

```bash
npm --prefix frontend run build
```

Open the browser console and inspect `window.__viz` (scene/camera/gantry
objects, plus `.channels` for the gantry's own animation state) or
`window.__lastStateMessages` (captured tip/volume state events) for
debugging.

For a timestamped trace of what the animation system is actually doing
(op events received, resources attaching/detaching, gantry waits
computed, thermocycler animations starting/finishing), turn on
`frontend/src/log.ts`'s optional leveled logging -- silent by default, same
idea as Python's `logging` module. Either run
`window.__log.setLevel("debug")` in the console, or open the page with
`?logLevel=debug` in the URL; `"info"` gives a shorter high-level trace
(one line per op, plus animation start/finish) without the finer
per-attach/per-wait detail. Levels: `debug` < `info` < `warn` < `error` <
`off`.

Unit tests -- Python side (`src/hamilton_visualizer/normalization.py`'s
pure decision logic, no PyLabRobot/browser involved):

```bash
uv run pytest
```

Frontend side (`frontend/src/gantry-planning.ts`'s motion-planning math and
a couple of other pure-logic modules -- no browser, via Vitest; needs the
one-time `npm --prefix frontend install` above):

```bash
npm --prefix frontend test
```

Type-check the whole frontend without emitting:

```bash
npm --prefix frontend run typecheck
```

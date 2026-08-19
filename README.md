# Hamilton Visualizer

A browser-based isometric visualizer for [PyLabRobot](https://github.com/PyLabRobot/pylabrobot)
Hamilton STAR runs: deck, carriers, tip racks, and plates rendered at their
real coordinates, with the 8-channel pipetting gantry animated live as your
protocol runs (tip pickup, aspirate, dispense, drop tip).

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture and rationale, and
[docs/PLAN.md](docs/PLAN.md) for the phased build plan / status.

Moving plates (iSWAP / CO-RE gripper) is out of scope -- see DESIGN.md
section 4.

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/).

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
- The frontend (`frontend/main.js`) is vanilla JS + [Three.js](https://threejs.org/)
  (vendored locally, no build step), rendering everything as simple boxes
  from an orthographic camera set to a fixed isometric angle.

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
frontend/                          index.html, main.js (also plans real gantry motion --
                                    see planGantryPasses()), vendor/ (three.js, OrbitControls)
examples/demo_protocol.py          runnable, hardware-free demo
examples/cherry_pick_demo.py       cherry-picking demo: an ordinary lh.dispense() onto a
                                    scattered smiley-face pattern, animated column-by-column
                                    the way a real Hamilton STAR's shared-x gantry actually
                                    would -- the visualizer works this out on its own
```

## Development

```bash
uv run python examples/demo_protocol.py
```

Open the browser console and inspect `window.__viz` (scene/camera/gantry
objects) or `window.__lastStateMessages` (captured tip/volume state events)
for debugging.

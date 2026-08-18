# Hamilton STAR Visualizer — Design Doc

Status: **approved for implementation** (Phase 0 not yet started)
Last updated: 2026-08-18

## 1. Objective

A browser-based visualizer for Hamilton STAR liquid-handling runs driven by
[PyLabRobot](https://github.com/PyLabRobot/pylabrobot). It renders the deck
(carriers, tip racks, plates, trash) in a simple isometric projection using
the actual coordinates PyLabRobot already knows about, and — most
importantly — animates the 8-channel pipetting gantry: tip pickup, aspirate,
dispense, drop tip.

Moving plates (iSWAP / CO-RE gripper) is explicitly **out of scope**.

## 2. Research findings (grounded in PyLabRobot source, Aug 2026)

These findings came from reading the actual current source (PyLabRobot has
moved a lot of code into a `pylabrobot.legacy` namespace recently, so this
was worth checking rather than trusting training data):

1. **"Chatterbox output" is two very different things.**
   `STARChatterboxBackend` overrides the low-level command sender so it logs
   instead of talking to hardware. For channel/gantry Y/Z jogs it logs clean,
   human-readable lines (e.g. `"moving channel %s to y: %s"`,
   `"positioning channels in z: %s"`). But `pick_up_tips`, `aspirate`,
   `dispense`, `drop_tips` never produce a human-readable log line — they get
   compiled into raw Hamilton STAR firmware command strings (proprietary
   ASCII protocol, deep in a ~15k-line backend file), and *that* is what
   gets logged. Regex-parsing that text for "which well, which channel, what
   volume" is not practically feasible.

2. **Real coordinates are already available on every `Resource`.**
   `Resource.get_absolute_location()` and `Resource.serialize()` expose real
   `size_x/size_y/size_z` and position/rotation for carriers, plates, tip
   racks, wells, and tip spots. PyLabRobot's own 2D Visualizer already walks
   the deck tree (`_serialize_resource_tree`) and ships this to the browser
   — we reuse this approach directly for accurate carrier/plate boxes.

3. **The existing 2D Visualizer never animates the gantry.** It is a purely
   passive listener on `Resource.register_state_update_callback`
   (tip-present / liquid-volume state only). It has no concept of channel
   X/Y/Z position or motion. Gantry animation is new work, not something to
   extract from the existing tool.

4. **The clean interception point is `LiquidHandler.backend`.**
   `LiquidHandler.pick_up_tips` / `aspirate` / `dispense` / `drop_tips` build
   fully structured operation objects (resource reference + offset +
   channel + tip/volume) before calling `self.backend.pick_up_tips(...)`
   etc. Wrapping that backend interface — the same pattern
   `STARChatterboxBackend` itself uses, a decorator around a real backend —
   gets us exact, structured, per-channel events with no text parsing, and
   it works identically against real hardware or `STARChatterboxBackend`.

## 3. Architecture

```
 PyLabRobot script
   LiquidHandler
     └─ VisualizerBackend (wraps real backend or STARChatterboxBackend)
          ├─ forwards every call unchanged to the wrapped backend
          └─ emits structured JSON events over a websocket
                 - one-time deck scene graph (on connect)
                 - resource state deltas (tip present, well volume)
                 - operation events (pick_up_tips/aspirate/dispense/drop_tips)
                          │
                          ▼
                 FastAPI + uvicorn server (static files + /ws)
                          │
                          ▼
                 Browser frontend (Three.js, orthographic/isometric camera)
```

### VisualizerBackend

A thin `LiquidHandlerBackend` decorator, structurally the same idea as
`STARChatterboxBackend`, wrapping the *real* backend (or Chatterbox, for
dev/testing without hardware). Every call passes through unchanged to the
wrapped backend, then a structured event is emitted:

- op type, channel(s) involved
- resource name + absolute xyz (via `resource.get_absolute_location()`)
- volume / tip-type info where relevant

Passive state (tip present, well liquid volume) is **not** duplicated here —
it reuses PyLabRobot's existing `register_state_update_callback` mechanism,
same as the built-in Visualizer. We are extending that tool, not replacing
it.

### Server

Single Python process: FastAPI + `uvicorn`, one websocket endpoint. Serves
the static frontend and streams the three event kinds above.

### Frontend

Static HTML/JS. Three.js, vendored locally (no JS build step), with an
**orthographic camera** angled to a standard isometric view. Deck, carriers,
plates, tip racks, wells, and tip spots render as simple `BoxGeometry` at
their real coordinates. Three.js gives correct depth-sorting/occlusion for
free, so "simple bounding boxes, no complicated projections" holds even
though it's WebGL under the hood.

### Gantry model

Single shared **X** position for the pipetting arm, independent **Y/Z** per
channel — this matches real STAR kinematics (also why the STAR backend logs
per-channel Y and Z, but a single arm X).

We do not have true firmware motion timing available (see finding #1), so
animation is **synthesized client-side**: approach → descend → actuate →
retract → travel, as eased keyframes between operation events. This is a
deliberate simplification.

## 4. Scope

**In (v1 / MVP):**
- Static isometric scene from a real deck: carriers, tip racks, plates,
  trash, wells/tip-spots, all at true coordinates.
- Live tip-presence and well-liquid-volume reflection.
- 8-channel gantry: arm X + per-channel Y/Z, animated for pick-up-tips,
  drop-tips, aspirate, dispense.
- Basic orbit/zoom camera, hover tooltips, small event-log side panel for
  correlating the 3D view with actual backend calls.
- Live mode only: run a protocol script with `VisualizerBackend` wrapping
  `STARChatterboxBackend` (dev) or a real backend, open the browser page,
  watch it live.

**Out (v1):**
- Moving plates (iSWAP / CO-RE gripper).
- 96-head, Hamilton Vantage support.
- Log-file replay/scrubbing (the event schema is designed to be
  file-dumpable, so this is a cheap add later).
- True firmware-accurate motion timing/acceleration.

## 5. Tech stack

- **Python packaging:** `uv` (src layout, standalone project for personal
  use to start).
- **Server:** FastAPI, `uvicorn`, `websockets`.
- **PyLabRobot:** dev/testing against `STARChatterboxBackend` +
  `STARLetDeck` (no hardware required); same code path works against a real
  `STARBackend`.
- **Frontend:** vanilla JS + Three.js (vendored `three.module.js`, no
  bundler).
- **Version control:** git.

## 6. Repo structure

```
HamiltonVisualizer/
├── docs/
│   ├── DESIGN.md          (this file)
│   └── PLAN.md            (phased task breakdown)
├── src/
│   └── hamilton_visualizer/
│       ├── server.py            # FastAPI app, websocket endpoint
│       ├── visualizer_backend.py  # LiquidHandlerBackend decorator
│       └── scene.py             # resource-tree -> scene graph serialization
├── frontend/
│   ├── index.html
│   ├── main.js
│   └── vendor/
│       └── three.module.js
├── examples/
│   └── demo_protocol.py   # STARChatterboxBackend + STARLetDeck demo run
├── pyproject.toml
└── README.md
```

## 7. Future / stretch (explicitly deferred)

- Log-file capture + replay/scrubbing UI.
- 96-head visualization.
- iSWAP / CO-RE gripper + plate-move animation.
- Hamilton Vantage support.
- Firmware-accurate motion timing (would require decoding low-level STAR
  protocol, or a different data source than is currently practical).

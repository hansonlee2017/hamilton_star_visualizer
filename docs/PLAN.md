# Implementation Plan

Companion to [DESIGN.md](DESIGN.md). Each phase should end in something
runnable/demo-able before moving to the next. Check items off as they land.

## Phase 0 — Repo & project scaffolding

Goal: empty-but-working skeleton, nothing project-specific rendered yet.

- [ ] `git init`; `.gitignore` (Python, `uv`, node/vendor artifacts, `.venv`)
- [ ] `uv init` (src layout) at repo root
- [ ] Add deps: `pylabrobot`, `fastapi`, `uvicorn[standard]`, `websockets`
- [ ] `src/hamilton_visualizer/server.py`: minimal FastAPI app serving a
      static "hello" page from `frontend/`
- [ ] `frontend/index.html` + `frontend/main.js` placeholder page
- [ ] Vendor `three.module.js` into `frontend/vendor/` (pin a version, note
      it in README)
- [ ] `uv run` entry point / script to launch the server
- [ ] README: how to install (`uv sync`) and run
- [ ] Smoke test: `uv run <entry point>` → open browser → see placeholder
      page
- [ ] Initial commit

## Phase 1 — Static isometric deck scene

Goal: point the tool at a real PyLabRobot deck and see accurate, static
bounding boxes for carriers/plates/tip racks/wells in isometric view. No
live events yet.

- [ ] `examples/demo_protocol.py`: build a `STARLetDeck` (or similar) with a
      representative set of carriers, tip racks, and plates — no protocol
      logic yet, just deck construction
- [ ] `src/hamilton_visualizer/scene.py`: walk the deck's resource tree,
      produce a JSON-serializable scene graph (name, type/category, absolute
      xyz, size_x/y/z, rotation) — adapt PyLabRobot's own
      `_serialize_resource_tree` approach
- [ ] Websocket endpoint on the server: on connect, send the one-time scene
      graph for a deck passed in by the caller
- [ ] Frontend: Three.js scene setup — orthographic camera at a fixed
      isometric angle, basic lighting, ground/deck plane
- [ ] Frontend: consume the scene graph JSON, instantiate `BoxGeometry` per
      resource at its real coordinates/size; distinct materials/colors per
      resource category (carrier / tip rack / plate / well / tip spot /
      trash)
- [ ] Camera controls: orbit + zoom (mouse)
- [ ] Hover tooltip showing resource name/type
- [ ] Demo: run `demo_protocol.py` → open browser → confirm the rendered
      layout matches the deck definition (spot-check a few known
      coordinates)

## Phase 2 — Live resource state (tips, liquid)

Goal: tip-present and well-liquid-volume changes on the deck show up live
in the browser, using PyLabRobot's existing state-callback mechanism.

- [ ] Hook `register_state_update_callback` on deck resources (reuse
      PyLabRobot Visualizer's pattern) to detect tip-spot and well state
      changes
- [ ] Server: forward state-delta events over the same websocket
- [ ] Frontend: update tip-spot material (tip present/absent) and well
      fill-level/color (empty → volume-proportional fill) on incoming
      deltas
- [ ] Extend `demo_protocol.py` with a simple script that manually flips
      tip/volume state (no gantry motion yet) to exercise this end-to-end
- [ ] Demo: run script → watch tip/well states update live in the browser

## Phase 3 — Gantry animation (the priority feature)

Goal: pick_up_tips / drop_tips / aspirate / dispense visibly animate the
8-channel head on the correct channel(s), at the correct deck position.

- [ ] `src/hamilton_visualizer/visualizer_backend.py`: `VisualizerBackend`
      class implementing the `LiquidHandlerBackend` interface, wrapping a
      supplied backend (e.g. `STARChatterboxBackend`)
  - [ ] Forward `setup`, `pick_up_tips`, `drop_tips`, `aspirate`,
        `dispense`, and other required interface methods unchanged to the
        wrapped backend
  - [ ] For each of pick_up_tips/drop_tips/aspirate/dispense: build a
        structured event (channel index, resource name + absolute xyz,
        volume/tip info) and push it to the server
- [ ] Server: relay operation events over the websocket (separate event
      type from scene graph / state deltas)
- [ ] Define the gantry model client-side: single arm X, per-channel Y/Z,
      per-channel tip-present flag
- [ ] Frontend: render the 8-channel head as a small group of channel
      glyphs above the deck plane
- [ ] Frontend: synthesized keyframe animation per operation event
      (approach → descend → actuate → retract → travel), eased tweening
      between waypoints
- [ ] Tip glyph appears/disappears on the correct channel on pickup/drop;
      brief color pulse on aspirate/dispense
- [ ] Rewrite `demo_protocol.py` into a real (short) protocol: pick up
      tips, aspirate from a plate, dispense to another plate, drop tips —
      run it through `LiquidHandler` + `VisualizerBackend` +
      `STARChatterboxBackend`
- [ ] Demo: run the protocol → watch the gantry animate each step in the
      correct location

## Phase 4 — Polish

Goal: pleasant to actually use day-to-day.

- [ ] Event-log side panel: scrolling list of recent operations, useful for
      correlating 3D view with what the script is doing
- [ ] Color legend (resource categories, tip/liquid states)
- [ ] Connection-status indicator (connected/disconnected/reconnecting)
- [ ] Basic reconnect handling if the server restarts mid-run
- [ ] README pass: how to plug `VisualizerBackend` into your own protocol
      script, screenshots/GIF
- [ ] Tag a v1

## Stretch / explicitly deferred (not v1)

- [ ] Event capture-to-file + offline replay/scrubbing UI
- [ ] 96-head visualization
- [ ] iSWAP / CO-RE gripper + plate-move animation
- [ ] Hamilton Vantage support
- [ ] Firmware-accurate motion timing

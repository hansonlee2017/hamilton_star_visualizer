# Implementation Plan

Companion to [DESIGN.md](DESIGN.md). Each phase should end in something
runnable/demo-able before moving to the next. Check items off as they land.

**Status (2026-08-18): Phases 0-3 built and verified end-to-end (deck scene,
live tip/volume state, gantry animation all confirmed working against the
bundled demo protocol, including a real bug found and fixed along the way --
see the note under Phase 1). Phase 4 mostly landed opportunistically while
building the others. This is a first pass for review, not a tagged release.**

## Phase 0 — Repo & project scaffolding

Goal: empty-but-working skeleton, nothing project-specific rendered yet.

- [x] `git init`; `.gitignore` (Python, `uv`, node/vendor artifacts, `.venv`)
- [x] `uv init` (src layout) at repo root
- [x] Add deps: `pylabrobot`, `fastapi`, `uvicorn[standard]`, `websockets`
- [x] `src/hamilton_visualizer/server.py`: minimal FastAPI app serving a
      static "hello" page from `frontend/`
- [x] `frontend/index.html` + `frontend/main.js` placeholder page
- [x] Vendor `three.module.js` into `frontend/vendor/` (pinned to 0.185.1,
      noted in DESIGN.md; `OrbitControls.js` vendored alongside it)
- [x] `uv run` entry point / script to launch the server (`hamilton-visualizer`
      points at usage instructions; the actual launcher is
      `examples/demo_protocol.py`, see Phase 1 note)
- [x] README: how to install (`uv sync`) and run
- [x] Smoke test: ran the demo end-to-end, confirmed the page loads and the
      websocket connects
- [x] Initial commit (docs); full first-pass implementation to be committed
      after this review

## Phase 1 — Static isometric deck scene

Goal: point the tool at a real PyLabRobot deck and see accurate, static
bounding boxes for carriers/plates/tip racks/wells in isometric view. No
live events yet.

- [x] `examples/demo_protocol.py`: build a `STARLetDeck` with a tip carrier
      and plate carrier — later extended in Phase 3 into the full protocol
- [x] `src/hamilton_visualizer/scene.py`: turned out to be a thin wrapper —
      `Resource.serialize()` already recurses the whole tree with
      parent-relative location/rotation/size, so there was no need to
      reimplement `_serialize_resource_tree`
- [x] Websocket endpoint on the server: sends the cached scene graph to
      every newly-connecting client
- [x] Frontend: Three.js scene setup — orthographic camera at a fixed
      isometric angle, basic lighting
- [x] Frontend: consume the scene graph JSON, instantiate `BoxGeometry` per
      resource at its real coordinates/size, mirroring the PLR parent-child
      hierarchy with nested Three.js groups; distinct colors per category
- [x] Camera controls: OrbitControls (orbit + zoom via mouse)
- [x] Hover tooltip showing resource name/type
- [x] Demo: ran `demo_protocol.py`, confirmed the rendered layout in a real
      browser via automated screenshots

  **Bug found and fixed during verification:** a deck's own `size_z`
  reflects the whole instrument housing (~900mm for a real STAR), not a
  "surface" — rendering it literally as a solid box made the deck a giant
  block that also threw off camera framing, and the same problem hid
  plates/tip-racks inside their carrier's box (carrier `size_z` is the full
  rail envelope, not the carrier's own thickness). Fixed by drawing
  deck/carrier categories as a thin platform sitting below their own origin,
  and by framing the camera on the actual built geometry's bounding box
  instead of trusting any one resource's declared size. See `main.js`,
  `THIN_ENVELOPE_CATEGORIES`.

## Phase 2 — Live resource state (tips, liquid)

Goal: tip-present and well-liquid-volume changes on the deck show up live
in the browser, using PyLabRobot's existing state-callback mechanism.

- [x] Hook `register_state_update_callback` recursively in
      `VisualizerBackend.setup()`
- [x] Server: forward state-delta events (`{"type": "state", ...}`) over the
      same websocket
- [x] Frontend: update tip-spot color (present/absent) and well fill color
      (empty → volume-proportional) on incoming deltas
- [x] Demo: pre-fill source wells with volume and exercise pick-up/aspirate/
      dispense/drop through the full protocol
- [x] Demo: confirmed live in a real browser — captured the full state
      sequence for a well (200 → pending 150 → committed 150 µL) and a tip
      spot (present → null → present) via the browser console

  **Bug found and fixed during verification:** PyLabRobot's tip and volume
  trackers are **disabled by default, process-wide**
  (`does_tip_tracking()` / `does_volume_tracking()` both start `False`) —
  without enabling them, resource state never changes and nothing broadcasts,
  regardless of how correct the callback wiring is. `VisualizerBackend` now
  turns both on in `setup()` by default (`enable_tracking=True`, can be
  disabled), documented in its docstring since it also makes PyLabRobot
  itself stricter (raises on mismatched pick-ups / insufficient volume).

## Phase 3 — Gantry animation (the priority feature)

Goal: pick_up_tips / drop_tips / aspirate / dispense visibly animate the
8-channel head on the correct channel(s), at the correct deck position.

- [x] `src/hamilton_visualizer/visualizer_backend.py`: `VisualizerBackend`
      implementing the full `LiquidHandlerBackend` interface, wrapping a
      supplied backend
  - [x] Forwards every abstract + optional interface method to the wrapped
        backend (pipetting, 96-head, resource-move, manual channel jog)
  - [x] pick_up_tips/drop_tips/aspirate/dispense build a structured event
        (channel index, resource name, absolute xyz via
        `get_absolute_location`, volume/tip info) and push it to the server;
        96-head and resource-move calls emit a lighter event for the log
        panel (not animated in v1, as scoped)
- [x] Server: relays `{"type": "op", ...}` events over the websocket
- [x] Gantry model client-side: single arm X, independent per-channel Y/Z,
      per-channel tip-present flag (see DESIGN.md for the simplification —
      channels are not constrained to a shared arm X in v1)
- [x] Frontend: 8-channel head rendered as small cylinder+cone glyphs
- [x] Frontend: synthesized keyframe animation per op (rise → travel →
      descend → hold → retract), eased tweening, queued per channel
- [x] Tip glyph appears/disappears on the correct channel on pickup/drop;
      brief color pulse on aspirate/dispense (channel + resource)
- [x] Rewrote `demo_protocol.py` into a real protocol: 3 columns of
      pick-up/aspirate/dispense/drop-tips through
      `LiquidHandlerChatterboxBackend`, paced with short sleeps so it's
      watchable
- [x] Demo: confirmed via the browser — event log shows real per-channel/
      volume detail, and channel objects were verified (via console) to move
      through the correct waypoints and settle at the right rest position

## Phase 4 — Polish

Goal: pleasant to actually use day-to-day.

- [x] Event-log side panel: scrolling list of recent operations (also logs
      96-head/resource-move/manual-jog events not otherwise animated)
- [x] Color legend (resource categories, tip/liquid states, gantry channel)
- [x] Connection-status indicator (connected/disconnected)
- [x] Basic reconnect handling: auto-retry every 1.5s on disconnect
- [x] README pass: install/run instructions, how to plug `VisualizerBackend`
      into your own protocol script, brief architecture summary
- [ ] Screenshots/GIF in README
- [ ] Tag a v1 (holding off until this first pass is reviewed)

## Stretch / explicitly deferred (not v1)

- [ ] Event capture-to-file + offline replay/scrubbing UI
- [ ] 96-head visualization
- [ ] iSWAP / CO-RE gripper + plate-move animation
- [ ] Hamilton Vantage support
- [ ] Firmware-accurate motion timing
- [ ] Sync initial tip/volume state on connect (currently only *changes*
      after connect are reflected — a rack that starts pre-filled with tips
      shows the default "empty" color until the first pick-up touches it)

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
  rail envelope, not the carrier's own thickness). Fixed by drawing the deck
  as a thin platform sitting below its own origin, and by framing the camera
  on the actual built geometry's bounding box instead of trusting any one
  resource's declared size. See `main.js`.

  **Refined further (2026-08-18 review):** a fixed-thickness platform for
  carriers left plates/tip-racks floating with a visible gap above their
  carrier. Carriers are now drawn as a solid shaft from their own base up to
  wherever their payload's holder (`PlateHolder`/`ResourceHolder` child)
  actually sits, so the payload rests flush on top instead of floating or
  being buried — see `CARRIER_CATEGORIES` in `main.js`.

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

  **Correctness fix (2026-08-18 review):** the tip pick-up/drop-off z target
  used `resource_point()`'s generic top-anchor on the `TipSpot`, but a
  `TipSpot` is a zero-height placement marker (`size_z=0` by construction)
  whose raw location is calibrated (per tip-rack `dz`) to land near the
  tip's sharp point, not where a channel actually grabs it. Added
  `tip_grab_point()`, mirroring `STARBackend.pick_up_tips`'s own
  `end_tip_pick_up_process` math (`spot_z + tip.total_tip_length -
  tip.fitting_depth`), and `channel_ops_event` now uses it for
  pick_up_tips/drop_tips against a `TipSpot` specifically (drop-to-Trash
  still uses the generic top-anchor). See `events.py`.

## Phase 4 — Polish

Goal: pleasant to actually use day-to-day.

- [x] Event-log side panel: scrolling list of recent operations (also logs
      96-head/resource-move/manual-jog events not otherwise animated)
- [x] Color legend (resource categories, tip/liquid states, gantry channel)
- [x] Connection-status indicator (connected/disconnected)
- [x] Basic reconnect handling: auto-retry every 1.5s on disconnect
- [x] README pass: install/run instructions, how to plug `VisualizerBackend`
      into your own protocol script, brief architecture summary
- [x] Replay: `VisualizerServer` records every broadcast event (in memory,
      capped at `MAX_EVENT_HISTORY`) with a timestamp; a "Replay" button in
      the HUD asks the server to re-send its whole history to just that
      client, paced to approximate the original timing (capped per-gap at
      `MAX_REPLAY_GAP` so a real multi-minute pause doesn't replay literally).
      Solves "I opened the browser too late" and "let me watch that again"
      without needing a full capture-to-file/scrubbing UI. **Caveat:**
      in-memory only — restarting the Python process loses the history, so
      this doesn't survive a script restart (see the stretch item below).

  **Bug found and fixed while building this:** `ws.onopen`/`ws.onclose`
  didn't check whether their socket was still the active one, so a stale
  connection attempt's `onclose` firing after a newer connection's `onopen`
  had already succeeded could re-disable the Replay button (and status
  text) despite genuinely being connected. Both handlers now bail out early
  if `ws !== currentWs`. Also deduped a cosmetic double scene-load on
  replay (the explicitly-resent current scene, plus its own copy at the
  head of history) — `replay()` now strips a leading run of `scene` events
  from history after sending the current one explicitly.
- [ ] Screenshots/GIF in README
- [ ] Tag a v1 (holding off until this first pass is reviewed)

## Review round 2 (2026-08-18)

User feedback after the first pass: no visible tip geometry, aspirate/
dispense visually entering the plate rather than using a real channel z,
switch the demo from `drop_tips` to `discard_tips`, and an aspirate/dispense
"flow" animation.

- [x] **Tip geometry.** Tips render as a small inverted 4-sided pyramid
      (`THREE.ConeGeometry(r, h, 4)`) — one nested in each `TipSpot`
      (visibility toggled by tip-presence state, replacing the old
      color-swap-on-a-near-zero-height-box approach) and one on each gantry
      channel (already existed as a 10-segment cone; switched to 4 segments
      to match). **Bug found while wiring this up:** a `TipSpot`'s
      `location.z` isn't just zero-height (see the Phase 3 note above) --
      it's also displaced by a large negative `dz` each tip-rack factory
      bakes in (e.g. -83.5mm) for firmware pick-up-depth math. Anchoring the
      pyramid to the spot's own local origin buried it ~100mm below the
      visible rack. Fixed by threading the parent rack's height down through
      `buildResourceObject()`'s recursion and using it to cancel that offset
      out, so the pyramid hangs from just under the rack's visible top
      surface instead. Also added `VisualizerBackend._broadcast_initial_state()`
      so a rack that starts pre-filled with tips (the common case) shows
      them immediately instead of only after each spot's first pick-up --
      this closes a gap noted in the first review round, and also means a
      fresh replay starts from the correct initial state.
- [x] **`discard_tips` instead of `drop_tips`.** Demo protocol switched.
      No backend/event code changes needed: `LiquidHandler.discard_tips()`
      is a convenience wrapper that still calls `self.backend.drop_tips(...)`
      under the hood (targeting the deck's trash), so `VisualizerBackend`'s
      interception point already covers it — the event log still labels it
      `drop_tips` (that's the literal backend call), but the target resource
      correctly shows as `trash` instead of a tip-rack spot.
- [x] **Aspirate/dispense channel z.** Added `events.py`'s
      `liquid_surface_point()`, mirroring `STARBackend.aspirate`'s own
      `well_bottom + material_z_thickness + liquid_height` formula. Respects
      an explicit `op.liquid_height` when the protocol sets one; otherwise
      derives it from the well's *currently tracked* volume via
      `compute_height_from_volume()`, falling back to the well bottom if the
      resource doesn't support that. Numerically verified against a real
      well (200µL in a 360µL well: old top-anchor z=196.82 at the opening →
      new z=192.84, correctly below the surface and above the 186.15 bottom).
      Known simplification: because `LiquidHandler` queues the tracker
      change and only commits it *after* `backend.aspirate`/`dispense`
      returns, reading `tracker.volume` at broadcast time ends up reading
      the *pre-operation* level for both ops (not post-aspirate/dispense) --
      documented in the function's docstring, not exact but a reasonable
      "where the surface was when the tip arrived" approximation.
- [x] **Aspirate/dispense flow animation.** `Channel.flowPulse(direction)`
      in `main.js`: a small canvas-generated repeating-stripe gradient
      texture (`createFlowTexture()`), applied as the tip pyramid's `map`
      and scrolled via `texture.offset.y` for ~550ms -- up for aspirate,
      down for dispense -- then removed to restore the plain tip color.
      Each channel owns its own texture *clone* so two channels animating
      concurrently (the common case -- all 8 fire together) don't fight
      over a shared offset. Verified live: polled a channel's tip material
      mid-replay and confirmed `material.map` was set with a real,
      advancing `offset.y`.

  **Bug found and fixed while verifying this:** the new
  `_broadcast_initial_state()` (see above) walks every resource, including
  `Trash`, whose `max_volume` is `float("inf")` by design. Python's
  `json.dumps` emits that as the bare token `Infinity`, which is *not*
  valid JSON -- the browser's `JSON.parse` threw a `SyntaxError` on every
  message containing it, silently breaking state sync from that point on.
  Added `server.py`'s `_json_safe()`, applied to every outgoing message in
  `_send()`, which recursively replaces non-finite floats (`inf`/`-inf`/
  `nan`) with `null`.

## Stretch / explicitly deferred (not v1)

- [ ] Event capture-to-file (durable, survives a process restart) +
      scrubbing/seek UI — in-memory replay from Phase 4 covers the common
      "I missed it" / "watch that again" case within one run
- [ ] 96-head visualization
- [ ] iSWAP / CO-RE gripper + plate-move animation
- [ ] Hamilton Vantage support
- [ ] Firmware-accurate motion timing

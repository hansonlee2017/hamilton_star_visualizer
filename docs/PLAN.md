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

## Review round 3 (2026-08-18)

User feedback after round 2: tips only visible in the first of 3 loop
iterations and shaped like "droplets" not pyramids (and no visible flow
animation, possibly downstream of that); the cylindrical channel body
visibly entering wells instead of just the tip; discarded channels
visually merging into one object instead of staying 9mm apart; a request
for a slower playback option to review animations more closely.

- [x] **Tip shape.** Root cause: `THREE.ConeGeometry` points its apex
      toward +Y by default (an upright cone/party-hat), and nothing was
      flipping it -- so every tip pyramid, in the rack and on the channel,
      was apex-up/base-down, the opposite of an inverted pyramid, which
      read as a "droplet" at low resolution. Added `rotation.x = Math.PI`
      to both. Also bumped the channel's carried-tip size
      (`CHANNEL_TIP_RADIUS`/`CHANNEL_TIP_HEIGHT`) -- see next item for why.
- [x] **Body entering wells / "only first iteration."** Both traced to the
      same design gap: `animateChannelOp()` was sending the *group origin*
      (where body meets tip) to `entry.z` (the server's computed target for
      the tip's *apex*) with no compensation for the tip's own rendered
      length -- so the body's bottom face ended up sitting right at the
      target depth instead of comfortably above it, and the tip's apex
      overshot *below* the target by half the tip's height. Fixed by
      offsetting the descend/hold target by `CHANNEL_TIP_HEIGHT`
      (`targetZ = entry.z + CHANNEL_TIP_HEIGHT`), so the apex lands exactly
      on target and the body clears it. Verified live for a tip pick-up:
      apex at world z=218.55 (matches the server's `tip_grab_point` target
      exactly), body bottom at 253.75 -- 18.8mm clear of the 234.95mm rack
      surface.

      The "only saw tips in the first iteration" symptom was a *separate*
      bug in the same area: `onArrive` (which flips tip visibility and
      fires the flow animation) was scheduled via `setTimeout(fn, fixedDelay)`
      measured from *event arrival*, not from when the animation actually
      reached that point in the (per-channel) queue. Since events arrive
      faster (~0.5s apart) than an op takes to animate (~1.6s), the queue
      backs up more with every iteration, so the fixed-delay timer drifts
      further out of sync with the visual position each time -- by
      iteration 2-3 it could fire while the channel was still elsewhere.
      Fixed by giving `Channel.enqueue()` an optional `onComplete` that
      fires exactly when *that* waypoint's tween finishes, and passing
      `onArrive` as the descend leg's `onComplete` instead of a timer. This
      also fixes the flow animation's timing, since it's triggered from the
      same callback.
- [x] **Channels merging together on discard.** Root cause: none of
      `events.py`'s point functions ever applied `op.offset` -- which is
      exactly how PyLabRobot spreads multiple channels that nominally
      target the *same* resource. `discard_tips()` sends all 8 channels to
      the deck's one `Trash`, distinguished only by a per-channel offset
      (`compute_channel_offsets(..., spread="tight")`); ignoring it made
      all 8 collapse onto the same point. Threaded `offset` through
      `resource_point()`/`tip_grab_point()`/`liquid_surface_point()` and
      every call site (`channel_ops_event()`, `resource_event()`, and its
      callers in `visualizer_backend.py` for the 96-head/resource-move
      ops, which have the same gap). Verified via an integration test
      against a real `discard_tips()` call: 8 channels, y positions
      exactly 9mm apart (`[342.7, 333.7, ..., 279.7]`).
- [x] **Slower playback for review.** Added a speed dropdown (1x/0.5x/
      0.25x) in the HUD, backed by a `durationScale` multiplier applied to
      every keyframe/pulse/flow duration in `main.js`. Applies to live
      viewing and replay alike, and can be changed mid-run.

## Review round 4 (2026-08-18)

User feedback after round 3: the channel always detours near
`trash_core96` between operations instead of just rising straight up; tip
spots overlapping/hidden inside the tip rack; wells and their fill level
not visible, likely the same clipping issue, with a suggestion to raise
wells/tip-spots in z and use black for empty ones.

- [x] **Detour near `trash_core96`.** Root cause, found by tracing
      `trash_core96`'s real coordinates (x≈3, essentially the deck origin)
      against the channel's constructor default (`x: 0`): the RISE leg's
      target x/y was `ch.pos.x/y` read **at the moment the op event
      arrived** (`animateChannelOp`'s enqueue call), not when the leg
      actually starts executing. Since events routinely arrive faster than
      their ~1.6s animation plays out, the per-channel queue backs up, so
      that snapshot is frequently stale -- often still showing the
      channel's *initial* (x=0) position from before it had moved at all,
      because no waypoint had executed yet by the time later events'
      RISE legs were enqueued. x=0 happens to sit almost exactly on
      `trash_core96`, which is never actually part of this demo's
      protocol -- explaining the "always detours there" pattern precisely.
      Fixed properly rather than patched around: `Channel.enqueue()` now
      accepts `x`/`y` of `null`, meaning "resolve to wherever this leg
      actually starts from" -- resolved lazily inside `update()`, right
      when the leg begins, using the channel's real position at that
      instant. `animateChannelOp`'s RISE leg now passes `{x: null, y:
      null, z: restZ}`, exactly matching the user's ask ("just go to safe
      z-height while maintaining the same x-y"). Verified live: sampled a
      channel's world x 1000 times over ~15s of replay -- zero samples
      landed near trash_core96's x (0 of 1001, vs. frequent hits before
      the fix).
- [x] **Tip spots hidden inside the rack / wells hidden inside plates.**
      Same root pattern as the carrier fix two rounds back, just not yet
      applied to these two categories: `tip_rack`'s declared `size_z`
      (20mm) and `plate`'s (14.2mm) were both rendered as a *solid* box
      the full declared height, but a `TipSpot`'s tip and a `Well`'s
      liquid sit recessed *inside* that height (a well starts 3mm up from
      a 14.2mm-tall plate's own base, comfortably inside it) -- so the
      solid parent box entirely buried them. Added `tip_rack`/`plate` to
      the same thin-slab treatment carriers already got
      (`THIN_CATEGORIES`), rendered at a fixed `THIN_CATEGORY_THICKNESS`
      (3mm) instead of their full declared height.

      This surfaced a real design bug in the *carrier* fix while
      implementing it: `buildResourceObject` was passing its own
      (possibly-thinned) rendered `sizeZ` down to children as
      `parentSizeZ`, conflating "how tall to draw this box" with "what
      height should children's layout math treat as the real surface."
      For carriers those happened to coincide by construction, but thinning
      tip_rack/plate the same way would have also shifted where their
      children think the real surface is, undoing the fix. Now always
      passes the *declared* `node.size_z` down (`declaredSizeZ`),
      independent of whatever thickness this node is actually rendered at.
- [x] **Black for empty tip spots/wells.** Tip spot pyramids are now
      *always* rendered (previously hidden via `visible=false` when
      empty) -- amber when present, black (`EMPTY_COLOR`) when not, so an
      empty slot still reads as a slot rather than disappearing.
      `VOLUME_EMPTY_COLOR` (the 0% end of a well's fill-level gradient) is
      now the same black instead of a dark teal.

      Verified live via material color lookups: a touched-then-discarded
      tip spot reads pure black (`000000`); an untouched one reads amber
      (`e0b23d`); a partially-drained well (150/360µL) and an
      untouched-but-prefilled one (200/360µL) both read distinct shades of
      green between black and full, proportional to fill.

## Review round 5 (2026-08-18)

User feedback: tip racks should show as filled at the very start, not just
after a replay; the destination plate's wells looked a different (and
inconsistent) color from the source plate's and from unused wells.

- [x] **Tip racks not filled at first connect.** Real bug, and the direct
      cause of "only visible after Replay" from round 3 lingering in a new
      form: `VisualizerServer` cached the *scene* for newly-connecting
      clients but never the latest *state* per resource. Since
      `_broadcast_initial_state()` (added two rounds back) fires
      synchronously during `setup()` -- normally well before a demo's
      grace-period sleep even starts -- any client connecting during that
      "now would be a good time to open the browser" window had already
      missed it, and would show an all-black/empty scene until clicking
      Replay. Added `VisualizerServer._latest_state` (resource name -> its
      most recent state event); new connections now receive it right after
      the scene, same as replay already did via history. Verified live:
      connecting mid-run (before the demo's first pipetting step) now shows
      the pre-filled tip rack immediately, no Replay needed.
- [x] **Destination-plate wells "look wrong."** Not a rendering bug --
      checked the actual numbers live: `source_plate_well_A1` (150/360µL,
      used) vs `_A4` (200/360µL, untouched) vs `dest_plate_well_A1`
      (50/360µL, used) vs `_A4` (0/360µL, untouched) all came back as
      different shades of the *same* single teal-to-black gradient,
      exactly tracking their real (and genuinely different) volumes --
      the demo only ever dispenses 50µL into a 360µL-max well, so a
      "used" destination well is only ~14% full. The actual problem: a
      *linear* volume fraction makes anything under ~20% nearly
      indistinguishable from truly empty, so the destination plate's used
      wells (14%) looked almost as black as its untouched ones (0%), while
      the source plate's wells (42-56%, since the demo pre-fills them to
      200µL for the demo to have something to aspirate) looked clearly
      green -- reading as "inconsistent" even though every well was
      colored correctly for its own volume. Changed the fraction to
      `Math.sqrt(rawFraction)` before the color lerp: boosts the low end
      (14% -> 37% along the gradient) while leaving 0% at 0 and 100% at
      100% and preserving monotonic ordering, so a small-but-real volume
      now reads as clearly non-empty without misrepresenting which well
      has more liquid. Verified live: the same 50µL destination well went
      from `0c5d42` (barely different from black) to `1a946b` (clearly
      green), while the 0µL one is still exactly `000000`.

## Review round 6 (2026-08-18)

User feedback: wells appeared filled before the dispense animation reached
them (originally phrased as "before the filling animation happens").

- [x] **Well/tip color changing before the animation arrives.** Root cause:
      PyLabRobot's tracker fires its state-update callback the moment
      `LiquidHandler.dispense()`/`aspirate()`/`pick_up_tips()`/`drop_tips()`
      queues the tracker change -- *before* it even calls this backend (i.e.
      before `VisualizerBackend`, and therefore the "op" event that drives
      the gantry animation, runs at all). So the separately-broadcast
      "state" message routinely reaches the frontend and gets applied
      before the corresponding "op" event's animation has even started,
      let alone arrived. Confirmed by reading PyLabRobot's own
      `VolumeTracker`/`TipTracker` source: `add_liquid`/`remove_liquid`/
      `remove_tip` all invoke the registered callback immediately, and
      `LiquidHandler` only calls the backend afterward.

      Fixed by not depending on that message's timing at all for these two
      categories:
      - `events.py`'s `channel_ops_event()` now embeds the *resulting*
        state directly in each channel entry (`resource_has_tip` for
        pick_up_tips/drop_tips, computed for free since a successful call
        always empties/fills its target; `resource_volume`/
        `resource_max_volume` for aspirate/dispense, read from the
        tracker's `pending_volume` -- not `volume`, since our wrapper runs
        before `LiquidHandler.commit()` syncs the two).
      - `visualizer_backend.py`'s `_register_state_callbacks` now skips
        registering a live callback for `tip_spot`/`well` categories
        entirely -- their only live-update path is the embedded data above.
      - `main.js`'s `applyEmbeddedResourceState()` applies that embedded
        data from `animateChannelOp`'s `onArrive` -- i.e. exactly when the
        gantry visually arrives, never before.

      **Regression found and fixed while verifying this end-to-end:**
      skipping the live callback also stopped updating
      `VisualizerServer._latest_state` (the snapshot sent to *new*
      connections -- see round 5) for tip_spot/well, so a client connecting
      after a run had progressed saw stale pre-run state for those two
      categories instead of what actually happened. Added
      `VisualizerServer.record_resource_state()`, a cache-only update (no
      live broadcast) that `visualizer_backend.py` now also calls from the
      same embedded data, keeping new connections correct without
      reintroducing the timing race.

      Verified in three ways: (1) an integration test confirmed the
      embedded values are correct (`resource_volume: 150.0` after
      aspirating 50µL from a 200µL well) and that zero live "state" events
      fire for touched tip_spot/well resources during a run; (2) before
      adding `record_resource_state()`, a fresh connection made *after* a
      full demo run reproduced the regression exactly (a dispensed-into
      well stuck showing its stale pre-run black); (3) after adding it, the
      same scenario showed every well/tip-spot's correct final color.

## Review round 7 (2026-08-18)

User feedback: needed an explicit "start" trigger instead of a fixed wait
so there's no risk of connecting mid-run; a ~100mm gap between the deck
platform and the carriers it's meant to support; tip pyramids should use
the real tip length, not an arbitrary constant; empty wells/tip-spots
should be semi-transparent.

- [x] **Start button instead of a fixed sleep.** Added
      `VisualizerServer.wait_for_start()` (blocks on an `asyncio.Event`)
      and a `{"action": "start_protocol"}` websocket message that sets it
      and broadcasts `{"type": "start_status", "started": true}` to every
      connected client. `examples/demo_protocol.py` now calls
      `await server.wait_for_start()` instead of `asyncio.sleep(10)`. A
      green "Start Protocol" button in the HUD sends the action and hides
      itself once `start_status` confirms it; a client connecting *after*
      someone else already started sees it correctly pre-hidden (the
      status is sent to every new connection, not just broadcast at the
      moment it happens). This is also documented in the README as the
      recommended pattern for real protocols, not just the demo.
- [x] **~100mm gap between the deck platform and the carriers.** Same
      family of bug as the carrier/tip_rack/plate fixes in earlier
      rounds, just one level up: checked real coordinates and found deck
      children (carriers, trash) attach at `location.z=100` relative to
      the deck, not `0` -- the deck's own `size_z` origin is the
      instrument's structural floor, not the carrier rail surface. The
      platform was anchored at the deck's z=0, leaving it floating
      ~100mm below every carrier. Fixed the same way the carrier shaft
      height was: anchor the platform's *top* at the minimum child
      `location.z` instead of at the deck's own origin. Verified live:
      the deck mesh's world-space center now reads `y=95` (platform
      top at 100, thickness 10mm) -- exactly the carriers' attachment
      height.
- [x] **Tip pyramid length.** Was a flat constant (16mm resting in the
      rack, ~35mm carried by a channel) with no connection to the real
      tip. Added `scene.py`'s `_rack_tip_length()`, which reads
      `total_tip_length` from a rack's seated tip if any spot has one,
      falling back to `TipSpot.make_tip()` (one harmless side effect: it
      advances that spot's name counter by one) if the whole rack starts
      empty, and embeds it as `tip_length_mm` on each `TipRack` scene
      node. `main.js` threads it down to each spot's pyramid the same way
      `parentSizeZ` already flows to it. For the *channel's* carried tip,
      `events.py` embeds the real picked-up tip's `total_tip_length`
      directly in the `pick_up_tips` op event (no lookup needed --
      `op.tip` *is* the real tip), and `Channel.setTip()` rebuilds its
      geometry to match, remembered as `tipLength` so every subsequent
      op with that tip (aspirate/dispense/drop) uses the correct
      body-clearance offset too, not just the pick-up itself. Verified
      live: both the rack pyramid and the channel's carried-tip geometry
      read exactly `95.1` (mm) for the demo's 1000µL filter tip.
- [x] **50% opacity for empty wells/tip-spots.** `volumeVisual()`/
      `tipVisual()` now return an opacity alongside the color -- 50% at
      the empty end, ramping to 100% with fill (wells) or a flat 100%
      when present (tip spots) -- shared by both places a color gets
      applied (the generic "state" path and the timing-correct embedded
      op-event path from round 6) so they can't drift apart. Had to also
      add `transparent: true` to the tip pyramid's material, which
      previously had no opacity support at all. Verified live: an empty
      well reads `opacity: 0.5`, a tip spot with a tip reads `opacity: 1`.

## Review round 8 (2026-08-18)

User feedback: pre-filled source-plate wells other than the ones actually
aspirated from stayed black at startup; the very first round of
aspirate/dispense sank the tips much too low (rounds 2 and 3 looked
correct); the plate read as a disconnected array of cubes, unlike the tip
rack's single blue base.

- [x] **Pre-filled wells not visible until touched.** Root cause:
      `_broadcast_initial_state()` runs once, synchronously, inside
      `setup()` -- but `examples/demo_protocol.py` (like most real
      protocols would) does its own state setup *after* `setup()` returns
      (`well.set_volume(200)` for every source well, so there's something
      to watch drain). tip_spot/well categories don't get live callback
      updates at all (round 6's `_LIVE_CALLBACK_EXCLUDED_CATEGORIES`, to
      avoid the state-vs-animation race), so a well changed in that
      after-`setup()` window stayed invisible until an aspirate/dispense
      happened to touch it -- exactly what made only the actually-aspirated
      wells look right and everything else look empty. Fixed by adding
      `VisualizerBackend.wait_for_start()`, which blocks on the existing
      (round 7) start gate and then re-runs `_broadcast_initial_state()`
      -- the point a protocol clicks "Start" is exactly the point it's
      declaring its manual setup finished, so re-snapshotting there closes
      the gap without reintroducing the round-6 race (nothing here is tied
      to animation timing). `demo_protocol.py` now calls
      `backend.wait_for_start()` instead of `server.wait_for_start()`
      directly. Verified live: before clicking Start, all source-plate
      wells read `000000` (black) as expected (the fix only fires on
      Start); immediately after clicking it, both aspirated wells *and*
      untouched ones (e.g. `source_plate_well_A4`, `H4`, `A12`, `H12`,
      never touched by the 3-column demo) read the same pre-fill green
      (`27ca93`)/opacity as each other.
- [x] **First round's tips too low.** Same *class* of staleness bug as an
      earlier round's x/y fix, just not yet applied to Z: `animateChannelOp`
      computed `entry.z + ch.tipLength` synchronously at event-arrival
      time, but `ch.tipLength` is only updated to the real tip length by a
      *preceding* `pick_up_tips` leg's `onArrive` callback -- which, on the
      first round, hadn't necessarily fired yet if events arrived faster
      than the ~1.6s-per-op animation could drain its backlog (exactly the
      first round, before the queue has had time to catch up). Every later
      round was fine because by then the backlog had settled. Fixed by
      extending the existing lazy-resolution mechanism (`enqueue()`
      already supported `target.x`/`target.y === null` meaning "resolve
      when this leg starts") to also accept `target.z` as a function,
      resolved at the same point -- relying on the same guarantee that
      already made the x/y fix correct: a channel's queue is strictly
      FIFO, so by the time a later leg actually starts, every earlier
      leg's `onComplete`/`onArrive` (including the `pick_up_tips` that
      sets `ch.tipLength`) is guaranteed to have already run. Verified
      live: recorded channel 0's world-space height every 50ms across all
      three rounds and extracted each round's local-minima (the
      pick_up_tips/aspirate/dispense/discard_tips depths). All three
      rounds produced the *identical* sequence (`313.65`, `287.94`,
      `281.75`, `232.2`), i.e. no first-round-only anomaly.
- [x] **Plate reads as disconnected cubes.** First changed `plate`'s
      `CATEGORY_COLORS` (and the matching legend entry) from a
      well-fill-gradient-adjacent green (`0x3d9970`) to a muted purple
      (`0x6a5a94`), reasoning the base was blending into its own wells'
      colors the way `tip_rack`'s blue clearly doesn't. The material color
      changed correctly, but the user reported still seeing no purple at
      all -- the real bug was two levels deeper. Dumped the actual
      PyLabRobot resource tree for `source_plate` and its carrier site:
      the plate sits at `location.z = -3.03` on its `PlateHolder` -- a
      real, baked-in PLR datum offset (chosen so the plate's own wells, at
      `+3.03`, land exactly flush with the carrier rail), not "how far the
      visible base sticks up." Round 7's thin-slab code drew the base from
      the plate's own local `0` to `THIN_CATEGORY_THICKNESS` (3mm)
      upward -- for a `TipRack` (whose site offset is exactly `0`) that's
      the visible surface, but for a `Plate` it put the entire slab
      *below* the rail, buried inside the carrier's own box (whose height
      is computed to reach exactly that same rail) -- rendered, correctly
      colored, and completely invisible. Confirmed numerically before
      fixing: carrier top and well bottom both read world `y=186.15`,
      while the plate's slab spanned `183.12`-`186.12`, i.e. entirely
      under the carrier's opaque geometry. Fixed by lifting a thin
      category's slab by however far its own placement is recessed below
      zero (`Math.max(0, -node.location.z)`) before centering it --
      canceling a negative datum offset the same way round 7 canceled
      TipSpot's baked `-83.5mm` dz for its pyramid, just at the parent's
      own placement instead of a child's. `TipRack` (offset `0`) is
      unaffected. Verified live: the plate's slab now spans world
      `186.15`-`189.15`, flush with the carrier rail and the wells'
      bottom, and a screenshot shows a clearly visible purple base/rim
      around and between the wells on both plates, matching the tip
      rack's blue-tray look.

## Review round 9 (2026-08-18)

User feedback: the cherry-picking demo (added this round, see below) didn't
match how a real Hamilton STAR actually moves -- all 8 channels are bolted
to one arm with a single x motor, so they're always at the same x; only y
(and z, for whichever channels are actually pipetting) can differ per
channel. The original demo's scattered dispense moved all 8 channels to
independent (x, y) targets simultaneously, which isn't physically possible.
Asked for a helper function to plan real, reachable gantry motion, and
asked clarifying questions before implementing.

- [x] **New demo: `examples/cherry_pick_demo.py`.** Aspirates a full
      column (`A1:H1`) from the source plate, then dispenses into 8
      hand-picked destination wells chosen to read as a smiley face (2
      eyes + a 6-point mouth curve) -- added before the gantry-realism
      request below, as a starting point.
- [x] **New library module: `src/hamilton_visualizer/gantry.py`.** Added
      as a reusable helper (not demo-local -- confirmed with the user:
      "a real Hamilton can't move channels to independent x positions" is
      a hardware fact, not a fact about this one demo). Core piece is
      `plan_gantry_passes()`: turns "channel i eventually needs resource
      R_i" into a sequence of `GantryPass`es, one per distinct x
      (ascending), each carrying which channel(s) actually have a target
      there and the minimal y-nudges every other loaded channel needs to
      stay clear (per the user's answer: "if the channels are in the way
      ..., move them on Y to maintain >= 9mm center to center distance").
      Solved with a two-pass algorithm (see the module's own docstring for
      the change-of-variable trick that turns "decrease by >= pitch per
      step" into plain non-increasing, solved by one forward and one
      backward propagation pass).

      **First version had a real bug, not just a naive one:** an initial
      single-pass clamp raised spuriously whenever an idle channel's
      *stale* preferred y (from a different, already-visited plate/site --
      e.g. still holding its post-aspirate source-plate position while a
      much-later dispense pass needs it near the destination plate's very
      different y range) was tighter than a downstream fixed target
      needed, because the forward sweep locked in "too low" before ever
      seeing the conflict. Fixed by reformulating as the two-pass
      forward/backward propagation described above, verified by hand
      against a real conflicting case (channel 0/1 needing to jump ~70mm
      from the source plate's y range to the destination plate's) before
      moving on.

      **Second, separate issue found via the same verification:** with a
      straightforward "channel i dispenses to smiley well i" mapping,
      channels 1 and 6 (assigned to `C8`/`G8`, which share column 8) are 5
      channel-slots apart but their rows are only 4 apart -- physically
      unreachable in one simultaneous move, confirmed by hand (`(6-1) *
      9mm = 45mm` needed vs. `36mm` actually available). Initially fixed
      by hand-picking a conflict-free channel-to-well assignment, but the
      user then corrected the underlying design: rather than solving for
      one global simultaneous arrangement, real hardware (and the user's
      explicit algorithm) just falls back to visiting such channels
      **one at a time, smallest channel index first**, when a column's
      channels can't all be reached together. Rewrote
      `plan_gantry_passes()` around that: for each column, try resolving
      all of that column's channels as fixed simultaneously; if
      `_resolve_ys` raises (infeasible), fall back to one stop per
      channel instead, in ascending index order -- reusing the same
      solver either way, since a lone fixed channel can never conflict
      with itself. This also meant the original, narrative-friendly
      channel-to-well assignment (`C5, C8, F4, G5, G6, G7, G8, F9`, no
      hand-reordering needed) just works.
- [x] **`VisualizerBackend.nudge_channel()`.** A purely cosmetic
      channel reposition (broadcasts directly, skipping `self._inner`
      entirely) for `plan_gantry_passes()`'s idle-channel nudges -- there's
      no PLR-level command for "get out of the way" (real firmware
      handles this internally as part of a command's own motion planning,
      not as something a protocol issues), and the existing hardware
      passthroughs (`move_channel_x`/`move_channel_y`) aren't usable here
      anyway since `LiquidHandlerChatterboxBackend` doesn't implement them
      (raises `NotImplementedError` -- confirmed directly against its
      source).
- [x] **Frontend: `nudge_channel` op + `target.z === null` support.**
      Added a `"nudge_channel"` case to `handleOpEvent()` -- a plain glide
      to `(x, y)` at rest height, no rise/descend/hold structure, since
      it's never touching labware. Also extended `Channel.update()`'s
      lazy-resolution handling (`target.x`/`target.y === null` already
      meant "resolve at leg start") to cover `target.z === null` too, for
      symmetry and because a nudge might only specify one axis.

      Verified live: recorded all 8 channels' world x every ~80ms across
      a full run -- the vast majority of samples show all 8 sharing
      exactly one x value, with mismatches confined to the brief windows
      *during* an animated move (expected, since channels glide rather
      than teleport). The event log shows the exact expected sequence at
      column 8: `dispense p1:dest_plate_well_C8` (channel 1 alone), then
      seven `nudge_channel` calls dragging every other channel to that
      same x, then `dispense p6:dest_plate_well_G8` (channel 6 alone) --
      i.e. real column-by-column, smallest-index-first motion, not a
      simultaneous scattered jump. A screenshot of the finished run shows
      the same recognizable smiley face as before, produced this time by
      physically-plausible motion.

## Review round 10 (2026-08-18)

User feedback: the x-movement and dispense movements weren't happening in
the correct order -- should be strictly x-move -> y-move -> z-move ->
dispense.

- [x] **Diagonal x/y travel, not sequential.** `animateChannelOp()`'s
      "travel" leg (and `nudge_channel`'s single move) interpolated x and y
      *together* in one tween -- a diagonal glide, not the real motion
      order (shared-x arm moves first, then this channel's own y motor --
      see `hamilton_visualizer.gantry`'s docstring for the same hardware
      fact applied across channels; this is that same fact applied to one
      channel's own approach). Split the single combined-XY leg into two
      sequential legs (`X_MOVE_MS` then `Y_MOVE_MS`, replacing the old
      single `TRAVEL_MS`) in both `animateChannelOp()` and the
      `nudge_channel` handler, so x fully completes before y starts, and y
      fully completes before z (descend) starts -- descend's `onArrive` is
      what actually triggers the dispense/aspirate/pick-up-tip effect, so
      this also guarantees dispense never fires until z has descended,
      which itself never starts until both x and y are in place.

      Verified live: recorded channel 0's (x, y, z) position every 20ms
      across a full cherry-pick run and classified consecutive samples by
      which axis was actually changing. The trace is a clean, repeating
      `x -> y -> z` sequence (each axis's segment fully finishing before
      the next begins) with no sustained simultaneous-axis segments --
      the only "mixed" samples are single ~20ms polling-boundary
      artifacts (one sample landing exactly between two legs), not real
      simultaneous motion.

## Review round 11 (2026-08-18)

User feedback: after round 10's per-channel x -> y -> z fix, the motion
still didn't look right. Then, once the real cause turned out to be a
timing/architecture issue: "I would like the gantry move to be handled on
the visualizer level ... rather than handled by the python script. I would
like the python script to just simply say `await lh.dispense(<list_of_
target_wells>, volumes...)`."

- [x] **Diagnosed round 10's fix as incomplete, not wrong.** Round 10 made
      each *individual* channel's own approach strictly x -> y -> z, and
      that part was correct -- but `examples/cherry_pick_demo.py` still
      drove `plan_gantry_passes()` from Python, issuing one real
      `lh.dispense()`/`nudge_channel()` broadcast per gantry stop with a
      fixed `asyncio.sleep()` in between to (try to) let one stop's
      animation finish before the next stop's events went out. Recorded
      all 8 channels' position every 15ms and classified which axis each
      was moving on: even after widening the sleep from 0.3s to 2.1s
      (well past the nominal ~1.6s animation), some fraction of samples
      still showed *different* channels in *different* phases at the same
      instant (e.g. one channel already descending to dispense while
      another, from the *next* stop, was already moving in y) -- i.e. the
      arm wasn't visibly moving together stop-by-stop. Root cause: guessing
      a server-side sleep long enough to cover animation + websocket/
      asyncio scheduling jitter is fundamentally unreliable, not just
      under-tuned.
- [x] **Moved gantry-pass planning from Python to the frontend.** Per the
      user's explicit request, `hamilton_visualizer.gantry` (the round-9
      module) and `VisualizerBackend.nudge_channel()` are deleted;
      `examples/cherry_pick_demo.py` now does exactly one plain
      `await lh.dispense(dest_wells, vols=[...])` for all 8 scattered
      wells, identical in shape to every other `dispense()` call in this
      repo. `frontend/main.js` gained `planGantryPasses()` (a direct port
      of the deleted Python module's grouping/fallback logic) and
      `resolveChannelYs()` (a port of `_resolve_ys`), operating on the
      `x`/`y` values already embedded in the "op" event's channel entries
      -- no new data needs to flow from the server at all. A channel's
      *current* position (`Channel.pos.y`, continuously tracked by the
      renderer already) stands in for the old `initial_y` parameter a
      protocol script used to have to compute and pass in by hand.
      `pick_up_tips`/`drop_tips`/`aspirate`/`dispense` in
      `handleOpEvent()` now all route through this via a shared
      `animateChannelGroupOp()` helper instead of each naively animating
      every channel entry independently and assuming simultaneous
      feasibility.

      This isn't just moving the same logic to a different language: since
      every pass's legs for *every* involved channel are now enqueued
      synchronously, in order, onto each channel's own already-existing
      FIFO queue (`Channel.enqueue()`, round 7) the moment the *one* real
      op event arrives, there is no external timing/sleeping anywhere in
      the whole path any more -- each channel's queue naturally plays its
      own legs out in enqueued order, which is what actually guarantees
      passes never overlap, instead of a guessed sleep duration that
      merely made overlap less frequent.
- [x] **Found and fixed a second, structural desync bug during
      verification.** With the sleep removed, the same cross-channel
      phase mismatch *still* showed up, at the same reproducible point.
      Cause: an idle channel's nudge (`RISE + X + Y` = 750ms) takes
      *less* total time than an active channel's full cycle (`RISE + X +
      Y + DESCEND + HOLD + RETRACT` = 1600ms) for the same gantry stop --
      so the idle channel's queue drains sooner and starts the *next*
      stop's legs while an active channel from the *current* stop is
      still mid-descend, even though both stops' legs were enqueued in
      the correct order. Fixed by padding `nudgeChannel()` with a final
      no-op wait (`DESCEND_MS + HOLD_MS + RETRACT_MS`) so every loaded
      channel spends exactly the same total duration per stop whether
      it's active or idle there, keeping every channel's queue advancing
      through stops in lockstep.

      Verified live: recorded all 8 channels' position every 15ms across
      a full cherry-pick run (now driven by a single `lh.dispense()` call)
      and classified which axis each channel was moving on at each
      sample. Before the padding fix: 159 of 2821 samples showed more
      than one distinct axis in motion across channels at the same
      instant. After: 0 of 2680 samples did. The event log shows exactly
      one `dispense` entry listing all 8 channels/wells, confirming the
      Python side issued a single ordinary call; a screenshot shows the
      same smiley face as before, now driven entirely by the visualizer's
      own planning.

## Review round 12 (2026-08-19)

User feature requests: render wells by their real shape (round -> cylinder,
V-bottom like a PCR plate -> inverted cone, square -> unchanged box); label
the deck's rails every 5 (5, 10, 15, ...); show a well's volume on hover.

- [x] **Shape-aware well rendering.** PyLabRobot's own `Resource.
      serialize()` already reports a Well's `bottom_type` ("flat"/"U"/"V"/
      "unknown") and `cross_section_type` ("circle"/"rectangle") -- real
      dataclass fields, not something scene.py had to add -- so this
      needed zero backend changes. Added `wellShapeFor()`: V-bottom wells
      get an inverted `ConeGeometry` (apex down, same rotation trick as
      the tip pyramid), circular-cross-section wells get a
      `CylinderGeometry`, everything else keeps the existing `BoxGeometry`.
      Both new geometries are built once as a *unit* shape (radius/size
      0.5, height 1) and non-uniformly scaled per instance
      (`mesh.scale.set(sizeX, sizeZ, sizeY)`) to the well's real
      footprint, so one geometry is reused across every well of a plate
      instead of allocating a differently-sized one per well.

      Verified live: `cor_96_wellplate_360uL_Fb` (flat bottom, circular)
      now reports `CylinderGeometry` correctly scaled to `(6.86, 10.67,
      6.86)`, and a screenshot shows visibly round wells instead of
      cubes. A real V-bottom plate
      (`Azenta4titudeFrameStar_96_wellplate_200ul_Vb`) reports
      `ConeGeometry` with `rotation.x = π` (apex down); a screenshot
      shows the wells reading as small points/spikes rather than flat
      tops.
- [x] **Rail number labels, every 5.** `num_rails` is already part of a
      deck node's own `serialize()` output (a real field on
      `HamiltonDeck`, no injection needed); the rail-to-x formula (`x =
      100.0 + (rail - 1) * 22.5`) only exists as arithmetic inside
      PyLabRobot's `rails_to_location()`, so those two constants are
      hardcoded on the frontend (`RAIL_X_OFFSET_MM`/`RAIL_WIDTH_MM`) the
      same way `CHANNEL_PITCH_MM` already is, rather than threading two
      numbers that never change through scene.py. Added
      `createTextSprite()` (same "draw text on a canvas, use it as a
      texture" approach `createFlowTexture()` already uses -- no font-
      loading library needed) and `addRailLabels()`, placing a billboard
      sprite reading "5", "10", ... at each fifth rail's x, just in front
      of (smaller y than) where carriers actually attach, at deck-surface
      height, so they read like ruler markings instead of overlapping any
      carrier sitting on the rail.

      Verified live: a screenshot of the STARLet deck (32 rails) shows
      "5", "10", "15", "20", "25", "30" running along the front edge in a
      clean line matching the isometric perspective.
- [x] **Volume on hover.** The hover tooltip (round 1) only ever showed a
      resource's static name/type -- nothing tracked a well's *live*
      volume anywhere retrievable later; `applyState()`/
      `applyEmbeddedResourceState()` only ever wrote it straight into the
      mesh's color/opacity. Added `volume`/`maxVolume` fields to each
      resourceIndex entry (seeded from the node's own declared
      `max_volume`, updated by both of those functions alongside the
      color/opacity they already set) and a volume line in the tooltip,
      shown only for `category === "well"` and only once a real value has
      arrived (`entry.volume` starts `null`, so an unstarted protocol
      doesn't claim every well is at 0uL).

      Verified live: seeded a well's tracked volume, synthesized a
      pointermove at its exact projected screen position (via
      `camera.project()` on its mesh's world position) to trigger the
      real hover handler, and confirmed the tooltip's rendered HTML reads
      "123.4 / 360 µL" under the resource name/type, styled in the same
      green used for the well legend swatch.

## Review round 13 (2026-08-19)

User feature requests: draw lines on the deck marking the borders between
rails; hovering a plate or carrier should show its specific catalog model
(e.g. "cor_96_wellplate_360uL_Fb", "TIP_CAR_480_A00"), not just its coarse
type.

- [x] **Rail border lines.** Added `addRailLines()`, drawing a thin line
      at *every* rail boundary (not just every `RAIL_LABEL_INTERVAL`-th
      one like the round-12 number labels) -- `numRails + 1` lines
      bracketing each 22.5mm-wide slot, spanning the deck's full y depth,
      sitting on the platform's own top surface. Uses normal depth-testing
      (unlike the always-on-top label sprites), so a carrier sitting on
      the rail correctly occludes the line segment underneath it, since a
      line "on the deck" should behave like a real surface marking, not a
      HUD overlay. One `THREE.LineSegments` with a single `BufferGeometry`
      for the whole set rather than one object per line.

      Verified live: screenshot shows a clean ruled grid across the full
      deck surface, with lines visibly interrupted where the tip and
      plate carriers sit on top of them.
- [x] **Model in tooltip.** `node.model` -- the catalog identifier for the
      specific factory/constant that built this resource instance -- is
      already a real `Resource` field PyLabRobot includes in
      `serialize()` (confirmed directly: `cor_96_wellplate_360uL_Fb(name=
      "p").model == "cor_96_wellplate_360uL_Fb"`), distinct from the much
      coarser class name (`resourceType`, e.g. "Plate") the tooltip
      already showed. Threaded through to both mesh and tip-pyramid
      `userData` and added as a new tooltip line, shown for anything that
      has one (plates and carriers per the request, but also tip racks,
      trash, etc. for free, with no per-category special-casing needed).

      Verified live: hovering the source plate's base (at a corner
      outside the well grid, so the raycast doesn't hit a well sitting on
      top of it) shows "cor_96_wellplate_360uL_Fb"; hovering the tip and
      plate carriers shows "TIP_CAR_480_A00" and "PLT_CAR_L5AC_A00"
      respectively -- confirmed both via the tooltip's rendered HTML and
      a screenshot.

## Review round 14 (2026-08-19)

User feedback: rail number labels sat on a rail's *border* rather than
within it -- "the number 5 is drawn at the border between rail 4 and 5."

- [x] **Centered rail labels within their own slot.** `addRailLabels()`
      used the exact same x as `addRailLines()`'s border at that rail
      number -- correct for a border, but a rail's number should read as
      labeling its own slot, not the boundary with the rail before it.
      `RAIL_X_OFFSET_MM + (rail-1)*RAIL_WIDTH_MM` is rail N's *left*
      border (also where a resource assigned via `rails=N` actually
      attaches); added `+ RAIL_WIDTH_MM / 2` so the label sits centered
      between that left border and rail N's right border instead.

      Verified live: rail 5's label now sits at world x=201.25 --
      exactly midway between its left border (190.0) and right border
      (212.5, i.e. rail 6's left border) -- and a screenshot shows every
      label sitting inside its own slot rather than on a dividing line.

## Review round 15 (2026-08-19)

User request: a new demo protocol for a PicoGreen dsDNA quantitation
reaction -- samples in columns 1-3 of a 96-well PCR plate, a 2-fold serial
dilution standard curve (8 wells, last one pure diluent) from a 100 ng/uL
stock and TE diluent in 1.5mL Eppendorf tubes on a 32-tube carrier, diluted
into column 12 of the sample plate, then 5uL sample/standard + 195uL
PicoGreen working solution (60mL Hamilton reservoir) into a Corning
360uL flat-bottom assay plate.

- [x] **Researched every real resource before writing anything.** A PCR
      plate needed to be *skirted* (`azenta_96_wellplate_200uL_Vb_
      4titudeframestar`) -- PLR's `PlateHolder.assign_child_resource`
      hard-rejects semi-skirted plates (common real PCR plates like
      Thermo MicroAmp) on a standard carrier site. The 60mL reservoir
      (`hamilton_1_trough_60mL_Vb`) needed `Trough_CAR_5R60_A00` (which,
      despite its name, only has 4 sites in PLR's current definition).
      The 32-tube carrier is `hamilton_tube_carrier_32_a00_insert_
      eppendorf_1_5mL` holding `eppendorf_tube_1500uL_Vb` tubes --
      `Tube_CAR_32_A00` and a couple of Eppendorf-tube aliases are
      deprecated wrappers pointing at these. All four carriers verified
      end-to-end on a real `STARLetDeck()` (rails 1/7/13/14, no
      collisions) before any visualizer work started.
- [x] **Two rendering bugs found and fixed, exposed by resource
      categories this project had never used before.**
      - `trough_carrier` (the reservoir's carrier) was missing from
        `CARRIER_CATEGORIES` -- confirmed with real coordinates (declared
        `size_z=104mm`, but its trough site attaches at only `z=63.5mm`)
        that this is the exact same envelope-vs-payload gap already fixed
        for every other carrier category in round 7; without the fix, the
        reservoir would render buried inside a full-height solid box.
      - `trough`/`tube` categories were missing from `CATEGORY_COLORS`
        (cosmetic -- fell back to a generic gray) and, more importantly,
        from `_LIVE_CALLBACK_EXCLUDED_CATEGORIES` -- since
        `channel_ops_event()`'s embedded-volume logic is already
        category-agnostic (any Container with a tracker, not
        well-specific), any aspirate/dispense against the reservoir or a
        tube would have raced a live "state" broadcast ahead of the
        gantry animation, reproducing round 6's original bug for two
        categories nobody had exercised yet. Fixed preemptively, before
        the demo ever ran, by reasoning from the existing code rather
        than waiting to observe it break.
- [x] **A real protocol-design bug: the top standard well was fully
      drained.** First version aspirated only `DILUTION_VOLUME` (100uL)
      of neat stock into A12; the very next step (`A12 -> B12`) pulls
      that same 100uL back out, leaving A12 at 0uL -- enough for the
      dilution math to work, but nothing left for A12's own 5uL transfer
      to the assay plate later. Live run confirmed this exactly:
      `TooLittleLiquidError: 5.0uL > 0.0uL`. Fixed by loading A12 with
      *2x* `DILUTION_VOLUME`, the standard technique for a serial
      dilution's first tube -- verified by hand-tracing the resulting
      volumes for every well (A-F settle at 100uL, G at 200uL, H at
      100uL, all comfortably above the later 5uL draw) before rerunning.
- [x] **A real, harder-to-spot bug: channel 0 fell ~38s behind channels
      1-7, so later multi-channel reads caught it mid-backlog.** After
      the liquid-volume fix, live verification still showed 5 of 8
      column-12 wells at their *pre*-transfer volumes (confirmed via the
      wells' actual rendered opacity, not just cached tooltip state, so
      this was a real rendering bug, not a stale metadata field).
      Traced with temporary logging in `planGantryPasses()`/
      `applyEmbeddedResourceState()`: the server's embedded volume data
      was correct for every channel the whole time -- channel 0 was
      simply still working through its own ~38.4s single-channel
      dilution-stage backlog (24 legs: pick-up, top-standard aspirate+
      dispense, diluent aspirate+7 dispenses, 6 serial aspirate/dispense
      pairs, discard) when the query ran, while channels 1-7 (with no
      such backlog) had already reached and applied their own later
      column-12 legs. This is a real gap round 11's architecture didn't
      anticipate: it guarantees passes never overlap *within* one
      multi-channel op, but a lopsided single-channel stage can leave one
      channel's queue far longer than the others' *across* stages, and
      nothing currently drags idle channels along during a call that
      doesn't target them (see `planGantryPasses()`'s docstring -- it
      only ever considers channels actually present in a given call's
      `entries`). On a real Hamilton this desync is physically
      impossible -- channels 1-7 can't do anything elsewhere while
      channel 0 alone is tied to the one shared arm -- so the fix belongs
      in the protocol script, not the visualizer: added a calculated
      wait (24 legs x ~1.6s/leg x 1.3 margin, the same proportional
      safety margin round 9 needed for a single pass) after the dilution
      stage, giving channel 0's real backlog time to fully drain before
      the 8-channel stages begin.

      Verified live: reran the full protocol and checked every column-12
      sample-plate well and all 32 assay-plate wells immediately after
      the script printed "finished," with no extra waiting -- all matched
      their expected volumes exactly (A-F/H at 95uL, G at 195uL; all 32
      assay wells at 200uL). Screenshot confirms the full deck (tip
      carrier, paired sample/assay plates, reservoir carrier, tube
      carrier) renders correctly end to end.

## Review round 16 (2026-08-19)

User feedback on the PicoGreen demo: use 7 channels for the TE-diluent
distribution instead of one; during that single-channel phase, *every*
channel should visibly move together even when only one is active; pick
tip size by transfer volume (1-50uL/50-300uL/300-1000uL -> 50/300/1000uL
tips); color-code tips by size (pink/yellow/white); move the reservoir to
rail 2 and the two tubes to rails 7 and 8.

- [x] **Researched real resources before touching anything.** Confirmed
      exact factory names (`hamilton_96_tiprack_50uL_filter`/`_300uL_
      filter`), and that a `Tip`'s `nominal_volume` (not `maximal_volume`,
      which is a real ~10-20% Hamilton overfill allowance, e.g. 1065 for a
      "1000uL" tip) is the nameplate value to classify/color by. Confirmed
      PyLabRobot has no small Hamilton Eppendorf tube carrier (minimum is
      24/32 sites) -- "tubes to slot 7 and 8" means two separate
      32-carrier instances, one tube each, not a smaller part.
- [x] **7-channel diluent distribution + real drag-along.** Rewrote the
      dilution stage: channels 1-7 each aspirate 100uL from the tiny
      diluent tube in turn (only one channel fits its ~10mm opening at a
      time), then all 7 dispense into B12-H12 simultaneously. Fixed
      `planGantryPasses()` to actually implement what its own docstring
      already claimed ("every other loaded channel gets nudged") --
      previously `channelIndices` only ever came from the current call's
      own `entries`, so a single-channel call left the other 7 channels
      completely stationary instead of dragged along. Now derives the
      extra dragged-along channels from every channel currently loaded
      with a tip, not just the ones this specific call targets.
- [x] **A real staleness bug in that fix, caught via a leg-count audit,
      not just a screenshot.** The first version read
      `channels[i].hasTip` -- Channel.setTip()'s flag, which only flips at
      an op's own animation `onArrive`, routinely *well after* this event
      was received (the same "events arrive faster than their ~1.6s
      animation plays out" reality this file has design around before).
      Planning a pass needs to know "is this channel loaded" at *event-
      processing* time, not whenever its animation catches up -- reading
      the animation-timed flag silently undercounted loaded channels for
      every call issued before an earlier pick_up_tips's animation had
      finished. Diagnosed by instrumenting `Channel.enqueue()` to count
      total legs per channel and comparing against hand-derived expected
      counts: channel 0 came up short by exactly one nudge-leg's worth
      (32 = 8 missing nudges x 4 enqueues/nudge) out of an expected 128,
      confirming legs were being dropped, not just mistimed. Fixed with
      `loadedChannelsEager`, a plain `Set` updated synchronously the
      instant a pick_up_tips/drop_tips event is *processed* (in
      `handleOpEvent()`, before the animation is even queued), decoupled
      from the animation-timed visual flag entirely.

      Verified live: reinstrumented `enqueue()` to log total legs per
      channel -- after the fix, channel 0 shows exactly 128 and channels
      1-7 each show exactly 104, matching hand-derived expected counts
      precisely (both wrong before the fix: 96 and 56). Recorded all 8
      channels' x every 50ms across the *entire* protocol afterward: 0 of
      2777 samples showed any spread between channels -- every channel
      stayed exactly arm-synchronized the whole run, a strictly stronger
      result than round 15's per-pass-only guarantee.
- [x] **Tip size by transfer volume.** Added `tip_rack_for_volume()`
      (1-50uL/50-300uL/300-1000uL -> 50/300/1000uL tip racks, picking the
      smallest tip that comfortably holds a volume, matching real
      practice) and three tip racks on one carrier. All of this demo's
      real volumes (5-200uL) only ever need the 50uL and 300uL racks; the
      1000uL rack is present for completeness/future volume changes but
      unused this run.
- [x] **Tip color by capacity.** `node["tip_max_volume_ul"]` (from
      `Tip.nominal_volume`) now flows through the same two paths
      `tip_length_mm` already used: `scene.py`'s `_inject_tip_info()`
      (renamed from `_inject_tip_lengths()`, now reading one representative
      tip once instead of two separate lookups) for resting tips, and
      `events.py`'s `channel_ops_event()` for a channel's carried tip.
      Frontend gained `tipColorForVolume()` (<=50 pink, <=300 yellow,
      otherwise white) used everywhere a tip's "present" color is set
      (`tipVisual()`, `Channel.setTip()`), replacing the old flat
      `TIP_PRESENT_COLOR` constant; a resting tip_spot's capacity is known
      once at scene-build time and cached on its `resourceIndex` entry
      (`tipMaxVolumeUl`) rather than re-sent on every state update, since
      -- unlike a channel, which switches tips all run -- a given rack
      position always holds the same tip model. Legend updated to show
      all three capacity colors.

      Verified live: a fresh scene shows the three tip racks rendering
      pink/yellow/white (`f48fb1`/`ffd54f`/`ffffff`) with `tipMaxVolumeUl`
      50/300/1000 exactly.
- [x] **Deck reposition.** Reservoir carrier to rails=2; dna_stock and
      te_diluent each get their own 32-tube carrier (only site 0 used) at
      rails=7 and rails=8 respectively. Tip and plate carriers moved to
      rails=9 and rails=15 to make room, verified collision-free via
      `assign_child_resource` (which raises on overlap) before writing the
      final script.

      Verified live: `reservoir_carrier_1`/`dna_stock_carrier`/
      `te_diluent_carrier`/`tip_carrier_1`/`plate_carrier_1` report world x
      122.5/235/257.5/280/415 -- exactly rails 2/7/8/9/15.

## Review round 17 (2026-08-19)

User correction on round 16's deck reposition, plus two new asks: "slot"
meant a site *within* a carrier, not a deck rail -- reservoir to slot 2 of
its carrier, tubes to slots 7 and 8 of theirs, with the carriers themselves
moved back to their original rail positions; dispense the higher-volume
PicoGreen reagent before the smaller sample/standard volume; and drop the
1000uL tip rack since nothing in this protocol ever needs it.

- [x] **Rail-vs-slot fix.** Round 16 read "slot 2"/"slot 7 and 8" as deck
      rails and repositioned four carriers to make room. Reverted all four
      carriers to round 15's original rails (tip=1, plate=7, reservoir=13,
      tube=14) and, instead, indexed *into* the carriers: `reservoir_
      carrier[1] = picogreen_reservoir` (site 2, 1-indexed) and a single
      `tube_carrier` (collapsing round 16's two separate 32-tube carriers
      back into one, matching the original request) with `tube_carrier[6]
      = dna_stock` / `tube_carrier[7] = te_diluent` (sites 7 and 8,
      1-indexed).
- [x] **Reagent dispense order.** Swapped the two final per-column loops so
      the 195uL PicoGreen-working-solution transfer (300uL tips) now runs
      before the 5uL sample/standard transfer (50uL tips) for every
      column -- the larger volume lands first, so the small sample volume
      dispenses into (and mixes with) a substantial existing volume rather
      than the reverse.
- [x] **Removed the unused 1000uL tip rack.** Nothing in this protocol
      pipettes above 200uL, so `tip_rack_for_volume()` went back to a
      2-tier 50/300uL function and `hamilton_96_tiprack_1000uL_filter` was
      dropped from both the deck and the import list entirely.

      Verified live end-to-end: deck assigns without collision at the
      reverted rails; `resourceIndex` confirms `dna_stock_100nguL`/
      `te_diluent` sit in `tube_carrier_1`'s site-6/site-7 holders and
      `picogreen_reservoir` in `reservoir_carrier_1`'s site-1 holder
      (all 1-indexed-to-0-indexed as expected); the event log shows each
      column's 195uL PicoGreen dispense preceding its 5uL sample dispense;
      no tip name in the entire run ever reports a 1000uL/1065uL capacity
      (only the 50uL/60uL and 300uL/360uL tiers appear); the protocol
      finishes with no errors and every tracked volume exactly matches
      hand-derived expectations -- all 32 assay wells at 200uL, standard
      column rows A-F/H at 95uL and row G (the last dilution step's
      target) at 195uL, `dna_stock`/`te_diluent` drawn down to 300uL each,
      and `picogreen_reservoir` drawn down to 3760uL.

## Review round 18 (2026-08-19)

Three smaller fixes: round volume displays to 1 decimal place; make
troughs and tubes show their volume on hover too, not just wells; and a
report that the multichannel pipettes' Y order looks reversed at their
starting position.

- [x] **Volume rounding.** The hover tooltip's volume line already rounded
      the live volume to 1 decimal (`entry.volume.toFixed(1)`) but not the
      max-volume half of the fraction, which can come straight out of
      PyLabRobot as a long float -- e.g. `azenta_96_wellplate_200uL_Vb_
      4titudeframestar`'s real declared capacity is `203.52938905975373`,
      not a round 200 or 203.5. Added `.toFixed(1)` there too.
- [x] **Trough/tube volume on hover.** The tooltip's volume line was gated
      on `category === "well"` only; troughs and tubes already had live
      `entry.volume`/`entry.maxVolume` tracking (round 15's `volumeVisual()`
      fill-level coloring was already category-agnostic, "Container-shaped
      'has a volume' state" per its own comment) -- the tooltip just never
      surfaced it. Broadened the check to `well`/`trough`/`tube`.
- [x] **Reversed channel Y order at rest, confirmed and fixed.** `Channel`'s
      constructor set `pos.y = index * CHANNEL_Y_SPACING` -- channel 0 at
      the lowest (most "front", -y) offset, channel 7 at the highest (most
      "back", +y). Real Hamilton/PyLabRobot channel numbering runs the
      other way: an 8-channel `drop_tips`' own per-channel trash offsets
      (already visible in every prior round's event log/server output)
      report `+31.5, +22.5, ..., -31.5` for channels 0-7, i.e. channel 0 is
      the back-most channel and increasing index moves toward the front.
      The parked/rest row was mirrored front-to-back relative to that.
      Fixed by negating: `pos.y = -index * CHANNEL_Y_SPACING`.

      Verified live: hovering `sample_plate_well_A1` (well) now reads
      "50.0 / 203.5 &micro;L" instead of the raw unrounded float;
      hovering `picogreen_reservoir` (trough) and `te_diluent` (tube) now
      show "10000.0 / 60000.0 &micro;L" and "300.0 / 1500.0 &micro;L"
      respectively, where before they showed no volume line at all.
      Queried the parked channels' world positions directly after a fresh
      scene load: channel 0 sits at the highest (most "back") Y and
      channel 7 at the lowest (most "front"), matching the real per-
      channel trash-offset convention instead of the old mirrored order.

## Review round 19 (2026-08-19)

User request: let the PicoGreen/sample mixing ratio and the sample count be
entered in the HUD, next to Start, instead of hardcoded -- sample volume
1-20uL (PicoGreen working solution makes up the rest of a fixed 200uL
total), sample count 1-88 placed column-wise on the sample plate from A1.
Locked once started; a Reset button (locked until the run finishes) starts
the whole thing over with new values.

- [x] **Library support for params + reset, in `VisualizerServer`/
      `VisualizerBackend`, not just this one demo.** `"start_protocol"` now
      carries an opaque `params` dict, handed back verbatim by
      `wait_for_start()` -- the server doesn't know or care what's in it,
      same as argv or a config file would be to any other script. Guarded
      exactly like before: a second `"start_protocol"` once one's been
      accepted is ignored server-side, so a run's params can't change
      mid-run regardless of what the browser sends. Added
      `mark_finished()`/`wait_for_reset()`/`reset_for_new_run()` for the
      "start over" half -- `"reset"` is only honored server-side once
      `mark_finished()` has been called (matches "lock the reset button
      during execution" exactly, and isn't just a UI nicety -- a
      hand-crafted `{"action": "reset"}` sent mid-run is ignored too).
      `reset_for_new_run()` clears scene/state/event history and broadcasts
      a `"reset"` message so every connected client's HUD (not just the one
      that clicked) goes back to its pre-run state. Also added
      `VisualizerBackend.broadcast_state()`, a public split-out of what
      `wait_for_start()` already did internally -- needed here because this
      demo's sample-count-dependent pre-fill can't happen until *after*
      the params arrive, but tip_spot/well/trough/tube state only pushes
      live via that one-shot broadcast, not a live callback (see
      `_LIVE_CALLBACK_EXCLUDED_CATEGORIES`), so skipping it would leave the
      HUD showing the pre-fill's *previous* (empty) state forever.
- [x] **`examples/picogreen_demo.py` restructured around a `while True:`
      loop.** Each pass builds a completely fresh deck/backend/
      `LiquidHandler` (`build_deck()`) rather than hand-resetting the
      previous run's PyLabRobot trackers in place -- simpler and more
      certainly correct, and no different from what actually restarting the
      script would give you, just without restarting the process. Sample
      placement is column-wise from A1 via `sample_column_groups()`: full
      8-row columns until the last, which may be partial (e.g. 20 samples
      is 2 full columns + 4 more rows of a 3rd). 88 is exactly 11 full
      columns, so the standard curve's column 12 is never reachable
      regardless of what a client sends -- enforced by clamping, not just
      documented.
- [x] **A second 300uL tip rack, because the first one really would run
      out.** A 96-tip rack only has 12 columns. At the maximum sample count
      this protocol can need up to 13 fresh 300uL columns in one run (1 for
      the dilution stage + up to 12 sample/standard transfer stages) --
      one more than a single rack provides. `rack_column_stream()`
      generalizes the existing fresh-tip-column idiom to roll over to a
      second rack once the first's 12 columns are exhausted, instead of
      raising `StopIteration`/a PLR "no tip" error partway through an
      88-sample run.

      Verified live, two runs back to back through a full Reset cycle:
      (1) baseline params (24 samples/5uL, matching round 17's already-
      verified behavior) finished with all 32 assay wells at exactly
      200uL, the standard curve at 95/95/95/95/95/95/195/95uL, and the
      reservoir drawn down to exactly the hand-derived 500uL remaining;
      clicking Reset cleared the event log, rebuilt a fully-stocked fresh
      scene, and re-enabled both inputs and Start. (2) The worst case,
      88 samples at 20uL each (180uL PicoGreen), run immediately after:
      every one of the 96 assay wells (88 sample + 8 standard) landed at
      exactly 200uL, all 88 sample-plate source wells drawn down to
      exactly 30uL (50uL prefill - 20uL pulled), and the reservoir's
      remaining volume again matched the hand-derived 500uL exactly.
      Grepping the two runs' combined tip-rack usage confirmed the
      rollover worked precisely as designed: rack A got 136 tip-spot
      pickups (run 1's 5 columns + run 2's first 12), rack B got exactly
      8 (run 2's 13th, overflow column) -- not one spot more or less than
      the hand-derived expectation. No 1000uL tip, malformed volume, or
      backend error appeared in either run.

## Review round 20 (2026-08-19)

Three smaller fixes: always leave a known 1000uL of PicoGreen behind
instead of an unpredictable amount; lock Replay during a run the same way
Reset is locked; and make Replay/Reset visually distinct colors so they
aren't confused for each other.

- [x] **Fixed 1000uL PicoGreen residual.** The reservoir's starting fill
      was `(needed for this run) + 500uL margin` -- a guess at the
      *starting* amount, not a promise about what's left afterward.
      Renamed to `RESIDUAL_PICOGREEN_UL = 1000.0` and reworded the math the
      same way: `required = (sample_count + 8) * picogreen_volume +
      RESIDUAL_PICOGREEN_UL`, so whatever a given run actually consumes,
      exactly 1000uL remains once it's done -- a guaranteed residual, not
      a starting-fill margin that happened to leave some amount over.
- [x] **Replay locked during a run, server-side and in the HUD.** Replaying
      over a live run would interleave replayed events with live ones on
      *every* connected client, not just the one that clicked -- the same
      class of problem "Reset locked during execution" already exists to
      prevent. Guarded the "replay" websocket action the same way "reset"
      already is (`not self._start_event.is_set() or self._finished_event.
      is_set()` -- allowed before a run starts and again once it's
      finished, never mid-run), and disabled the HUD button in the same two
      places Reset's lock lives: optimistically on Start, authoritatively
      on every connected client's "start_status", re-enabled on
      "run_status: finished" alongside Reset.
- [x] **Replay (blue) and Reset (amber) get distinct tinted backgrounds.**
      Previously both were the same flat neutral-dark button style as
      everything else in the HUD, only distinguishable by their labels.

      Verified live: sent a raw `{"action": "replay"}` over a second
      websocket connection while a run was in progress and confirmed it
      was silently ignored -- that connection received exactly the same
      555 sync messages a connection making *no* replay request also
      received, proving the server actually rejected it rather than the
      UI just hiding the button. After the run finished, the reservoir's
      `resourceIndex` volume read exactly 1000uL, and both Replay and
      Reset showed as enabled with their own distinct colors (confirmed
      by screenshot) rather than the flat gray every other HUD control
      uses.

## Review round 21 (2026-08-19)

User request: change the aspiration flow color from blue to orange.

- [x] **Split the single shared flow texture into two.** A channel's
      mid-pipetting tip glow (`Channel.flowPulse()`) used one shared blue
      gradient texture for both directions -- aspirate just scrolled it one
      way, dispense the other, so aspirate and dispense looked identical
      apart from which way the stripes moved. `createFlowTexture()` now
      takes its two gradient-stop colors as parameters instead of having
      them hardcoded, and there are two module-level base textures built
      from it: `FLOW_TEXTURE_ASPIRATE` (orange, `#ffe3bf`/`#c4752f`) and
      `FLOW_TEXTURE_DISPENSE` (blue, `#bfeaff`/`#2f8fc4`, the original
      colors, unchanged). Each `Channel` clones both once (so its own
      scroll-offset animation can't fight another channel's, same reason
      the single shared texture was cloned per-channel before), and
      `flowPulse(direction)` just picks between the two clones by sign
      instead of always using the one texture it used to.

      Verified live, at the texture level rather than by eyeballing a
      screenshot (a flow pulse only lasts ~550ms, awkward to catch on
      camera reliably): patched a polling loop into the live page reading
      each channel's `tipMesh.material.map` (only non-null mid-pulse) and
      sampling the underlying canvas's actual rendered pixel color.
      Caught both directions live across a real run: a dispense pulse
      read back `rgb(51,145,197)` (`#3391c5`, matching the unchanged blue
      stops exactly) and an aspirate pulse read back `rgb(197,120,51)`
      (`#c57833`, matching the new orange stops exactly) -- not just "some
      color changed," the literal on-screen pixels for each direction.

## Stretch / explicitly deferred (not v1)

- [ ] Event capture-to-file (durable, survives a process restart) +
      scrubbing/seek UI — in-memory replay from Phase 4 covers the common
      "I missed it" / "watch that again" case within one run
- [ ] 96-head visualization
- [ ] iSWAP / CO-RE gripper + plate-move animation
- [ ] Hamilton Vantage support
- [ ] Firmware-accurate motion timing

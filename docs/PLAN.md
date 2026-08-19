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

## Stretch / explicitly deferred (not v1)

- [ ] Event capture-to-file (durable, survives a process restart) +
      scrubbing/seek UI — in-memory replay from Phase 4 covers the common
      "I missed it" / "watch that again" case within one run
- [ ] 96-head visualization
- [ ] iSWAP / CO-RE gripper + plate-move animation
- [ ] Hamilton Vantage support
- [ ] Firmware-accurate motion timing

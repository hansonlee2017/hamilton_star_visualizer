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

## Stretch / explicitly deferred (not v1)

- [ ] Event capture-to-file (durable, survives a process restart) +
      scrubbing/seek UI — in-memory replay from Phase 4 covers the common
      "I missed it" / "watch that again" case within one run
- [ ] 96-head visualization
- [ ] iSWAP / CO-RE gripper + plate-move animation
- [ ] Hamilton Vantage support
- [ ] Firmware-accurate motion timing

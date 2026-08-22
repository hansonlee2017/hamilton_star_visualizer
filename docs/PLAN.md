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

## Review round 22 (2026-08-19)

Three requests: reuse tips during the PicoGreen working-solution dispense
(nothing in the assay plate to contaminate); change the aspirate flow color
from orange to red; and, after establishing that real PyLabRobot traverse-
height kwargs exist but have no effect under this project's Chatterbox
backend or fixed-duration frontend animation, actually wire them through so
the visualizer *does* show a difference when a protocol requests a shorter
rise/retract.

- [x] **PicoGreen tip reuse.** One tip pick-up now covers the *entire*
      PicoGreen stage instead of one fresh pick-up/discard per column --
      every aspirate draws from the same single reservoir and every
      dispense lands in a still-empty assay well, so there's no cross-
      contamination risk a fresh tip would guard against (unlike the
      sample/standard transfer loop right after it, which still gets a
      fresh tip per column since each source there really is different).
      This incidentally erased the round-19 tip-rack-capacity problem it
      was fixing: with reuse, the PicoGreen stage only ever needs 1 fresh
      300uL column total (not up to 12), so the whole run only ever needs
      2 (1 there + 1 for the dilution stage) -- nowhere near a single
      rack's 12. Removed the now-unnecessary second 300uL rack
      (`tip_rack_300uL_b`) added in round 19, restoring a 2-rack deck.

      Verified live at 88 samples/20uL (the case that used to need up to
      13 columns): grepping the two 300uL tip-column pickups (dilution +
      the single PicoGreen pick-up) confirmed exactly 16 tip-spot mentions
      total (2 columns x 8 channels) across the whole run, and the
      protocol still finished with every volume exactly matching hand-
      derived expectations.
- [x] **Aspirate color: orange -> red.** `FLOW_TEXTURE_ASPIRATE`'s gradient
      stops changed from `#ffe3bf`/`#c4752f` to `#ffd6d6`/`#c73a3a`.

      Verified live with the same pixel-sampling technique as round 21
      (screenshotting a ~550ms pulse reliably isn't worth the attempts):
      polled a live run's channel tip materials and read back
      `rgb(200,62,62)` for an active aspirate pulse -- unambiguously red,
      not orange -- while dispense still read back the unchanged
      `rgb(51,145,197)` blue.
- [x] **Real traverse-height kwargs, actually wired through to the
      animation.** Research first (see the "Speed research" discussion
      this round is based on): `STARBackend.aspirate()`/`dispense()` both
      accept real Hamilton firmware kwargs --
      `minimum_traverse_height_at_beginning_of_a_command` (rise-to height
      before a command) and `min_z_endpos` (retract-to height after) --
      defaulting to a conservative global `_channel_traversal_height`
      (245mm) that PLR itself overrides down in at least one place ("we
      don't want to move channels up, we are already above the liquid").
      A real, legitimate optimization -- but inert in this project as
      found: `LiquidHandlerChatterboxBackend` has no motion/timing model
      at all (just prints a table row), and the frontend's rise/retract
      legs used a single fixed `restZ` target with fixed `RISE_MS`/
      `RETRACT_MS` durations, never reading anything from the op event
      that could change either. Passing the kwargs through unchanged
      would've been pure decoration -- extra printed Chatterbox columns,
      nothing else.

      Wired for real instead: `picogreen_demo.py`'s PicoGreen loop now
      passes both kwargs on its aspirate (reservoir -- never moves) and
      dispense (assay plate) calls, computed from each resource's own
      `get_absolute_location(z="top")` plus a 5mm clearance margin, not
      guessed constants. `VisualizerBackend.aspirate()`/`dispense()` peek
      (not pop) `minimum_traverse_height_at_beginning_of_a_command`/
      `min_z_endpos` out of `**backend_kwargs` and hand them to
      `events.py`'s `channel_ops_event()`, which embeds them as top-level
      `traverse_height_mm`/`end_height_mm` fields on the "op" event (one
      value for the whole multi-channel command, matching the real
      firmware semantics -- not per-channel). `None` (the default -- every
      other call site) omits both fields entirely, so every op that
      doesn't set these kwargs is byte-for-byte unaffected.
      `animateChannelOp()` now rises to and retracts from these heights
      instead of the fixed `restZ` when present, clamped to
      `[entry.z, restZ]`, *and* scales `RISE_MS`/`RETRACT_MS` by what
      fraction of the nominal working-depth-to-restZ span this op's height
      actually needs (floored at `MIN_LEG_MS=40` so an aggressive override
      never collapses to a literal same-frame teleport) -- a lower
      traverse height is both visibly lower and measurably faster, not
      just geometrically different.

      Verified live end-to-end, including through a full Reset cycle
      (proving the heights are recomputed fresh from the *new* deck's
      resources each run, not cached): captured real "op" events via a
      raw websocket replay and confirmed `traverse_height_mm`/
      `end_height_mm` on the PicoGreen reservoir aspirate read exactly
      `234` (`229.0` real top + 5mm) and on the assay-plate dispense read
      exactly `202.32` (`197.32` real top + 5mm) -- both matching the
      hand-derived resource geometry exactly, identically on a second run
      after Reset. Confirmed a freshly-parked channel's rest height is
      `384.95mm`, well above both overrides, so the reduction is real, not
      a no-op clamp. Computed the resulting durations by hand from the
      captured working depths: the reservoir aspirate's rise/retract drops
      from 350ms to ~100ms (a ~71% reduction), the assay-plate dispense's
      drops to the 40ms floor (~89%), while the untouched sample/standard
      loop's ops still take the full 350ms.
      Also found (via this session's own diagnostic websocket testing, not
      part of this feature) a pre-existing gap where an abrupt client
      disconnect mid-replay can raise an uncaught `RuntimeError` in
      `server.py`'s websocket loop instead of being caught like a normal
      `WebSocketDisconnect` -- flagged as a separate background task
      rather than fixed here, since it's unrelated to what this round
      changed.

## Review round 23 (2026-08-19)

User report: a long delay between the serial dilution and PicoGreen setup
stages; during PicoGreen dispense, tips appear to pierce through wells and
clip through the reservoir, with the pipette seeming to *raise* rather
than lower during dispense; and a request to extend the round-22 traverse-
height optimization to the sample/standard transfer, standard/TE
aspiration from their tubes, and the serial dilution phases.

- [x] **Root-caused and fixed the piercing/clipping bug -- a frame
      mismatch, not a cosmetic issue.** `traverseHeightMm`/`endHeightMm`
      are expressed in *tip-point* terms (how high the tip's own point
      should clear a resource by), matching `entry.z`. But every leg in
      `animateChannelOp()` moves the *channel body origin*, which sits
      *above* the tip's point by the tip's own length (`targetZ() =
      entry.z + tipLength`) -- round 22 set the rise/retract Z targets to
      the raw tip-point height directly, never adding that offset. For the
      assay-plate dispense specifically, the real required body-origin
      depth (~246.55mm, `entry.z` + a 300uL tip's ~59.9mm) ended up
      *deeper* than the buggy rise/retract target (202.32mm, un-offset) --
      inverting the sequence: the leg labeled "rise" (202.32) was actually
      *below* the leg labeled "descend" (246.55), so the channel visibly
      moved *up* where it should move *down*, and while traveling at that
      wrong height the tip's own rendered point sat below the plate's rim
      -- exactly "pierce through the well." Fixed by converting
      `traverseHeightMm`/`endHeightMm` to body-origin terms (`+ this op's
      own tip length`) before using them, resolved lazily via `targetZ()`
      itself rather than a separately-captured value -- for the same
      staleness reason `targetZ()` was already a function (`ch.tipLength`
      can't be read at enqueue time; see `enqueue()`'s docstring). Also
      extended `Channel.update()`/`enqueue()` to support a duration
      *function* (`(from, target) => number`), not just a number, so the
      leg-duration fraction can use the same freshly-resolved values
      instead of being computed too early.

      Verified two ways: (1) by hand, using the exact real numbers from a
      live run -- with the fix, the reservoir aspirate's rise
      (body-origin) resolves to 293.9mm, comfortably above its own descend
      depth (233.45mm) by 60.45mm (previously a broken ~0.55mm gap), and
      the tip's own rendered height during travel comes out to exactly
      234mm -- the intended 5mm above the reservoir's 229mm rim, not 55mm
      *below* it. (2) live: polled channel 0's actual rendered Z during a
      real run and confirmed samples landing within 3mm of both corrected
      values (293.9, 262.22), with the trajectory never exceeding `restZ`
      or dropping below any real working depth -- no inversion signature
      anywhere in the trace.
- [x] **Extended the traverse-height optimization to every phase named**:
      standard/TE tube aspiration, the serial dilution's own aspirate/
      dispense pairs (both within the sample plate), and the sample/
      standard transfer loop's aspirate (sample plate) and dispense (assay
      plate). Moved the five per-resource heights (sample plate, assay
      plate, reservoir, DNA stock tube, TE tube) to one shared computation
      near the top of the run instead of a local copy inside just the
      PicoGreen loop.
- [x] **Shrank the post-dilution wait to match.** The old
      `dilution_stage_legs * 1.6s * 1.3` treated all 24 legs as full-height
      (~1.6s each); now only `pick_up_tips`/`discard_tips` (2 of the 24)
      still rise/retract to the full global safe height -- the other 22
      all carry a traverse-height override, so their rise/retract legs are
      shorter. Reworded as a weighted estimate (2 legs @ 1.6s + 22 legs @
      ~1.1s) with the same 1.3x safety margin round 9 established, rather
      than a uniform 1.6s/leg applied to legs that no longer take that
      long.

      Verified live: the full run (dilution -> PicoGreen -> sample/
      standard transfer) completed with all 32 assay wells at exactly
      200uL, the standard curve at 95/95/95/95/95/95/195/95uL, and the
      reservoir at exactly the designed 1000uL residual -- no regressions
      from moving/duplicating the height computations or reworking the
      wait's derivation.

## Review round 24 (2026-08-19)

User report: during the serial dilution phase, only the active pipette
(channel 0) appears to move -- channels 1-7, which should be dragged
along, look frozen.

- [x] **Root-caused: round 23's height reduction broke drag-along's
      exact-duration invariant.** `nudgeChannel()` (the idle/dragged-along
      channel path) already carried an explicit, load-bearing comment and
      a "confirmed live" note from when drag-along was first built: every
      channel in one gantry pass -- active or idle -- has to take the
      *exact* same total duration, because each channel's queue is
      independent FIFO, and a channel that finishes early starts its
      *next* pass's legs while a slower one is still mid-leg, breaking the
      whole arm's visible sync. Round 23 shortened the *active* channel's
      rise/retract duration when a traverse-height override applied, but
      `nudgeChannel()` still always used the old fixed `RISE_MS`/
      `RETRACT_MS` -- exactly the violation that comment warned against,
      just in the opposite direction from the bug it was originally
      written to prevent (now the *active* channel races ahead of the
      *idle* ones, instead of the reverse). Over many fast, tightly-looped
      serial-dilution steps (each now much shorter thanks to round 23),
      channels 1-7 fell further and further behind every iteration,
      reading as "frozen" relative to channel 0's now much faster cycle.
- [x] **Fixed by sharing one duration across the whole pass.** Extracted
      `traverseLegZ()`/`traverseLegDuration()` as standalone functions
      (previously private closures inside `animateChannelOp()`) so
      `animateChannelGroupOp()` can compute a pass's rise/retract duration
      *once*, from one representative active entry, and hand the identical
      value to both `animateChannelOp()` (every active channel in the
      pass) and `nudgeChannel()` (every idle one) -- guaranteeing bit-for-
      bit equal totals regardless of height overrides, restoring the
      invariant instead of just patching the one symptom. `nudgeChannel()`
      also now converts `traverseHeightMm`/`endHeightMm` to a body-origin
      Z using its *own* channel's tip length (matching
      `animateChannelOp()`'s round-23 fix), in case an idle channel is
      ever carrying a different tip model than the pass's active one --
      not currently possible in this demo, but the math doesn't assume it.

      Verified live: polled all 8 channels' rendered Z every 100ms across
      a full run and found 245 of 248 samples where channel 0 was away
      from `restZ` (i.e. doing real work) also showed channels 1-7 at the
      *identical* Z, moving in exact lockstep -- not frozen at `restZ`
      (the pre-fix symptom). Full run still finished with every volume
      exactly correct, confirming the shared-duration refactor didn't
      change anything about the actual pipetting.

## Review round 25 (2026-08-19)

User question: does the visualizer actually need to animate close to real
time, and could `picogreen_demo.py` skip `asyncio.sleep()`/wait entirely by
generating Chatterbox text and parsing it for animation instead? Followed
by: just remove the `asyncio.sleep()` calls.

- [x] **Assessed the "parse Chatterbox text" idea and didn't take it.**
      This was already considered and rejected when the project was
      designed -- `visualizer_backend.py`'s own docstring explains why:
      `VisualizerBackend` wraps the `LiquidHandlerBackend` interface to
      intercept the same typed PyLabRobot objects PLR itself uses
      internally (exact resource objects, real float volumes, real tip
      geometry), rather than re-deriving them from text meant for human
      eyeballs. Concretely confirmed why text-parsing would be worse, not
      simpler: `chatterbox.py` truncates its own printed kwarg columns to
      15 characters (`minimum_traverse_height_at_beginning_of_a_command`
      prints as `ng_of_a_command`) and resource names to 20-30 characters
      -- a parser would lose exactly the data round 23's traverse-height
      feature depends on, and would need its own separate copy of the deck
      resource tree to resolve names back into anything with real Z
      geometry anyway, which is what `VisualizerBackend` already does more
      directly.
- [x] **Removed every `asyncio.sleep()` call from `picogreen_demo.py`.**
      Confirmed first that none of them were ever load-bearing for
      anything the browser shows: each channel's animation queue is
      already fully decoupled from backend timing (independent per-channel
      FIFO, built specifically around "events arrive faster than they
      animate" -- see round 16's drag-along/staleness work). Removing the
      per-stage `0.2`/`0.3`s pacing sleeps and the whole dilution-stage
      wait (with its now-obsolete leg-counting rationale comment) doesn't
      change anything about tip/volume correctness, which was always
      enforced by PLR's own `await`ed call ordering, never by elapsed
      real time. The one real cost, noted in the module docstring:
      `VisualizerServer.replay()` paces itself off the *original* gaps
      between when events were sent, so a replay of a run recorded without
      any pacing plays back in a few seconds rather than at anything
      resembling the original pace -- an accepted, explicit tradeoff, not
      an oversight.

      Verified live: a full run finished (no errors) essentially
      instantly on the backend side, and once the browser's animation
      queue -- now carrying its entire backlog at once rather than
      trickling in between paced sends -- caught up, every volume was
      still exactly correct (32 assay wells at 200uL, standard curve at
      95/95/95/95/95/95/195/95uL, reservoir at the designed 1000uL
      residual), confirming the sleeps were cosmetic pacing only, never a
      correctness dependency.

## Review round 26 (2026-08-19)

User report: channels still not synchronized during pipetting steps, even
after round 24's fix. Suggestion: stop scaling rise/retract *duration* to
match the traverse-height reduction -- keep the Z-target change, drop the
timing change, since a real Hamilton's channels move at a fixed speed
regardless of distance anyway. Also asked whether `asyncio.gather()`
could sync the animations from the Python side instead.

- [x] **Answered the `asyncio.gather()` question.** No -- the desync is
      entirely a browser-side concern. The frontend builds its own
      animation timeline from the stream of "op" events; it has no
      visibility into how the Python script sequenced its own `await`
      calls, so concurrency on the backend can't influence it either way.
      (It also wouldn't be semantically right for the diluent-distribution
      loop specifically, which is deliberately sequential -- only one
      channel fits the tube's ~10mm opening at a time.)
- [x] **Took the suggested simplification -- and it's also the fix.**
      Round 24's "shared duration per pass" approach reduced but didn't
      eliminate the risk: separate op calls that each compute their own
      duration from their own representative entry (e.g. the diluent-
      distribution loop's 7 separate single-channel aspirate calls, each
      against a tube whose liquid level -- and so `entry.z` -- drifts
      slightly lower as it drains) could still land on slightly different
      numbers. Removed rise/retract duration-scaling entirely --
      `traverseLegDuration()`, `MIN_LEG_MS`, and the "representative
      active entry" duration-sharing in `animateChannelGroupOp()` are all
      gone. Every leg, active or idle, always takes its fixed nominal
      `RISE_MS`/`RETRACT_MS` now, exactly as before round 23 -- only the Z
      *target* still reflects a traverse-height override (`traverseLegZ()`,
      unchanged, still the round-23 body-origin-frame fix). A real
      Hamilton's channels don't move faster over a shorter distance
      anyway, so this wasn't even sacrificing realism -- just an animation
      embellishment that turned out to be the actual source of the
      remaining desync. With duration always a fixed constant, there's no
      computation left that could ever disagree between channels.

      Verified live: polled all 8 channels' rendered Z every 100ms across
      a full run -- zero samples where an idle channel stayed frozen at
      `restZ` while another channel was doing real work (the reported
      symptom), and the whole Z trace stayed within sane bounds (never
      below a real working depth, never above `restZ`) confirming the
      round-23 piercing/clipping fix is still intact. Full run still
      finished with every volume exactly correct.

## Review round 27 (2026-08-19)

User report, three instances of the same pattern: after `pick_up_tips`
(TE transfer, sample transfer), the gantry drops in Z and clips the
carrier before finishing its move; after aspirating (PicoGreen transfer),
it drops in Z before moving in X/Y. In each case: "it should move to the
top of \[the destination\] before going down in Z."

- [x] **Root-caused: a rise-leg target computed from the destination
      alone, blind to where the channel actually starts.** A resource's
      traverse height (its own rim + clearance) only ever accounts for
      clearing *that* resource -- it says nothing about whatever the
      channel currently sits over, left there by the *previous* op. Since
      the rise leg runs *before* X/Y move (rise, then X, then Y, then
      descend -- see `animateChannelOp()`'s own leg order comment), a
      destination-only height could be *lower* than the channel's current
      position, and the leg would drop Z first, at the *old* X/Y, then
      translate horizontally at that now-too-low height -- clipping
      whatever's actually at the old position (a carrier wall, an
      adjacent tube) on the way. Concretely: after `pick_up_tips` (never
      traverse-optimized -- it retracts to the full global safe height),
      the next op's rise leg targeted its own resource's low height with
      no regard for the fact the channel was still sitting near-385mm up;
      after a PicoGreen aspirate's retract (up near the reservoir's own
      traverse height), the following dispense's rise leg targeted the
      assay plate's *lower* height the same blind way.
- [x] **Fixed by clamping every rise/retract leg's target against where it
      actually starts.** `traverseLegZ()` (used by both
      `animateChannelOp()` and `nudgeChannel()`) now takes a third bound in
      its `min(restZ, max(...))`: the incoming leg's own `from.z`, so the
      leg only ever rises or holds level before translating -- never dips.
      Needed passing `from` into the lazy Z-target resolution in
      `Channel.update()`, alongside the target itself (previously only
      `duration` functions got `from`; `target.z` functions were called
      with no arguments) -- extended, not replaced, so `target.z`
      functions that don't care (like `animateChannelOp()`'s own
      `targetZ()` for the descend/hold legs) just ignore the extra
      argument. All the real descending still happens only in the
      dedicated descend leg, once X/Y are already correct -- this doesn't
      change *that* geometry at all, only stops the rise leg from
      preemptively doing part of it early.

      Verified live: captured every channel's full (x, y, z) trajectory at
      50ms resolution across a complete run and scanned for the exact bug
      signature -- a sample where Z dropped by more than 1mm in the same
      step X or Y moved by more than 1mm. Found 3 such samples out of
      10,024 total, and all three were trivial (1-4mm) drops right at
      ~383-385mm -- essentially at `restZ` itself, not a real clipping-
      relevant depth, and consistent with ordinary easing-curve
      interpolation noise at a leg boundary rather than the reported bug.
      Full run still finished with every volume exactly correct.

## Review round 28 (2026-08-19)

User request: apply round 25's `asyncio.sleep()` removal to the other two
demos, `cherry_pick_demo.py` and `demo_protocol.py`.

- [x] **Removed every `asyncio.sleep()` from both scripts.** Same
      reasoning as round 25: the browser's animation queue is already
      fully decoupled from backend timing, so these were never load-
      bearing for anything the browser shows -- just cosmetic pacing (and,
      for `replay()`, original-gap preservation, now traded away the same
      way picogreen_demo.py already was). `demo_protocol.py`'s per-column
      loop also had a stale comment specifically justifying the pacing
      ("gives the browser's per-op animation... room to play out before
      the next event arrives") -- removed along with the sleeps, since
      that was never actually true (the animation queue was always
      independent of it). Both scripts gained the same short docstring
      note picogreen_demo.py already carries, pointing at the fuller
      reasoning there and at this round.

      Verified live: both finished with no errors, and once each browser's
      animation queue caught up, every volume was exactly correct --
      `demo_protocol.py`'s 3 columns each left source wells at 150uL (200
      - 50) and dest wells at 50uL; `cherry_pick_demo.py`'s source column
      landed at 110uL (150 - 40) and all 8 smiley-pattern wells at exactly
      40uL.

## Review round 29 (2026-08-19)

User request: a new demo drawing a simple picture on a 384-well square-well
plate, 50uL tips, a 60mL reservoir.

- [x] **`examples/pixel_art_demo.py`.** A 9x11 pixel-art heart bitmap
      (`HEART_BITMAP`, hand-drawn but verified left-right symmetric and
      64 cells filled -- exactly 8 batches of 8), centered on a 384-well
      plate's 16x24 grid. Each batch is one ordinary 8-channel
      `LiquidHandler` call -- aspirate from the one shared reservoir
      (`spread="wide"`) and dispense into up to 8 scattered wells at once,
      the same "let `planGantryPasses()` work out the real motion" idiom
      `cherry_pick_demo.py` already established. One tip pick-up covers
      the whole picture (same reuse reasoning as picogreen_demo.py's
      PicoGreen stage: same reservoir, always-empty destinations). Built
      from the start without `asyncio.sleep()`, matching round 25-28's now-
      established practice.
- [x] **Found and fixed a real bug in `events.py` while building it.**
      PyLabRobot's `Container.material_z_thickness` is a *property*, not a
      plain attribute -- for a resource that never had it set (several real
      labware definitions, including the plate this demo first tried),
      accessing it doesn't leave it merely absent, it actively raises
      `NotImplementedError`. `liquid_surface_point()`'s
      `getattr(resource, "material_z_thickness", None)` only rescues a
      *missing* attribute (`AttributeError`); a property raising something
      else propagates straight through regardless of the default given --
      crashing the very first dispense against such a plate. Fixed with an
      explicit `try/except (NotImplementedError, AttributeError)` instead.
- [x] **Diagnosed a real frontend rendering gap, then sidestepped it with
      real custom labware instead of patching around it.** The demo's
      first plate choice, PyLabRobot's `HalfDeepWell_384_Well` (a
      Tecan-specific class, the closest available catalog match at the
      time), reports `category="tecan_plate"`, not the generic `"plate"`
      `frontend/main.js`'s `THIN_CATEGORIES`/`CATEGORY_COLORS` look up --
      so it fell through both the thin-base treatment and the purple
      color, rendering as a solid full-height gray box burying its own
      wells instead of the thin purple base every other plate gets. Per
      user direction, fixed not by teaching the frontend about this one
      more category, but by giving this demo a real, correctly-categorized
      plate instead: `examples/custom_labware.py`'s
      `cellvis_384_wellplate_120uL_Fb`, a plain `Plate` (category always
      `"plate"`, regardless of brand) built the same way PyLabRobot's own
      catalog entries are, with real dimensions -- footprint, well pitch,
      square well size (3.3mm, derived exactly from the product's stated
      10.89mm^2 bottom area), max volume (120uL), and cover-glass
      thickness/offset -- taken from Cellvis's product page and cross-
      checked against their own engineering drawing (every number that
      appears in both sources agrees, including a non-obvious one: the
      drawing's "11.38" well-depth callout is exactly what plate height -
      glass offset - glass thickness computes to from the product page's
      separately-stated numbers). This is a real, still-open gap for any
      *other* plate PyLabRobot categorizes outside its own convention --
      not fixed here, since a real custom part sidestepped it for this
      demo specifically.

      Verified live: the new plate's `category` reads `"plate"` and
      renders with the expected thin purple base (`0x6a5a94`) and the
      heart visibly legible in the well grid on screen. The full run
      finished with no errors, and all 384 wells matched the bitmap
      exactly (64 filled at 20uL, 320 empty) once the animation queue
      caught up, with the reservoir drawn down to exactly the expected
      3720uL (5000 - 64*20).

## Review round 30 (2026-08-19)

User request: rework `pixel_art_demo.py` from a single 384-well heart to 5
separate 96-well Corning plates on one plate carrier, each painting one
letter of "ROCHE" in portrait mode, using 300uL tips with a real
multi-dispense pattern (aspirate 300uL once, dispense 30uL up to 10 times
before re-aspirating), with dispense batches grouped by plate column.
Three follow-up rounds of live feedback arrived as the rework was
verified; all are covered below.

- [x] **`examples/pixel_art_demo.py` rewritten end to end.** Five bold
      block-letter bitmaps (`LETTERS`, 12 rows x 8 columns each --
      R=44/O=34/C=26/H=56/E=58 filled cells, hand-designed and verified via
      an ASCII-render script before use), one `cor_96_wellplate_360uL_Fb`
      per letter on `PLT_CAR_L5AC_A00` (confirmed to have exactly 5 sites),
      `hamilton_96_tiprack_300uL_filter` tips. `letter_row_batches()` maps
      each bitmap row onto one plate column and each bitmap column onto one
      plate row letter -- since a 96-well plate is natively wider (12
      columns) than tall (8 rows), this puts the letter's tall axis on the
      plate's column axis, its width axis on the plate's row axis: portrait
      orientation without physically rotating the plate. Every bitmap row
      is <=8 cells wide and lands in a single plate column, so grouping
      dispenses by bitmap row satisfies both the 8-channel limit and the
      user's "group by column for faster dispense" follow-up with no extra
      rechunking logic. `DISPENSES_PER_ASPIRATE = 10` (300uL / 30uL) chunks
      each letter's 12 rows into 2 aspirate cycles.
- [x] **Bug: reused tips overflowed between aspirate cycles (found live,
      fixed).** A bitmap row's width varies 3-8 cells, so a channel not
      needed on every row of a 10-row cycle ends the cycle still holding
      leftover volume -- one of "R"'s channels used only 2 of its first
      cycle's 10 rows, leaving 240uL in the tip. The very next aspirate
      (originally: same tip, next cycle) tried to add another 300uL on top,
      overflowing the tip's real 360uL capacity
      (`TooLittleVolumeError: 300.0uL > 120.0uL`, i.e. only 120uL of free
      space left). First fixed by discarding tips every cycle instead of
      every letter (10 tip pick-ups total); superseded by the leftover-
      return fix below once the user asked for it.
- [x] **Bug: a plain row<->column transpose mirrors, it doesn't rotate
      (found live via user report, fixed).** `letter_row_batches()`
      originally read bitmap column `c` as plate row `PLATE_ROWS[c]`.
      Swapping two axes with neither reversed is a *reflection* across the
      diagonal, not a 90-degree rotation -- confirmed live when "R" rendered
      as its own mirror image on the plate. Fixed by reversing one axis
      while swapping (`PLATE_ROWS[7 - c]`), which turns the reflection into
      the intended rotation. User confirmed live afterward: "The letters
      look fine."
- [x] **Follow-up: channel index should match row order for faster,
      non-diagonal gantry motion (user request, implemented).** The initial
      un-mirror fix built each row-batch's channel list by iterating bitmap
      columns in (reversed) order, which wasn't necessarily ascending by
      row letter -- a real gantry channel is physically fixed to one row, so
      an out-of-order list would make a channel dispense into a different
      row than its neighbors, reaching diagonally for no reason. Fixed by
      sorting `rows` ascending, then (see the next item) pinning each row
      letter to an explicit, *permanently* matching channel index rather
      than relying on PyLabRobot's positional default.
- [x] **Follow-up: return leftover ink to the reservoir with `empty=True`
      instead of discarding tips (user request, implemented).** Rather than
      wasting each cycle's leftover ink by discarding the tip that held it,
      each cycle now ends with an explicit `lh.dispense()` back to
      `ink_reservoir` for every channel that has leftover, using
      PyLabRobot's real `empty=True` dispense-mode flag (a genuine
      `STARBackend.dispense()` kwarg -- forwarded through
      `visualizer_backend.py`'s `dispense()` like any other backend kwarg,
      confirmed to reach `LiquidHandlerChatterboxBackend` and print in its
      log without needing any code changes there). This requires knowing
      each channel's *exact* leftover, which requires a channel to mean the
      same plate row on every dispense call within a cycle -- so
      `letter_row_batches()` now sorts `rows` ascending (previous item) and
      `main()` passes `use_channels=[PLATE_ROWS.index(row) for row in
      rows]` explicitly instead of PyLabRobot's positional default,
      tracking a `dispense_count` per row letter per cycle to compute exact
      leftover (`300uL - dispense_count * 30uL`). One tip pick-up now
      spans a whole letter's two cycles again (5 pick-ups total, not 10),
      since a tip returned to empty is safe to reuse. Verified live: the
      very first cycle's logged leftover volumes (A:300, B:120, C:210,
      D:180, E:210, F:240uL) matched a hand-computed check exactly, and the
      `empty` column appeared correctly in the Chatterbox log for every
      return dispense.
- [x] **Follow-up: move the reservoir to carrier site 2 (user request,
      implemented).** `reservoir_carrier[0] = ink_reservoir` changed to
      `reservoir_carrier[2]` (`Trough_CAR_5R60_A00` has 4 sites, confirmed
      live). Verified live: the reservoir renders at the carrier's third
      slot, not its first.
- [x] **Answered, not changed: why do PicoGreen-specific run params show up
      for every demo?** `frontend/index.html`'s "run-params" HUD (sample
      volume/count inputs, PicoGreen readout) is hardcoded into the one
      shared page, built originally for `picogreen_demo.py`; `main.js`'s
      Start-button handler always packages `sample_volume_ul`/
      `sample_count` into the `start_protocol` message regardless of which
      script is listening, and every other demo's `backend.wait_for_start()`
      just receives a params dict it never reads. Not PicoGreen-specific to
      *this* demo's correctness (pixel_art_demo.py ignores the returned
      params entirely), but a real "one hardcoded HUD for every protocol"
      simplification -- left as-is pending explicit user direction on how
      they'd want it generalized.

      Verified live end-to-end after all of the above: the backend run
      finished with zero errors, and every one of the 218 filled wells
      (44+34+26+56+58 across the 5 plates) matched its letter's bitmap
      exactly once the animation queue caught up (0 anomalies from a full
      `resourceIndex` sweep of all 5 plates' 96 wells each). The reservoir
      (pre-filled to 10,000uL) settled at exactly the hand-computed
      3,460uL -- 10,000 - 218*30, confirming the leftover-return math
      returns precisely what it aspirates but doesn't deliver, not merely
      "approximately".

## Review round 31 (2026-08-19)

User follow-up to round 30's "answered, not changed" item: actually fix
the PicoGreen-specific run-params HUD showing up for every demo.

- [x] **`VisualizerServer.set_run_params()`, a small opt-in mechanism, not a
      full form/formula system.** A protocol script now declares its own
      HUD input fields (a plain list of dicts -- see the method's
      docstring for the exact schema) instead of the frontend hardcoding
      one fixed pair of inputs for every script. Two field types only:
      `"number"` (an editable input, its value read back into
      `wait_for_start()`'s returned params dict by `id` when "Start
      Protocol" is clicked) and `"computed"` (a read-only derived readout;
      currently just `"picogreen_working_solution"`, the one
      `picogreen_demo.py` needs -- an unrecognized `basis` is simply not
      rendered, so this can grow new computed kinds later without breaking
      older ones). Declaring nothing (every demo but one) leaves the HUD's
      `#run-params` row hidden entirely (`display: none` by default in
      `index.html`'s CSS, toggled to `.visible` only once fields arrive) --
      the user picked this "minimal: hide it when unused" scope explicitly
      over a fully generic declarative-form system, since only one demo
      has ever needed protocol-specific inputs.
- [x] **`frontend/main.js` renders the HUD generically.** The two hardcoded
      DOM refs (`sampleVolumeInput`/`sampleCountInput`/
      `picogreenReadoutEl`) and the fixed `updatePicogreenReadout()` are
      gone, replaced by `renderRunParams(fields)` (builds `<label><input>`
      pairs and computed `<span class="readout">`s from whatever the
      server's `"run_params"` message declares) plus a `runParamInputs`
      map the Start-button handler, `lockForRun()`, and the `"reset"`
      handler all read/disable generically instead of naming specific
      input ids.
- [x] **`picogreen_demo.py` is the one demo that opts in**, declaring its
      existing 2 inputs + 1 computed readout from its own
      `MIN_SAMPLE_VOLUME_UL`/`MAX_SAMPLE_VOLUME_UL`/etc constants -- these
      already existed and were previously "kept in sync by hand" with
      separately hardcoded `index.html` attributes (per that comment's own
      wording); now the JS-visible min/max/default/total all come directly
      from the same Python constants the protocol logic itself uses, so
      there's nothing left to keep in sync. Declared fresh at the top of
      every `while True:` loop pass, since `reset_for_new_run()` clears the
      server's fields the same way it clears the scene.

      Verified live: `picogreen_demo.py`'s HUD renders identically to
      before ("Sample 5µL × 24 PicoGreen 195µL"), the computed readout
      still updates live as the sample-volume input changes (tested typing
      10 -> readout updated to "PicoGreen 190µL"), and clicking Start with
      that value produced `Started: 24 sample(s) at 10.0uL each (190.0uL
      PicoGreen per well)` in the backend log with no errors -- confirming
      the generically-built params dict round-trips correctly.
      `cherry_pick_demo.py` (never calls `set_run_params()`) now shows no
      HUD row at all -- just the status pill and buttons -- and still runs
      end to end with an empty params dict and no errors.

## Review round 32 (2026-08-20)

User request: generalize `pixel_art_demo.py` from a fixed "ROCHE" to any
5-character word (A-Z0-9), pre-generating all 36 characters' bitmaps
rather than drawing them at runtime, entered via the HUD, with a
30-150uL HUD-configurable dispense volume. Four decisions asked up front:
bitmap source (font-rasterized via Pillow, regenerating all 36 including
the existing R/O/C/H/E for one consistent style -- chosen over hand-
drawing), HUD widget (one 5-character text box -- chosen over 5 separate
boxes), validation (strict: block Start until exactly 5 valid characters
-- chosen over silently padding/truncating), and blank support (no --
chosen over allowing fewer than 5 real characters).

- [x] **36-character bitmap library, generated offline, not at runtime.**
      A one-off script (not committed -- run via `uv run --with pillow`,
      Pillow is not a runtime dependency) rasterized Arial Bold into each
      12x8 grid via block-averaged downsampling, then the literal output
      was pasted into `pixel_art_demo.py`'s `PATTERNS` dict -- `main()`
      never draws anything, only ever does a dict lookup, which is what
      actually makes 5-character *arbitrary* input practical.
- [x] **A new `"text"` field type for `VisualizerServer.set_run_params()`**
      (the HUD mechanism round 31 built) -- `frontend/main.js`'s
      `renderRunParams()` gained a branch that sanitizes input to
      uppercase `A-Z0-9` and truncates to a declared `length` as you type,
      plus `runParamsValid()`/`refreshStartButton()` to keep "Start
      Protocol" disabled while any text field is short of that length
      (wired into every place that used to set `startBtn.disabled`
      directly: `onopen`/`onclose`/the `"start_status"`/`"reset"`
      handlers). `index.html` gained matching `:invalid`-styling CSS (via
      `minLength`/`required` on the generated input, purely for that
      styling hook -- the JS validation logic doesn't rely on the
      browser's own constraint-validation state at all).
- [x] **Backend generalized to read `word`/`dispense_volume_ul` from the
      HUD** instead of the old fixed `WORD = "ROCHE"`/`DISPENSE_VOLUME_UL
      = 30.0` constants -- `_clamped_word()` (new, mirrors
      `_clamped_param()`'s "never trust a websocket value" philosophy)
      sanitizes and pads/truncates any input that somehow reaches the
      backend invalid despite the HUD's own gate. `DISPENSES_PER_ASPIRATE
      = 300 // dispense_volume_ul` computed at runtime; the existing
      leftover-return math already generalized to any dispense volume with
      no further changes (confirmed: `ASPIRATE_VOLUME_UL - dispense_count
      * dispense_volume_ul` never assumed the division was exact). Plates
      renamed by position (`plate_0`..`plate_4`), not by character, since
      a word can now repeat one (e.g. "HELLO").
- [x] **Bug: the reservoir's residual margin was sized for the wrong
      thing (found via hand math before it could fail live, fixed).**
      `RESIDUAL_INK_UL` was still 500uL, sized for "leftover once the run
      finishes" -- but every aspirate cycle draws the *full* 8 x 300uL =
      2,400uL from the reservoir instantly, before that cycle's leftover
      is returned a few dispenses later, so the pre-fill has to cover that
      single largest in-flight draw, not just the run's total net
      delivery. Raised to 2,500uL.

      Verified live: `HIGH1` at 75uL/well completed with zero backend
      errors, and a full `resourceIndex` sweep of all 5 plates matched the
      bitmaps exactly, with the reservoir settling at exactly the
      predicted 2,500uL residual -- this run's own dynamically-computed
      pre-fill minus its real delivered total, exactly, not merely close.
- [x] **Investigated a live gantry-desync report, found a genuine one-time
      freeze, could not reproduce it.** User reported "the pipettes are
      de-sync" mid-run; confirmed aspirate already happens as a single
      synchronized 8-channel pass (all `offset.x == 0`, so
      `planGantryPasses()` groups them into one pass, not eight sequential
      ones) -- that part of the design was already correct. Did catch one
      channel frozen mid-air at a non-rest height for 5+ continuous
      seconds with the backend already finished and the render loop
      confirmed still alive (`requestAnimationFrame` kept firing) -- but a
      clean, heavily-instrumented rerun of the identical word/volume
      (per-channel queue-length sampled every 250ms, explicit stall
      detection for any channel frozen >=3s at a non-zero queue) completed
      with zero stalls and fully correct final state. Folded the
      temporary `window.__channels` debug hook used for this into a
      permanent `window.__viz.channels` getter (a live getter, not a
      plain reference -- `ensureChannels()` *reassigns* the module-level
      `channels` array, not just mutates it) instead of leaving an ad-hoc
      global behind.

## Review round 33 (2026-08-20)

User request: a normalization-protocol demo -- read a 96-well plate's
current concentrations/volumes from a CSV, dilute every sample to one
target concentration in one final volume (50-200uL, both HUD inputs), with
three explicit rules: (1) flag "too dilute" wells that can't reach target,
(2) treat 5uL as the minimum pipettable volume, flagging/skipping
too-concentrated samples and skipping (not flagging the whole well for)
negligible diluent top-ups, (3) transfer whichever of sample/diluent is
larger first. Explicitly asked for a plan and clarifying questions before
any code, and for unit tests proving the logic. Four structural decisions
were asked up front (fresh destination plate; fresh tip per sample +
shared tips for diluent; 8-channel batching where possible; pytest) and
five more in a follow-up (sample_name CSV column; HUD for target/volume;
splitting "too dilute" into two distinct flags; 0.1uL rounding; a results
CSV including flags).

- [x] **`src/hamilton_visualizer/normalization.py`, a small PyLabRobot-free
      logic module.** `compute_normalization()` takes one well's
      `(concentration, volume)` plus the run's `(target_concentration,
      final_volume_ul)` and returns a `NormalizationResult` -- the exact
      sample/diluent volumes to transfer (rounded to 0.1uL), the transfer
      order, and a flag. Rule 1 splits into two distinct flags per the
      user's follow-up: `TOO_DILUTE_CONCENTRATION` (concentration itself
      is below target -- no achievable volume could ever work) vs
      `INSUFFICIENT_SAMPLE_VOLUME` (concentration would work, but this
      well doesn't hold enough of it) -- both skip the well entirely. Rule
      2 also splits: `TOO_CONCENTRATED` (sample volume needed rounds under
      5uL) skips the well entirely, while `DILUENT_SKIPPED` (diluent
      volume needed rounds under 5uL) only skips *that* leg -- the sample
      still transfers alone. Also holds `load_samples_csv()`/
      `write_results_csv()` -- plain stdlib `csv`, no PyLabRobot, just as
      unit-testable as the math.
- [x] **`tests/test_normalization.py`, 24 pytest cases** (added `pytest`
      as a `[dependency-groups] dev` dependency -- not previously in
      pyproject.toml, no `tests/` directory existed before this): every
      rule's ordinary case, its exact boundary (concentration/volume/
      pipette-volume values right at the threshold, confirming which side
      of `<` vs `<=` each check actually falls on), both `TOO_DILUTE_
      CONCENTRATION` edge cases (zero and negative concentration, guarding
      the division), all three transfer-order outcomes, rounding
      (confirming diluent is computed from the *rounded* sample volume so
      the two always sum to the final volume instead of drifting from
      independently-rounded numbers), and CSV round-trip/missing-column
      cases.
- [x] **`examples/normalization_demo.py`** -- reads
      `examples/normalization_samples.csv` (a fresh synthetic 96-well
      example, deterministically seeded to guarantee every flag path
      appears -- verified live: 64 ok / 9 insufficient_sample_volume / 8
      too_dilute_concentration / 8 too_concentrated / 7 diluent_skipped),
      pre-fills a source plate from it before "Start Protocol" (doesn't
      depend on the HUD's target/volume), and after the click computes
      every well's `NormalizationResult`, pre-fills the diluent reservoir
      dynamically from the *actual* total diluent this specific run needs
      (impossible to hardcode now that both HUD params vary), writes
      `examples/normalization_results.csv` (every well's computed volumes
      and flag -- the audit trail, not just what got pipetted), then
      executes the transfers: skipped wells untouched, active wells
      grouped by `transfer_order` and batched 8 channels at a time with
      per-channel volumes (PyLabRobot's `vols=[...]` already supports a
      different volume per channel in one call).
- [x] **Bug: two tip types can't both be mounted on the same channels at
      once (found live, fixed).** The original design picked up one
      shared set of diluent tips meant to stay mounted for the whole run,
      interleaving diluent/sample batches on the same 8 channels -- the
      very first sample batch's `pick_up_tips()` (defaulting to channels
      0-7, same as the diluent tips already sitting there) raised
      PyLabRobot's own `HasTipError: Channel has tip`, since a real
      8-channel head can only hold one tip per channel. Fixed by splitting
      into three phases instead of interleaving: phase A does every
      diluent-first well's diluent step (one shared pick-up), phase B does
      *every* well's sample step (fresh tips per batch, as always), phase
      C does every sample-first well's diluent step (a second shared
      pick-up, from a different tip-rack column than phase A). Each well's
      own two-liquid order is still preserved -- what rule 3 cares about
      is which liquid lands in *that well* first, not which tip-rack
      column supplied it -- confirmed live: the fixed version completed
      the full 96-well run one tip-collision-free.

      Verified live end-to-end: zero backend errors, and a full
      `resourceIndex` sweep of all 96 wells' destination *and* source
      plate volumes against `normalization_results.csv` found zero
      discrepancies (every active well's destination matched
      `sample_volume_ul + diluent_volume_ul` exactly, every active well's
      source matched `original_volume - sample_volume_ul` exactly, every
      skipped well's source stayed exactly unchanged). The diluent
      reservoir settled at exactly the hand-computed 2,000uL margin --
      this run's own dynamically-computed prefill (4,660.3uL real need +
      2,000uL margin) minus that same 4,660.3uL once actually delivered.

## Review round 34 (2026-08-21)

User report: watching the normalization demo live, "the channels desync
after a while... it could be after finishing the first phase of diluent
first, sample second" -- a specific, actionable hint pointing at the
Phase A (diluent-first wells' diluent step) to Phase B (every well's
sample step) boundary round 33 built.

- [x] **Found and fixed the real root cause, in `frontend/main.js` itself,
      not the demo script.** Reproduced live with full channel-state
      instrumentation and caught it directly: right after Phase A,
      channel 7 had already dropped its tip and sat idle at the trash
      position (`hasTip: false`, empty queue) while channels 0-6 were
      still deep in backlog, still holding tips (`hasTip: true`) --
      visually exactly what the user described, "a channel picks up a tip
      from a different tip box." Root cause: `planGantryPasses()` only
      dragged *tip-loaded* channels along for an op they weren't targeted
      by (`loadedChannelsEager`, added several rounds ago for a different
      bug). A channel with no tip mounted for a given call got nothing
      enqueued at all when that call didn't target it -- so a channel
      used less often than others (systematically channel 7, the least-
      favored index under PyLabRobot's default 0..n-1 channel assignment
      whenever a batch is smaller than 8) accumulates a shorter queue over
      the run, drains it in less real time, and reaches -- and starts
      animating -- a *later* op (a different tip rack's pick-up) while
      slower channels are still working through an earlier one. Confirmed
      live: channel 0 had 555 total legs queued at the run's start,
      channel 7 only 395.
      User explicitly steered away from a demo-side fix ("I don't think
      changing the logic in the normalization is a good idea. Because the
      visualizer should be able to accept any valid but arbitrary
      operations") -- correct: the bug wasn't specific to how this one
      demo happens to batch channels, it's that the visualizer didn't
      keep *any* protocol's channels in lockstep when channel usage isn't
      perfectly even, which no protocol is obligated to be.
- [x] **Fix: widened the "drag along" set from tip-loaded channels to
      every channel, always.** `nudgeChannel()`'s total duration already
      exactly equals `animateChannelOp()`'s (same six leg-durations, just
      the last three folded into one `enqueue()` call) -- so once every
      channel gets dragged along for every group op regardless of tip
      status, every channel accumulates identical total animation time no
      matter which ones a given call actually targets. True lockstep by
      construction, for any channel-usage pattern, not just even ones.
      `loadedChannelsEager` (now dead -- its only read site was the code
      just replaced) removed entirely, including its own tracking in
      `handleOpEvent()`'s pick_up_tips/drop_tips cases.

      Verified live: reran the identical word/CSV/params with full
      per-channel queue-length and tip-state instrumentation (400ms
      samples across the whole ~500-sample run). The queue-length gap
      between the busiest and idlest channel stayed *flat* at 32 legs for
      the entire run (never widened), vs. the old run's initial 160-leg
      gap that only grew from there. `hasTip` mismatches only ever
      appeared transiently (a single 400ms frame, or exactly matching a
      real 7-well tail batch correctly leaving one channel tip-less) --
      never the sustained "one channel fully done, others still deep in
      backlog" pattern the bug produced. Final state re-verified
      identical to before the fix: zero discrepancies across all 96
      wells' destination/source volumes against `normalization_results.csv`,
      reservoir settled at the same exact 2,000uL.

## Review round 35 (2026-08-21)

User request: three new capabilities -- a CO-RE 96 head (deferred to the
next round), an Inheco on-deck thermal cycler integration, and a bigger
deck (`STARDeck` instead of `STARLetDeck`) to fit them. Explicitly asked
for a plan and clarifying questions first; four real decisions came back:
pure infrastructure (no polished demo yet, verified with standalone
scripts instead), the 96-head and the 8 regular channels coexist on deck
rather than being exclusive, the lid should actually animate (not just the
5-second block shimmer), and Inheco's real dimensions should be researched
rather than guessed.

- [x] **Investigated PyLabRobot's actual thermocycling support before
      building anything** (the user's explicit ask -- "check if it is a
      resource holder or PCR adapter... whether it has a chatterbox
      backend"): confirmed `pylabrobot.thermocycling.thermocycler.
      Thermocycler` *is* a `ResourceHolder` (a plate lands directly via
      `child_location`, no separate PCR-adapter resource needed at the API
      level) that's also a `Machine` with its own `ThermocyclerBackend`;
      confirmed a real `ThermocyclerChatterboxBackend` exists (device-free,
      completes `run_protocol()` instantly -- the same role
      `LiquidHandlerChatterboxBackend` plays); confirmed a real `Protocol`/
      `Stage`/`Step` model (`temperature: List[float]`, `hold_seconds`)
      -- exactly the data the tooltip needed. No pre-built "Inheco ODTC"
      resource ships with PyLabRobot, so this one had to be constructed by
      hand, same as `custom_labware.py`'s Cellvis plate.
- [x] **`custom_labware.py` gained `inheco_odtc_thermocycler()`**, with
      real dimensions from Inheco's own product page (248 x 156.5 x
      124.3mm) confirmed via a fresh web fetch, not assumed -- including
      the detail that mattered for the lid animation: a real ODTC's lid
      "opens and closes by horizontal move," not a hinge. Oriented with
      its long 248mm side running front-to-back (`size_y`), not
      rail-parallel -- corrected mid-round after an initial wrong guess
      (real ODTCs are placed with the long axis into the deck, plate in
      the front section, electronics in the rear; the front section isn't
      necessarily half the depth). `size_x` is deliberately widened 1mm
      from the real 156.5mm to 157.5mm -- exactly 7 Hamilton deck rails
      (22.5mm pitch) -- so it places flush against a rail boundary like
      any other carrier instead of leaving an unusable sliver (per user
      direction). `child_location` (where a plate lands) isn't published
      anywhere found, so it's an explicit, documented engineering estimate
      (60% of the unit's height), not a fabricated spec.
- [x] **New `src/hamilton_visualizer/thermocycler_backend.py`
      (`VisualizerThermocyclerBackend`)**, the same wrap-and-forward
      pattern as `VisualizerBackend` applied to `ThermocyclerBackend`.
      Structurally different from the liquid-handling side in one real
      way: a `ThermocyclerBackend`'s calls carry only plain values (never
      a resource reference, since one backend is permanently bound to
      exactly one machine), so it needs the resource's own name passed in
      at construction instead of read off each op. `run_protocol()`
      broadcasts a `thermocycler_run_protocol` op event carrying
      `summarize_protocol()`'s human-readable line (e.g. "95C 5:00; 95C
      0:30, 55C 0:30, 72C 1:00 (x30); 72C 5:00") and caches it via
      `record_resource_state()` so a client connecting after the run (or a
      page reload) still shows it; `open_lid()`/`close_lid()` broadcast
      their own op events.
- [x] **Frontend: a new "thermocycler" category**, rendered the way the
      user specifically asked -- reusing the existing carrier treatment
      (a solid block from the base up to the payload holder height, i.e.
      exactly "a base rectangle plus a plate holder," no new geometry code
      needed for that part) plus one genuinely new piece: a separate lid
      mesh (not a PyLabRobot child resource -- Thermocycler's model has no
      lid sub-resource, so this is purely a visualizer-side extra) that
      slides horizontally on `thermocycler_open_lid`/`_close_lid`, matching
      the real hardware's actual mechanism. `run_protocol()`'s 5-second
      "cycling" is a fixed-duration pulsing-color shimmer on the block,
      deliberately decoupled from the backend's instant completion --
      the same "animation timing ignores backend timing" philosophy as
      every liquid-handling op in this visualizer, now extended to a
      second machine type. Tooltip shows the last-run protocol's summary
      once one exists.

      Verified live (`STARDeck`, per this round's third ask): a standalone
      script built a thermocycler holding a PCR plate, placed it at
      exactly 7 rails wide and centered on the deck's own Y depth (per
      user direction, so it's easily reachable rather than tucked in the
      usual front carrier band), closed the lid, ran a real
      3-stage/32-cycle protocol, then opened the lid again. Confirmed
      numerically: `size_x == 157.5 == 7 * 22.5` (rail pitch); placement
      `location.y == 202.75 == (653.5 - 248) / 2` (deck depth minus the
      thermocycler's own 248mm, centered); the lid's open position lands
      exactly flush with the unit's own rear edge
      (`lidCenterY + lidSizeY/2 + slideDistance == sizeY`), not overhanging
      past the real housing. The event log showed the exact expected
      summary string; the lid visibly slid along Y from covering the plate
      to clear of it and back; the tooltip showed the full protocol text;
      `resourceIndex` confirmed `protocolSummary`/`lidOpen` matched exactly
      what was sent.

      Follow-up fix (same round): the lid was first sized as a fraction of
      the housing's own `size_x`/`size_y` (~134 x ~136mm) -- nearly square,
      which read as rotated 90 degrees next to the visibly landscape-shaped
      plate sitting under it (a real SBS plate, and its lid, are wider
      (127.76mm, X) than deep (85.48mm, Y), not roughly equal). Re-derived
      the lid's size directly from the real PCR plate's own footprint
      (`cor_96_wellplate_360uL_Fb`: 127.76 x 85.48mm) plus a small
      clearance margin instead, so it stays landscape-shaped regardless of
      how the housing's own dimensions are tuned. Verified live:
      `lidMesh.geometry.parameters` = `{width: 139.76, depth: 97.48}`,
      matching the plate's own 127.76:85.48 aspect ratio.

      Two more follow-up fixes, both in the new `examples/thermocycler_demo.py`
      (promoted from a throwaway scratchpad verification script into a real,
      committed example so there's an actual command to run -- see that
      file's own docstring): (1) Replay did nothing after the run finished --
      `VisualizerServer`'s replay guard only opens once `mark_finished()` has
      been called, which the script never did; added it. (2) The lid
      genuinely wasn't opening "after thermal cycling is done" (user-
      reported) -- not a positioning bug (a same-turn detour down that path
      was reverted), but a pacing one: `close_lid()`/`run_protocol()`/
      `open_lid()` all complete near-instantly against the chatterbox
      backend with nothing between them, and unlike a `LiquidHandler`'s
      channels (each with a real-paced animation queue), the thermocycler's
      lid-slide/shimmer animations are plain fire-and-forget tweens with no
      queue -- so `open_lid()`'s 600ms slide fired and finished before the
      5-second shimmer had visually gotten anywhere. Added `asyncio.sleep()`
      calls matched to `main.js`'s own timing constants, standing in by hand
      for the queue liquid-handling ops get for free.

## Review round 36

User request: "maybe we should divide main.js up because now it is too
long" (1879 lines), plus "perhaps we need some unit test for it as well?"
mid-turn. Proposed a 9-module split and a `node --test`-based (zero
dependency, no build step) testing approach via `AskUserQuestion` before
starting -- both confirmed as proposed.

- [x] **Split `frontend/main.js` into 9 focused modules**, each with a
      clear one-directional dependency (no cycles): `coordinates.js`
      (`mapPoint()`), `categories.js` (color palette + `tipColorForVolume()`
      + legend data), `duration-scale.js` (the HUD's playback-speed
      multiplier, split out just so gantry.js/thermocycler.js/dom.js don't
      need to import each other for one shared number), `scene-builder.js`
      (scene graph -> Three.js construction; owns `resourceIndex`/
      `hoverables`), `resource-state.js` (live tip/volume/protocol-summary
      updates), `thermocycler.js` (lid-slide + shimmer animation),
      `gantry.js` (the `Channel` class + `handleOpEvent()`'s op dispatch),
      `dom.js` (DOM handles, event log, HUD wiring), `websocket.js` (the
      connection itself), `tooltip.js` (hover tooltips). `main.js` shrinks
      to ~150 lines: Three.js viewport/camera setup, wiring
      `websocket.js`'s `connect()` with callbacks from the other modules,
      and the render loop.

      The one real circularity risk -- dom.js's Start/Reset/Replay buttons
      need to *send* on the websocket, while websocket.js's message
      handlers need to update DOM/HUD state -- resolved by making
      `websocket.js` fully callback-driven (`connect(handlers)`) and
      DOM-agnostic, so `dom.js` can import its `send()` one-directionally
      without websocket.js ever needing to import `dom.js` back.
      `channels` (gantry.js) and `resourceIndex`/`hoverables`
      (scene-builder.js) are re-exported as live ES-module bindings (not
      snapshotted) -- unlike CommonJS `require()`, an ES `import` always
      sees the exporting module's *current* value, so `ensureChannels()`
      wholesale-reassigning `channels` is still visible everywhere that
      imported it, exactly as it was when everything shared one scope.

- [x] **Split `gantry.js`'s `resolveChannelYs()`/`planGantryPasses()`
      further, into a new `gantry-planning.js`**, deliberately with zero
      THREE.js/DOM imports -- these two are the least-obvious logic in the
      whole frontend (a change-of-variable feasibility solver for "can
      these channels' y targets all be reached in one gantry stop," plus
      the per-x stop-grouping built on top of it) and have been the source
      of real, previously-live-debugged desync bugs (rounds 15, 26, 34) --
      exactly what a unit test is for. `gantry.js` now just calls
      `planGantryPasses(entries, channels)` with its own live `Channel[]`.

- [x] **Added `node --test`-based unit tests** (`tests/frontend/`, zero
      dependencies, no build step -- matching this repo's existing
      no-build-step convention): 17 tests across `gantry-planning.js`
      (`resolveChannelYs`'s already-valid/nudge/sandwiched/throws cases;
      `planGantryPasses`'s single-x, scattered-x, partial-targeting, and
      same-x-conflict-fallback cases -- the last two checked via a
      reconstructed-invariant helper, not hand-derived exact y values, so
      they validate the actual physical constraint the function exists to
      guarantee rather than one brittle worked example), `categories.js`
      (`tipColorForVolume`'s threshold buckets/boundaries/fallback), and
      `resource-state.js` (`volumeVisual`/`tipVisual`'s empty/full/
      monotonic/sqrt-scaling behavior). `frontend/node_modules/three/
      package.json` is a small shim (not a real npm install -- just points
      the bare `"three"` specifier at the already-vendored
      `frontend/vendor/three.module.js`) so `resource-state.js`'s existing
      `import * as THREE from "three"` resolves identically under plain
      Node and the browser's own importmap, with zero changes to any
      import line; carved an exception into `.gitignore`'s blanket
      `node_modules/` rule for just this one file.

      Verified live (not just the new unit tests): re-ran
      `examples/thermocycler_demo.py` (full close/run/open sequence +
      Replay) and `examples/cherry_pick_demo.py` (the scattered-6-column
      smiley-face dispense -- exercises `planGantryPasses`'s multi-pass
      grouping directly) against the split frontend with a clean browser
      console -- identical behavior to before the split, screenshots and
      event log matched pre-split runs exactly. `docs/DESIGN.md`'s file
      tree and `README.md`'s testing section updated to match.

      Follow-up fix (same round): user-reported "the timing isn't right --
      the thermocycling starts before the lid opening, and the lid did not
      close in the visualizer." Root cause: the lid starts *closed* by
      default (`scene-builder.js`'s baked-in initial `lidMesh` position --
      there's no "starts open" scene attribute), and the script's very
      first lid op was `close_lid()` -- closing an already-closed lid is a
      no-op tween (identical start/end position), so it was never visible.
      The only lid motion in the whole run was the final open, which read
      as the cycling animation having started with no lid movement at all
      beforehand. Fixed by opening the lid first ("loading the plate")
      before ever closing it, so the subsequent close is a real, visible
      animation -- the full story is now open (load) -> close (visible) ->
      shimmer (cycling) -> open (visible, done).

      Also switched from Replay to a proper `while True:`/`wait_for_reset()`
      loop (matching `picogreen_demo.py`'s "start the entire thing over"
      pattern) per user suggestion ("perhaps it is easier just reset
      everything instead of replay"). This sidesteps a real Replay/live
      timing mismatch this round's pacing fix exposed:
      `VisualizerServer.replay()` caps a replayed gap between two events at
      2 real seconds (`MAX_REPLAY_GAP`), but the script's own 5-second
      shimmer-then-open pause is longer than that cap -- replaying it would
      fire `open_lid()` while the frontend's fixed 5-second shimmer
      animation was still only 2 seconds in, silently undoing the very
      pacing fix that made the lid open *after* cycling instead of during
      it. A fresh live run (via Reset) has no such cap. Verified live:
      full open/close/shimmer/open sequence with correct 5-second pacing
      (confirmed via event-log timestamps), then Reset produced a fresh
      scene (lid back to its closed default) ready for another run, with a
      clean browser console throughout.

## Review round 37

User-reported (again): "the lid opens before the thermal cycling animation
finished" -- even with round 36's follow-up fix in place. Root-caused to a
real architecture gap rather than a missed edge case: discussed with the
user before writing any code (per their explicit request).

- [x] **Diagnosed the real cause**: the Python-side `asyncio.sleep(5.0)`
      (round 36's fix) is a hardcoded guess that only matches the frontend
      at the HUD's default `1x` speed -- `THERMOCYCLER_SHIMMER_MS *
      getDurationScale()` can run 2-4x longer if the speed dropdown isn't
      at its default (a natural thing to reach for when *carefully*
      watching whether an animation looks right), and the Python sleep has
      no visibility into that dropdown at all. More fundamentally: unlike a
      `LiquidHandler`'s channels, which each have a real per-channel
      animation *queue* (`Channel.enqueue()`/`update()` in gantry.js) that
      lets ops fire back-to-back with zero `asyncio.sleep()` calls (see
      cherry_pick_demo.py's docstring), the thermocycler's lid-slide/
      shimmer animations were plain fire-and-forget `requestAnimationFrame`
      loops with no queue at all -- hand-placed sleeps were papering over a
      missing piece of frontend architecture, not really fixing it.
- [x] **Design discussion before implementation** (user: "Let's discuss
      before changing any code"): laid out the gantry's existing queue
      model vs. the thermocycler's lack of one, proposed generalizing the
      queue into a reusable class rather than hand-rolling a third copy for
      the CO-RE 96 head (explicitly the next round). User confirmed:
      per-resource queues (not a global one), and specifically asked about
      class reuse for the 96-head. Also flagged, correctly, that the 96-head
      and the 8-channel head share the gantry's single X drive but have
      independent Y/Z *and* aren't at the same X (they're mechanically
      offset along the rail) -- see "Deferred: cross-mechanism X sharing"
      below for how that's being carried forward, not yet implemented.
- [x] **New `frontend/animation-queue.js`** (`AnimationQueue`, zero
      THREE.js/DOM dependency): the generic "run tasks one at a time, tick
      each with a raw `[0,1]` progress" primitive both other pieces below
      build on. Deliberately applies *no* easing itself -- `motion-unit.js`
      wants `easeInOutQuad`, `thermocycler.js`'s shimmer wants raw `t` fed
      straight into a sine wave (easing it would distort the oscillation,
      not just its pacing) -- baking one policy in would have been wrong
      for the other caller.
- [x] **New `frontend/motion-unit.js`** (`MotionUnit`, also zero THREE.js/
      DOM dependency): the "queue of x/y/z leg tweens, with lazy
      target/duration resolution" mechanics extracted out of gantry.js's
      `Channel`, built on `AnimationQueue`. This is the class the CO-RE 96
      head is meant to reuse next round -- it's mechanically simpler than a
      multi-channel op (one rigid body, no `resolveChannelYs` row-conflict
      math needed for the head itself), but the rise/x/y/descend/hold/
      retract leg-tweening it needs is identical to what `Channel` already
      does.
- [x] **`gantry.js`'s `Channel` refactored to compose a `MotionUnit`**
      instead of implementing its own queue -- `Channel.pos` becomes a
      getter delegating to `this.motion.pos` (an ES getter is safe here
      since nothing outside `Channel` ever *writes* `.pos`, only reads
      `channels[ch].pos.y`, confirmed by grep before refactoring);
      `enqueue()`/`update()` become thin pass-throughs. Zero behavior
      change -- verified live (see below).
- [x] **`thermocycler.js`'s lid-slide/shimmer now enqueue onto
      `entry.animQueue`** (added to every `resourceIndex` entry uniformly
      in scene-builder.js -- cheap when never used, and means a category
      that wants sequenced animation needs no scene-builder.js changes to
      get it) instead of starting an independent `requestAnimationFrame`
      loop immediately. `main.js`'s render loop ticks every entry's
      `animQueue` alongside the existing per-channel `update()` calls. This
      is the actual fix: `close_lid()`/`run_protocol()`/`open_lid()` now
      play out in real sequence regardless of how quickly the three calls
      fire, and regardless of the speed dropdown (each task reads
      `getDurationScale()` fresh when it *starts*, not when it was
      enqueued).
- [x] **`examples/thermocycler_demo.py`'s three `asyncio.sleep()` calls
      deleted entirely** -- `close_lid()`/`run_protocol()`/`open_lid()` now
      fire back-to-back exactly like a liquid-handling demo's ops already
      do. Side effect worth noting: this also fixes Replay for this demo,
      which round 36 had specifically steered away from (`MAX_REPLAY_GAP`
      capping the shimmer's real gap at 2 replayed seconds) -- since
      pacing is now owned entirely by the frontend queue instead of by
      inter-event *timing*, a replayed event just enqueues a task the same
      as a live one does, so the cap no longer matters. Docstring updated
      to reflect this; the Reset loop stays too, as a fine "start over"
      pattern in its own right.
- [x] **17 new unit tests** (`tests/frontend/animation-queue.test.js`,
      `motion-unit.test.js`) covering: task sequencing/one-at-a-time
      execution, lazy `duration`-as-function resolution timing, `isIdle`,
      `MotionUnit`'s null-stays-put/function-target.z/function-duration
      staleness handling (the same scenarios `gantry-planning.js`'s tests
      already cover for cross-channel planning, now covered for the
      single-unit leg mechanics too), and confirming motion is genuinely
      eased rather than linear. 30/30 frontend tests pass; 24/24 Python
      tests unaffected.

      Verified live: `examples/thermocycler_demo.py`'s full open/close/
      shimmer/open sequence completed correctly end-to-end (confirmed via
      `resourceIndex` introspection: `animQueue.isIdle === true`, lid
      position exactly equal to `lidOpenPos`, block color exactly reverted
      to `baseColor` after the shimmer) even with all four op calls firing
      within the same wall-clock second (no sleeps left to space them out)
      -- this session's browser pane wasn't actively compositing frames
      (confirmed via a `requestAnimationFrame` probe), so the usual
      screenshot-based verification wasn't available; correctness was
      confirmed by manually driving `channels[i].update()`/
      `entry.animQueue.update()` in fixed 16ms steps instead and reading
      the resulting state directly, which does not depend on rAF actually
      firing. Also re-ran `cherry_pick_demo.py` the same way end-to-end
      (2000 manual frames, zero exceptions) to confirm the `Channel`/
      `MotionUnit` refactor changed nothing: all 8 smiley-face wells landed
      at exactly 40uL, channels ended at the trash with tips dropped, y
      positions still correctly 9mm-spaced.

**Deferred: cross-mechanism X sharing (for the CO-RE 96 head round).**
Implemented in "Review round 40" below, once the CO-RE 96 head itself
existed to build the second half of this against. The
96-head and the 8 channels share the gantry's one physical X drive (so
whichever one moves, the *other* needs an X-only "drag along" nudge --
exactly generalizing `nudgeChannel()`'s existing idle-channel-dragging in
`gantry-planning.js`'s `planGantryPasses()`) but are *not* at the same
absolute X (mechanically offset along the rail -- user-flagged). Not
implemented this round: `gantry-planning.js`'s `planGantryPasses()` stays
scoped to the 8-channel group exactly as tested, since a generalized
multi-unit-with-offset version has no second unit to verify it against yet
and would be pure speculation about both the algorithm shape and the real
offset value. Sketch for next round: introduce an `xOffsetMm` per gantry-
mounted unit (0 for the channel group, a real Hamilton-derived constant for
`Core96Head`); when a unit's op reports absolute target x, recover the
shared carriage reference as `armX = opX - thisUnit.xOffsetMm`, then any
*other* mounted unit's idle-drag target is `armX + thatUnit.xOffsetMm`.

## Review round 38

User-reported, again, after round 37's AnimationQueue fix: "it looks like
the lid opening and thermocycling happens at the same time? And I did not
see the close lid animation." Two distinct real bugs, not one -- both
found and fixed this round, neither a repeat of round 37's actual queue
logic (which tests/frontend/animation-queue.test.js and
motion-unit.test.js already covered correctly).

- [x] **Stale browser cache**: `server.py`'s no-cache treatment
      (`Cache-Control: no-store`) was still a single hardcoded
      `/static/main.js` route, left over from before round 36 split
      `main.js` into a dozen files -- every *other* module
      (`gantry.js`, `thermocycler.js`, `animation-queue.js`, ...) silently
      fell through to the generic `/static` mount and kept its default,
      cacheable headers. A tab left open across several rounds of edits
      (exactly this session's pattern) could easily be running a stale mix
      of old and new modules with no way to tell from the outside --
      confirmed live via `curl -D -`: `/static/gantry.js` had no
      `Cache-Control` header at all before this fix. Replaced the single
      hardcoded route with `/static/{filename}` matching any top-level
      `*.js` file (Starlette's default `str` path converter doesn't match
      `/`, so `/static/vendor/three.module.js` -- deliberately still
      cacheable, pinned third-party code -- never reaches it and falls
      through to the mount unchanged, confirmed live). Fixes this specific
      bug category permanently instead of needing a new hardcoded line
      every time this project's frontend grows another file.
- [x] **Unclamped render-loop `dt`**: the real bug behind "opens before
      cycling finished" even on a *fresh, uncached* load. `main.js`'s
      `animate(now)` computed `dt = now - lastTime` with no ceiling --
      completely standard requestAnimationFrame code, but a well-known
      pitfall: any real gap between two consecutive callbacks (a
      backgrounded/minimized tab, since browsers throttle or fully pause
      rAF for hidden tabs; a slow synchronous script; a dev-tools
      breakpoint) feeds straight into `dt` as one giant number on the next
      callback. Round 37's whole fix depends on the *frontend* actually
      spending real frames animating the close/shimmer/open sequence
      (there are no `asyncio.sleep()`s left to space it out on the Python
      side any more) -- a single stray large-`dt` frame right after "Start
      Protocol" is clicked is enough to blow through the entire queued
      sequence in one call. This reproduced reliably in this session's own
      testing tooling too (the browser pane went through a stretch of not
      compositing frames at all -- confirmed via a live
      `requestAnimationFrame` probe -- and the very next frame after it
      resumed instantly drained a freshly-enqueued 4-task queue). Fixed
      with `Math.min(now - lastTime, MAX_FRAME_DT_MS)` (50ms -- a few
      normal frames' worth, so real 60fps playback is completely
      unaffected, but a resumed/throttled tab now takes longer in real
      time to finish whatever was still queued instead of skipping to the
      end -- the standard fix for this whole class of rAF pitfall).

      Verified live with precise in-page timing (`performance.now()`-based
      sampling inside a single `javascript_exec` call, to rule out this
      session's own tool round-trip latency from masking the real
      elapsed time): clicking Start and sampling
      `resourceIndex.get('thermocycler_1')` at nine fixed real-time
      offsets (200ms through 7500ms) showed the *first* open completing by
      ~200ms, a genuinely visible close mid-slide at 800ms (lid z
      interpolating between its open and closed positions, `lidOpen:
      false`, one task still ahead of it in the queue), the shimmer
      holding the lid closed and steady from ~1.4s through ~6s (matching
      its 5-second duration), and the final open completing cleanly around
      ~7s with the queue fully drained (`isIdle: true`) -- the complete,
      correctly-paced story this round set out to produce, not the
      near-instant collapse the user reported.

## Review round 39

The CO-RE 96 head, the last of this round's original three-item request
(96-head, thermocycler, bigger deck) and explicitly deferred to its own
round back when the thermocycler work started. Landed now that
`MotionUnit`/`AnimationQueue` exist to build it on (round 37) and the
render-loop `dt` is clamped (round 38) so its animation paces correctly
too.

- [x] **Confirmed the backend data was already there** before writing any
      frontend code: `VisualizerBackend.pick_up_tips96()`/`drop_tips96()`/
      `aspirate96()`/`dispense96()` already broadcast a real absolute
      x/y/z target via `events.py`'s `resource_event()`/`resource_point()`
      (the touched rack/plate's own top-center + offset) -- no scene.py
      changes needed for basic motion, contrary to this round's own
      earlier speculation in the round-37 design discussion.
- [x] **`visualizer_backend.py`'s 96-head handlers extended** to embed
      per-item resource state, reusing existing shapes rather than
      inventing new ones: `pick_up_tips96`/`drop_tips96` embed a
      `tip_spots: [{resource, resource_has_tip}, ...]` list (one entry per
      of the rack's 96 spots -- no tracker read needed, same "a successful
      op has a deterministic end state" reasoning `channel_ops_event()`
      already uses for a single-channel pickup: every spot empties on
      pickup, refills on drop, regardless of whether it had one before).
      `aspirate96`/`dispense96` embed a `wells: [...]` list via a new
      `_well_volume_entries()`helper, with field names
      (`resource`/`resource_volume`/`resource_max_volume`) deliberately
      matching a single-channel op's own embedded shape, so the frontend
      can reuse `applyEmbeddedResourceState()` verbatim, once per item, with
      no new resource-state.js code.
- [x] **New `Core96Head` class in `gantry.js`**, composing `motion-unit.js`'s
      `MotionUnit` for its own rise/x/y/descend/hold/retract leg motion --
      the exact reuse the round-37 design discussion built that class for.
      Rendered as a single rigid block sized to the SBS/ANSI microplate
      footprint every labware it touches (tip racks, plates) already
      shares (127.76 x 85.48mm) -- not resized per op, same reasoning
      `scene-builder.js`'s thermocycler lid uses for its own real-footprint
      sizing. Opacity (not hue) distinguishes tip-presence, parked at a
      fixed out-of-the-way position when idle. Deliberately *not*
      coordinated with the 8 channels' shared-X gantry stops
      (`planGantryPasses()`) -- see the round-37 "Deferred: cross-mechanism
      X sharing" note, still unimplemented and not needed by anything this
      round exercises (the two mechanisms are never used concurrently in
      any protocol this repo runs).
- [x] **`handleOpEvent()` gained `pick_up_tips96`/`drop_tips96`/
      `aspirate96`/`dispense96` cases**, each driving the block's motion via
      a new `animateCore96Op()` (the same six-leg shape as
      `animateChannelOp()`, minus the multi-channel pass-planning that
      doesn't apply to one rigid body) and, on arrival, replaying whatever
      `tip_spots`/`wells` array the backend embedded through
      `applyEmbeddedResourceState()` -- and flashing the touched
      plate for aspirate/dispense, reusing the existing `flashResource()`.
- [x] **New `examples/core96_demo.py`**: picks up all 96 tips from a full
      rack, aspirates 50uL from every well of a source plate at once,
      dispenses into a fresh destination plate, drops tips back onto the
      rack -- the `while True`/`wait_for_reset()` "start the entire thing
      over" pattern established in rounds 36-38, not Replay. No individual
      8-channel ops -- exercises the 96-head in isolation, matching
      `thermocycler_demo.py`'s own "one mechanism per demo" scope.
- [x] **`categories.js` gained a "CO-RE 96 head" legend entry** (a
      distinct cyan, `0x4fa8c9`, from the single-channel amber and the
      thermocycler's brown).

      Verified live: `pick_up_tips96` -> `aspirate96(50uL)` ->
      `dispense96(50uL)` -> `drop_tips96` all fired and animated
      correctly with a clean browser console; `resourceIndex`
      introspection confirmed *every* well on both plates updated
      correctly, not just a sampled one (`source_plate_well_A1.volume ===
      150` [200 - 50] and `source_plate_well_H12.volume === 150` --
      opposite corners of the plate both correct; `dest_plate_well_A1`/
      `_H12` both `=== 50`), the tip rack's spots correctly round-tripped
      (empty after pickup, full again after drop), and `core96Head`
      correctly returned to its idle position/state
      (`hasTips: false`, `pos.z` back at the shared gantry `restZ`)
      afterward. Reset produced a clean fresh scene. Re-ran
      `cherry_pick_demo.py` (STARLetDeck, no 96-head ops at all) to confirm
      coexistence doesn't regress the 8-channel side -- all 8 smiley wells
      still landed at exactly 40uL, and `core96Head` correctly stayed
      idle at its parked position/state the entire run, confirming the two
      mechanisms are independent as designed. 30/30 frontend unit tests
      and 24/24 Python tests unaffected (no new pure logic worth isolating
      beyond what `motion-unit.test.js` already covers -- `Core96Head` is a
      thin, already-tested reuse of `MotionUnit`, the same reasoning
      `Channel` itself wasn't separately unit-tested either).

      Follow-up fix (same round, user-reported): "I did not see the tips
      attached to the 96 well head." The first version only dimmed the
      block's own opacity for tip-presence -- too subtle to read at a
      glance, and not what was actually asked for ("the same
      implementation as the multi-channel pipettes, where you can see the
      tips attached to them"). Replaced with 96 individual tip cones (an
      8-row x 12-column grid at the same 9mm `CHANNEL_PITCH_MM` a real
      96-well plate and the 8 channels' own spacing already use, centered
      on the block's footprint), using the *exact* geometry/rotation/color
      a single `Channel`'s own `tipMesh` uses, toggled via `.visible` the
      same way (not a hue/opacity change). Verified live -- confirmed
      numerically (`core96Head.tipMeshes[0].visible`/`[95].visible ===
      true` mid-sequence, `false` again after drop) and visually (slowed
      the HUD to `0.25x` speed specifically to get a screenshot within the
      now-longer tips-attached window -- a real amber 8x12 cone grid
      visible hanging beneath the cyan block, matching a single channel's
      tip glyph exactly).

      Second follow-up fix (same round, user-reported): "The tips appear
      too short. Be sure to match the tips length as what was done with
      the multichannel pipettes." Correct -- the cone grid above still
      used the fixed `CHANNEL_TIP_HEIGHT` placeholder unconditionally,
      never the real tip's own length the way `Channel.setTip()` rebuilds
      its single tipMesh's geometry from `channel_ops_event()`'s
      `tip_length_mm`. `visualizer_backend.py`'s `pick_up_tips96` gained
      the same fields: a *representative* tip (the first non-`None` entry
      in `pickup.tips` -- every tip in one rack is normally the same
      model, so any present one works the same way a single-channel
      pickup only ever has the one it actually grabbed) contributes
      `tip_length_mm`/`tip_max_volume_ul` to the event. `Core96Head`'s 96
      cones share one geometry and one material (not 96 independent
      pairs), so `setTips(present, lengthMm, maxVolumeUl)` only ever needs
      to rebuild/recolor that one shared pair -- geometry only rebuilt
      (and all 96 meshes repositioned) when the length actually changes,
      color follows `tipColorForVolume()` the same capacity-bucket way a
      channel's own carried tip does, mirroring `Channel.setTip()`
      exactly. Verified live against `core96_demo.py`'s real 300uL filter
      tip (`total_tip_length` confirmed via direct PyLabRobot introspection
      at 59.9mm, well past the 35.2mm placeholder): `core96Head.tipLength`/
      `tipGeometry.parameters.height` both read `59.9` mid-sequence (were
      `35.2` before any pickup), each tip mesh's own local `position.y`
      correctly at `-29.95` (half the new length), and
      `tipMaterial.color` correctly `0xffd54f` (yellow, the <=300uL
      bucket) instead of the flat fallback amber -- confirmed visually too
      (0.25x speed again) as a noticeably longer yellow cone grid reaching
      further down toward the rack.

      Third follow-up fix (same round, user-reported): "The tips seems to
      go through the well plates, indicating the z-coordinate is too
      low." Correct, and a direct consequence of fixing the tip length
      right before this: `animateCore96Op()`'s `targetZ` put the *group
      origin* (the block's own bottom face, i.e. the tips' own wide base
      -- see the constructor's own comment) at the resource's reported top
      plus a small clearance, with no compensation for the tips hanging
      *below* that origin by their own length -- exactly the body-vs-
      tip-point distinction `animateChannelOp()`'s own `targetZ` comment
      already explains for a single `Channel`, just missed here. Once the
      tips went from the 35.2mm placeholder to a real 59.9mm length (the
      fix two messages up), the gap between "block origin" and "tip's own
      point" grew enough to plainly bury the tips' points ~57mm through
      whatever labware they were "touching" instead of stopping at its
      surface. Fixed by adding `+ tipLength` to `targetZ`, mirroring
      `animateChannelOp()`'s `entry.z + tipLength` exactly; `tipLength`
      passed as an explicit override for `pick_up_tips96` specifically
      (the *new* tip about to be grabbed, from `msg.tip_length_mm` --
      `core96Head.tipLength` is still the *previous* pickup's value until
      `setTips()` runs in that op's own `onArrive`), every other op
      falling back to `core96Head.tipLength` since the head is still
      carrying that same tip throughout -- the identical override pattern
      `animateChannelOp()` already uses for a single channel's own
      pick_up_tips case. Verified live with exact arithmetic, not just a
      visual check: polled `core96Head.pos.z` every 100ms through a full
      (0.25x-speed) run to find the deepest real descend
      (`z=260.22, tipLength=59.9` -> tip apex world z `= 260.22 - 59.9 =
      200.32`), independently computed the source plate's own real top
      from its scene-graph node (`183.12 [group world y] + 14.2
      [declared size_z] = 197.32`) `+ CORE96_ENGAGE_CLEARANCE_MM (3) =
      200.32` -- an exact match, confirming the tips now stop precisely at
      the intended clearance above the plate's real surface, not
      wherever the frontend happens to render its (thin-slab-simplified)
      mesh. Re-verified both plates' volumes still transferred correctly
      end-to-end (`source_plate_well_A1.volume === 150`,
      `dest_plate_well_H12.volume === 50`) with a clean console throughout.

      Fourth follow-up fix (same round, user-reported): "The plate lights
      up instead of the wells during pipetting, also there is no
      animation for aspiration and dispense like in the multichannel
      pipettes." Both correct, and both straightforward omissions rather
      than anything wrong in the sequencing/Z work above. The
      aspirate96/dispense96 handler called `flashResource(msg.resource)`
      -- `msg.resource` is the *plate*, since `resource_event()` computes
      one top-level anchor point for the whole call the same way
      `pick_up_tips96`/`drop_tips96` do (that part is correct for those
      two -- there's genuinely one rack, not 96 spots, to anchor
      *motion* to) -- while a single channel's own aspirate/dispense
      flashes the one specific *well* it targeted
      (`flashResource(entry.resource)`). Fixed by flashing each well in
      `msg.wells` individually instead (the same array already used for
      `applyEmbeddedResourceState()`, one more call alongside it) --
      `msg.resource` no longer touched here at all. Separately,
      `Channel.pulse()` (a brief white flash on the channel's own body)
      and `Channel.flowPulse()` (a scrolling gradient texture on the
      carried tip, simulating liquid moving through it) were never called
      anywhere for the 96-head, since nothing in this round's earlier
      work had added equivalents. Added `Core96Head.pulse()`
      (identical to `Channel.pulse()`, reverting to `CORE96_EMPTY_COLOR`
      instead of a channel body's own fixed grey) and
      `Core96Head.flowPulse(direction)` -- applied to the *one* shared
      `tipMaterial` all 96 cones already use (see the constructor's own
      sharing comment), so animating it once visibly flows through all 96
      simultaneously instead of needing 96 independent animations; own
      cloned aspirate/dispense flow textures (mirroring `Channel`'s own
      per-instance clones) so this doesn't fight over texture `.offset`
      state with whichever `Channel` might be flow-pulsing at the same
      moment. Neither is routed through the leg-motion `AnimationQueue` --
      like `Channel`'s own versions, both are fire-and-forget decorative
      overlays timed to when an op visually arrives, not additional legs
      to sequence.

      Verified live: since both effects are brief (a few hundred ms, even
      scaled by the HUD's speed setting), a single screenshot proved
      unreliable for catching them (screenshot latency alone exceeded the
      window), so verified by densely polling the actual THREE.js material
      state every 20ms across a full run instead: `core96Head.body.
      material.color` was observed to actually reach pure white
      (`sawPulse: true`), `core96Head.tipMaterial.map` was observed
      non-null at some point (`sawFlowMap: true`, confirming the flow
      texture really gets applied), a sampled well's own mesh color was
      observed reaching pure white (`sawWellFlash: true`), and -- the
      actual regression check -- the *plate's* own mesh color was
      confirmed to *never* reach white across the whole run
      (`sawPlateFlash: false`), directly disproving the original "plate
      lights up" complaint under the fix. Both plates' volumes still
      correct end-to-end afterward, clean console throughout.

## Review round 40

User-reported: "Now I would like the 8-channel pipettes to move with the
96 well head as discussed earlier. Right now the eight channels seems to
be stationary during the core96 well operations." The cross-mechanism X
sharing round 37 deferred (no second unit to verify it against at the
time) -- implemented now that `Core96Head` exists.

- [x] **Real offset value, not a guess**: PyLabRobot's own
      `STAR_backend.py` documents the exact quantity needed --
      `_head96_request_x_offset()` reads it live from the instrument's own
      EEPROM ("X-arm carriage center <-> CoRe 96 head channel A1"), and
      its own comment gives a representative magnitude: "the head96
      offset is ~10x the iSWAP's (~368 mm vs ~34 mm)". `CORE96_X_OFFSET_MM
      = 368` in `gantry.js`, documented as representative (it's a live
      EEPROM read on real hardware specifically because it varies per
      physical unit) rather than universal. Direction -- which mechanism
      sits at higher X -- isn't in that source; taken from user direction
      instead ("the 8 channel pipette should be to the right of the core96
      head" -- initially described as a Y relationship, corrected to X
      one message later).
- [x] **Bidirectional dragging**: `animateChannelGroupOp()` (every
      channel op) now also calls a new `nudgeCore96Head(x)` per gantry
      pass, converting that pass's channel-frame x into the head's own
      frame; `animateCore96Op()` (every 96-head op) now also calls
      `nudgeChannel()` for all 8 channels, converting the other direction.
      `nudgeCore96Head()` mirrors `nudgeChannel()`'s own "dragged along,
      not actually doing anything" shape and duration exactly (same
      `RISE_MS`/`X_MOVE_MS`/`Y_MOVE_MS`/`DESCEND_MS+HOLD_MS+RETRACT_MS`
      legs), so whichever mechanism is "idle" this particular op still
      finishes its drag in lockstep with the "active" one, the same
      lockstep reasoning `nudgeChannel()`'s own docstring already gives
      for idle channels within a multi-channel op.
- [x] **Rest positions now derived, not independently guessed**: per
      follow-up user direction ("set the starting position of the 96 head
      at just above its trash can, while putting the 8 channels at the
      corresponding x-offset"), `CORE96_REST_X_MM`/`CORE96_REST_Y_MM`
      changed from an arbitrary out-of-the-way spot to
      `STARDeck().get_trash_area96()`'s own real position (confirmed live:
      `Coordinate(-58.200, 106.000, 216.400)`) -- a real deck landmark
      instead of a made-up one. `Channel`'s own initial rest X changed
      from a hardcoded `0` to `CORE96_REST_X_MM + CORE96_X_OFFSET_MM`,
      so the two mechanisms start out already consistent with the
      relationship they're dragged to maintain, rather than only
      converging on it once the first op fires.

      A mid-conversation aside from the user, while this was in progress,
      described the 96-head's/channels' own natural leftward/rightward
      *reach* each barely clearing their own respective trash -- confirmed
      as intentional context (real `trash_core96`/`trash` sit at opposite
      deck extremes, `x=-58.2` and `x=1340` on a 1545mm-wide `STARDeck`,
      confirmed live), not a bug to fix.

      Verified live: the core invariant (`channels[i].pos.x -
      core96Head.pos.x === CORE96_X_OFFSET_MM`, in both directions) held
      exactly across a standalone script exercising both mechanisms in one
      run (`pick_up_tips96`/`drop_tips96` then a single-channel
      `pick_up_tips`/`discard_tips`) -- confirmed both immediately after
      the sign fix (`+368` the intended direction) and mid-sequence during
      active dragging, not just at rest. Fresh rest-state confirmed
      exactly: `core96Head.pos` `{x: -58.2, y: 106}` (matching
      `trash_core96` exactly), `channels[0].pos.x` `309.8` (`=
      -58.2 + 368`). Re-ran `core96_demo.py` (which now also exercises the
      new channel-dragging path on every 96-head op, even though it never
      uses the channels itself) end-to-end -- both plates' volumes still
      transferred correctly, clean console, offset invariant held
      mid-sequence too. 30/30 frontend tests and 24/24 Python tests
      unaffected.

## Review round 41

User-requested new feature: "Using core-gripper to move plates from
different sites on the carrier or to and from the inheco ODTC." Two of the
8 pipetting channels grab a pair of gripper pads and use them to clamp and
carry a plate -- render the pads as small rectangular blocks attached to
those channels "just like tips," and show the plate itself actually moving.
Scoped via `AskUserQuestion` up front: **require an explicit
`use_arm="core"`** (the iSWAP arm stays the existing log-only/unanimated
path), **model persistent pad attachment** (pads stay clamped onto the same
two channels across moves, matching real hardware, rather than re-attaching
every single pickup), **reparent the real plate mesh** (not a separate
carried-plate glyph), and **read which channels from the call** (`channel_1`/
`channel_2`/`core_front_channel`, mirroring `STARBackend`'s own API) rather
than hardcoding a pair.

- [x] **Real mechanics confirmed via source read**: `STARBackend.
      pick_up_resource`/`drop_resource`/`move_picked_up_resource` all
      default to `use_arm="iswap"`; `use_arm="core"` routes to
      `core_pick_up_resource()`/`core_release_picked_up_resource()`, which
      resolve `front_channel`/`back_channel = front_channel - 1` (default
      `core_front_channel=7`, i.e. channels 6/7; the deprecated
      `channel_1`/`channel_2` pair resolves to the same thing:
      `front_channel = channel_2 - 1`, asserting `channel_1 + 1 ==
      channel_2`), and gate a "channels attach to the pads first" step on
      `self.core_parked` (`if self.core_parked: await
      self.pick_up_core_gripper_tools(front_channel=front_channel)`) --
      exactly the persistent-attachment behavior the user asked to model.
      `drop_resource`'s own `return_core_gripper: bool = True` controls
      whether that attachment is undone afterward.
- [x] **Two real staleness bugs found and fixed in `events.py`**: every
      existing single-resource event (`resource_event()`/`resource_point()`)
      reads the resource's own *current* `get_absolute_location()` --
      correct for pickup (nothing has moved it yet), but wrong for
      `drop_resource`/`move_picked_up_resource`: `LiquidHandler` only
      reassigns a resource to its real new parent *after* awaiting the
      backend call these events are raised from, so at broadcast time the
      resource is still parented at its *old* location. Fixed with two new
      helpers, `resource_drop_point(drop)`/`resource_move_point(move)`,
      built on a shared `_relocated_point()`: both use the already-resolved
      absolute `Coordinate` PyLabRobot hands the backend directly
      (`drop.destination`, confirmed the raw resolved value of whatever
      `to=` was passed; `move.location`, confirmed the raw `to=` argument
      of `move_picked_up_resource()` itself) instead of a live lookup.
      Verified standalone: dropping a plate onto a `Coordinate(200, 150,
      50)` destination reported `x=263.88` (`= 200 + size_x/2`), not the
      plate's still-old `x=347.88` -- and the same live check for a
      `move_picked_up_resource` leg.
- [x] **Chatterbox kwarg-forwarding gap, patched rather than special-cased**
      (per user direction: "Consider monkey patch the pylabrobot chatterbox
      to forward the extra kwargs"): `LiquidHandlerChatterboxBackend.
      pick_up_resource`/`move_picked_up_resource`/`drop_resource` take only
      their bare dataclass argument -- no `**backend_kwargs` at all, unlike
      every other chatterbox method (`pick_up_tips`/`aspirate`/`dispense`/
      etc. all accept it). `_patch_chatterbox_resource_kwargs()` in
      `visualizer_backend.py` monkey-patches those three methods once, at
      import time, to accept and print `**backend_kwargs` like their
      siblings -- letting `VisualizerBackend`'s own three methods use the
      exact same established blind-forward-and-peek pattern
      `pick_up_tips`/`aspirate`/`dispense` already use, instead of a
      one-off "silently drop these specific kwargs" branch.
- [x] **`VisualizerBackend` event design**: `pick_up_resource`/
      `move_picked_up_resource`/`drop_resource` all peek `use_arm` out of
      `backend_kwargs` (default `"iswap"`); anything but `"core"` keeps the
      original plain `resource_event()` broadcast, unchanged. A `"core"`
      pickup resolves `back_channel`/`front_channel` (mirroring
      `STARBackend`'s own resolution above), computes `needs_attach =
      (back_channel, front_channel) != self._core_gripper_channels` (new
      `__init__` state, mirroring `STARBackend`'s own `core_parked`
      tracking) and updates that state, then broadcasts
      `core_pick_up_resource` with `back_channel`/`front_channel`/
      `needs_attach`. A `"core"` drop broadcasts `core_drop_resource` via
      `resource_drop_point()` (not `resource_event()`) with the same two
      channel fields plus `return_core_gripper`, and only resets
      `_core_gripper_channels` to `None` when that's true. A `"core"` move
      broadcasts `core_move_picked_up_resource` via `resource_move_point()`.
      Verified standalone (`VisualizerBackend` against a fake server, no
      websocket): a full pickup → move → drop → repeat-pickup-different-
      channels → deprecated-`channel_1`/`channel_2` → default-`use_arm`
      sequence, asserting every field and the `_core_gripper_channels`
      state transition at each step -- all passed.
- [x] **Frontend: pad glyphs attached to channels, "just like tips"**:
      `Channel` gained a `padMesh` (a small `BoxGeometry`, hidden by
      default) and `setPad(visible)`, hanging below the body at the same
      spot `tipMesh` does (a channel only ever carries one or the other in
      real use). `setGripperPadChannels(back, front)` toggles exactly two
      channels' pads at once, called from `"core_pick_up_resource"` only
      when `needs_attach` is true, and from `"core_drop_resource"` (clearing
      both) only when `return_core_gripper` is true -- otherwise pads stay
      exactly where they were, modeling the persistent attachment the user
      asked for. New `CORE_GRIPPER_PAD_COLOR` (`categories.js`) plus a
      legend entry.
- [x] **Frontend: the carried plate is the real mesh, reparented**: a new
      `CarriedPlate` class wraps a `MotionUnit` whose `pos` is the
      resource's own top-center point (the same "meaning" every op's
      `msg.x/y/z` already has), converting to the group's left-front-bottom
      local frame on every tick (the mirror image of `events.py`'s
      `_relocated_point()`) so `animateCarriedPlateTo()`'s callers never
      have to do that conversion themselves. `"core_pick_up_resource"`
      reparents the resource's real scene-graph group into `gantryGroup`
      via `Object3D.attach()` (world-transform-preserving -- no jump) and
      wraps it in a fresh `CarriedPlate`; `"core_drop_resource"` reparents
      it back under a new `sceneRoot` (set once via `setSceneRoot()`, since
      `gantry.js` otherwise never touches it) at its real absolute
      destination -- not into whatever THREE group actually corresponds to
      its new PyLabRobot parent, since this project's scene tree only ever
      gets rebuilt wholesale from a fresh "scene" message anyway, and a flat
      `sceneRoot` child renders identically (position is already absolute
      deck mm).
- [x] **Two live-verified frontend timing bugs, both races between "when a
      websocket op message is handled" (near-instant; the backend has no
      reason to sleep between a move's own pickup/drop calls) and "when the
      ~1.1s leg animation for that op actually finishes" (deferred, via an
      `onArrive` callback)**:
      1. Deferring the reparent + `CarriedPlate` *creation* to the pickup's
         own `onArrive` left `carriedPlate` still `null` when the very next
         op's handler ran (routinely well before that 1.1s elapsed) --
         its `animateCarriedPlateTo()` call silently found nothing to
         enqueue onto. Fixed by doing the reparent/creation synchronously,
         in the event handler itself, not deferred at all -- safe, since
         nothing enqueues motion onto it until a *later* op actually calls
         `animateCarriedPlateTo()`, so it keeps rendering at the exact same
         (world-transform-preserved) point in the meantime.
      2. The mirror-image bug, introduced while fixing the first: setting
         `carriedPlate = null` synchronously in the drop handler (to mirror
         the fix above) orphaned that same drop's own just-enqueued legs
         from the only thing that ever ticks them (`updateCarriedPlate()`
         reads the current module-level `carriedPlate`) -- the resource
         visibly never reached its destination, frozen wherever it was when
         the handler ran. Fixed by simply not nulling it: an idle
         `AnimationQueue` is already a no-op once drained, and the next
         pickup (for this or any other resource) unconditionally overwrites
         the reference anyway.

      Both caught by a deterministic Node test (no browser, stubbed
      `document`/`THREE` canvas context, a hand-built fake scene fed
      through the real `scene-builder.js`) firing a pickup → drop → pickup
      → drop burst with *zero* real time between calls -- worse than any
      real backend spacing, and immune to the live browser's own
      unpredictable requestAnimationFrame/`setInterval` throttling on a
      backgrounded automation tab, which made this race nearly impossible
      to catch by screenshot timing alone (screenshots taken between tool
      calls kept landing on the *fully settled* final state regardless of
      when the bug was present, since a whole 3-move sequence can complete
      client-side well under 50ms once state changes stopped being
      artificially paced by the old 1.1s-deferred `onArrive`). Not kept as
      a committed test file, per `tests/frontend/README.md`'s own stated
      scope ("no THREE.js rendering, no DOM" -- everything at that level is
      "covered by hand" instead, matching every other rendering-heavy
      change in this file); this write-up is that hand-coverage record.
- [x] **New demo**: `examples/core_gripper_demo.py` moves a plate between
      two carrier sites and onto/off the Inheco ODTC, all via
      `lh.move_plate(..., use_arm="core")` -- PyLabRobot's own real API,
      no visualizer-specific call needed. The first two moves pass
      `return_core_gripper=False` so the pads stay attached across all
      three (exercising `needs_attach=False` on the second/third pickups);
      the last leaves PyLabRobot's own default (`True`), the one that makes
      the pad glyphs disappear again. Verified live end-to-end multiple
      times: final resting position (`world x/y/z` read via
      `matrixWorld.elements`) matched the real PyLabRobot LFB coordinate
      for the destination carrier site exactly on every run
      (`(284.000, 071.500, 183.120)`, `mapPoint`-converted), the resource's
      THREE parent correctly ended at the flat `sceneRoot` (not left under
      `gantryGroup`), and both pad glyphs correctly disappeared only after
      the final `return_core_gripper=True` drop.

## Stretch / explicitly deferred (not v1)

- [ ] Event capture-to-file (durable, survives a process restart) +
      scrubbing/seek UI — in-memory replay from Phase 4 covers the common
      "I missed it" / "watch that again" case within one run
- [ ] iSWAP arm animation (still log-only/unanimated by design -- see
      "Review round 41"; only the CO-RE gripper (`use_arm="core"`) is
      animated)
- [ ] Hamilton Vantage support
- [ ] Firmware-accurate motion timing

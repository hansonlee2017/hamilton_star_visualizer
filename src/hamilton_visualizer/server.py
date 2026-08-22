"""WebSocket + static-file server that streams visualizer state to the browser.

Runs inside the same asyncio event loop as your PyLabRobot protocol -- there
is no separate process to manage. Typical usage in a protocol script::

    server = VisualizerServer()
    await server.start()  # prints the URL to open

    lh = LiquidHandler(backend=VisualizerBackend(real_backend, server), deck=deck)
    await lh.setup()
    ... run your protocol as normal ...
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# src/hamilton_visualizer/server.py -> repo root -> frontend/
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

# Cap on how long a replayed gap between two events can be, in seconds --
# without this, replaying a run where you took a real 10-minute break
# between steps would make the browser wait 10 real minutes too.
MAX_REPLAY_GAP = 2.0

# How many past events (scene/state/op) to keep for replay. Old events are
# dropped once the buffer is full -- a very long run's earliest steps won't
# replay, but the run stays watchable live the whole time either way.
MAX_EVENT_HISTORY = 5000


def _json_safe(value: Any) -> Any:
  """Recursively replace non-finite floats (``inf``/``-inf``/``nan``) with
  ``None``. Python's ``json.dumps`` happily emits these as the bare tokens
  ``Infinity``/``-Infinity``/``NaN`` (a non-standard extension), which is
  *not* valid JSON -- e.g. a ``Trash`` resource's ``max_volume`` is
  ``float("inf")`` by design, and shipping that verbatim breaks
  ``JSON.parse`` in the browser for every message that resource appears in.
  """

  if isinstance(value, float):
    return value if value == value and value not in (float("inf"), float("-inf")) else None
  if isinstance(value, dict):
    return {k: _json_safe(v) for k, v in value.items()}
  if isinstance(value, list):
    return [_json_safe(v) for v in value]
  return value


class VisualizerServer:
  """Owns the websocket connections and the latest scene graph."""

  def __init__(self, host: str = "127.0.0.1", port: int = 8765):
    self.host = host
    self.port = port
    self._clients: Set[WebSocket] = set()
    self._send_locks: Dict[WebSocket, asyncio.Lock] = {}
    self._scene: Optional[Dict[str, Any]] = None
    self._num_channels: Optional[int] = None
    # Opt-in HUD run-param fields (see set_run_params()) -- empty means "no
    # protocol-specific inputs," which is most demos; the HUD row stays
    # hidden entirely rather than showing inputs a script never reads.
    self._run_params_fields: List[Dict[str, Any]] = []
    # resource name -> its most recent "state" event, so a client connecting
    # *after* e.g. a tip rack's initial "these spots have tips" broadcast
    # (which happens once, synchronously, during setup() -- often well
    # before the 10s grace period most demos wait before doing anything
    # else) still sees the correct current picture instead of an empty one.
    self._latest_state: Dict[str, Dict[str, Any]] = {}
    self._events: Deque[Tuple[float, Dict[str, Any]]] = deque(maxlen=MAX_EVENT_HISTORY)
    self._uv_server: Optional[uvicorn.Server] = None
    self._serve_task: Optional["asyncio.Task[None]"] = None
    # Set when a browser clicks "Start Protocol" -- see wait_for_start().
    self._start_event = asyncio.Event()
    # Whatever JSON-serializable dict the "Start Protocol" click sent along
    # (e.g. a demo's own sample-count/volume fields) -- opaque to this class,
    # just handed back verbatim by wait_for_start(). {} if the browser sent
    # no params (or an older frontend that doesn't send any at all).
    self._start_params: Dict[str, Any] = {}
    # Set by a protocol script calling mark_finished() -- gates "reset" (see
    # wait_for_reset()/reset_for_new_run()): a run in progress can't be
    # interrupted from the browser, only restarted once it's actually done.
    self._finished_event = asyncio.Event()
    # Set when a browser clicks "Reset" *after* mark_finished() -- see
    # wait_for_reset().
    self._reset_event = asyncio.Event()
    self.app = self._build_app()

  def _build_app(self) -> FastAPI:
    if not FRONTEND_DIR.is_dir():
      raise RuntimeError(
        f"Frontend directory not found at {FRONTEND_DIR}. "
        "hamilton-visualizer must be run from a checkout of the repo "
        "(it is not packaged into installed wheels)."
      )

    app = FastAPI()

    # index.html and every frontend/*.js module are what you'd actually be
    # iterating on; explicit routes here (matched before the /static mount
    # below) keep the browser from serving a stale cached copy after an
    # edit -- easy to lose time to otherwise, since FileResponse/
    # StaticFiles don't set no-cache by default. This used to be a single
    # hardcoded "/static/main.js" route, back when main.js was the only
    # frontend file -- once it was split into coordinates.js/gantry.js/
    # thermocycler.js/etc. (see docs/PLAN.md's "Review round 36"), every
    # *other* module silently fell through to the generic mount below and
    # kept its default (cacheable) headers, which is exactly how a browser
    # ended up running a stale mix of old and new modules after later
    # edits (round 38: a user's still-open tab kept animating the
    # thermocycler with pre-AnimationQueue logic well after the fix
    # shipped). Matching any top-level *.js file, not just main.js, is what
    # actually fixes that instead of needing a new hardcoded route added
    # every time this project's frontend grows another module.
    #
    # The vendored third-party files under frontend/vendor/ are pinned and
    # don't change, so they're deliberately left cacheable via the mount --
    # this route's {filename} path parameter never matches a path
    # containing "/" (Starlette's default str converter, unlike the
    # "path" converter, stops at the next slash), so a request for
    # /static/vendor/three.module.js can never reach this function at all;
    # it always falls through to the mount below unchanged.
    no_cache = {"Cache-Control": "no-store"}

    @app.get("/")
    async def index() -> FileResponse:
      return FileResponse(FRONTEND_DIR / "index.html", headers=no_cache)

    @app.get("/static/{filename}")
    async def frontend_js(filename: str) -> FileResponse:
      candidate = FRONTEND_DIR / filename
      if filename.endswith(".js") and candidate.is_file():
        return FileResponse(candidate, headers=no_cache)
      # Not a top-level .js module this route owns -- e.g. a typo'd path,
      # or (in principle; nothing in frontend/ currently needs this) some
      # other top-level non-.js asset. Not the vendor/three-module.js case
      # above -- that never reaches here at all.
      raise HTTPException(status_code=404)

    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
      await websocket.accept()
      self._clients.add(websocket)
      self._send_locks[websocket] = asyncio.Lock()
      logger.info("client connected (%d total)", len(self._clients))
      try:
        if self._scene is not None:
          await self._send(
            websocket, {"type": "scene", "deck": self._scene, "num_channels": self._num_channels}
          )
        # Always sent, even when empty -- an empty list is what tells a
        # newly-connecting client's HUD to *not* render the run-params row,
        # same as every other client currently sees (see set_run_params()).
        await self._send(websocket, {"type": "run_params", "fields": self._run_params_fields})
        for state_event in self._latest_state.values():
          await self._send(websocket, state_event)
        await self._send(websocket, {"type": "start_status", "started": self._start_event.is_set()})
        await self._send(websocket, {"type": "run_status", "finished": self._finished_event.is_set()})
        while True:
          raw = await websocket.receive_text()
          try:
            msg = json.loads(raw)
          except ValueError:
            continue
          action = msg.get("action")
          # Guarded the same way "reset" is (not just by the browser
          # graying the button out): replaying over a run still in
          # progress would interleave replayed events with live ones on
          # every connected client, not just the one that clicked --
          # allowed before a run starts (nothing to conflict with yet) and
          # again once it's finished, same window "reset" opens in.
          if action == "replay" and (not self._start_event.is_set() or self._finished_event.is_set()):
            await self.replay(websocket)
          elif action == "start_protocol" and not self._start_event.is_set():
            params = msg.get("params")
            self._start_params = params if isinstance(params, dict) else {}
            self._start_event.set()
            await self.broadcast({"type": "start_status", "started": True})
          elif action == "reset" and self._finished_event.is_set():
            # Guarded server-side, not just by the browser graying the button
            # out -- a run in progress must never be torn down mid-protocol
            # (see wait_for_reset()'s docstring).
            self._reset_event.set()
      except WebSocketDisconnect:
        pass
      finally:
        self._clients.discard(websocket)
        self._send_locks.pop(websocket, None)
        logger.info("client disconnected (%d total)", len(self._clients))

    return app

  async def start(self) -> None:
    """Start serving in the background of the current event loop."""

    config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
    self._uv_server = uvicorn.Server(config)
    self._serve_task = asyncio.create_task(self._uv_server.serve())
    while not self._uv_server.started:
      await asyncio.sleep(0.02)
    url = f"http://{self.host}:{self.port}"
    logger.info("visualizer running at %s", url)
    print(f"Hamilton Visualizer running at {url}")

  async def stop(self) -> None:
    if self._uv_server is not None:
      self._uv_server.should_exit = True
    if self._serve_task is not None:
      await self._serve_task

  async def wait_for_start(self) -> Dict[str, Any]:
    """Block until a browser clicks "Start Protocol" (the HUD button sends
    ``{"action": "start_protocol", "params": {...}}``), then return whatever
    ``params`` dict it sent (``{}`` if none).

    Call this after setting up your deck/scene and before running your
    actual protocol steps, instead of an arbitrary ``asyncio.sleep()`` --
    it means you can take as long as you want opening the browser and
    confirming the initial deck/tip/liquid state looks right, with no risk
    of the protocol racing ahead and starting before you're connected (see
    docs/PLAN.md's "Review round 7" for why that was worth fixing).

    ``params`` is opaque to this class -- a demo with its own HUD inputs
    (e.g. a sample count/volume) reads its own keys back out and is
    responsible for validating/clamping them, exactly as if they'd come from
    argv or a config file. Once ``_start_event`` is set, further
    "start_protocol" messages are ignored server-side (see the websocket
    handler above) -- a run's params, once accepted, can't be changed
    mid-run from the browser.
    """

    await self._start_event.wait()
    return self._start_params

  async def mark_finished(self) -> None:
    """Tell every connected client the current run has finished -- enables
    the HUD's "Reset" button (see ``wait_for_reset()``).

    Call this once your protocol's last step is done, before whatever your
    script does to keep the process alive afterward.
    """

    self._finished_event.set()
    await self.broadcast({"type": "run_status", "finished": True})

  async def wait_for_reset(self) -> None:
    """Block until a browser clicks "Reset" (only accepted, server-side,
    once :meth:`mark_finished` has been called -- see the websocket
    handler's ``action == "reset"`` guard).

    A protocol script that wants a "start the whole thing over" loop should
    await this right after :meth:`mark_finished`, then call
    :meth:`reset_for_new_run` and go back to building a fresh deck and
    calling :meth:`wait_for_start` again.
    """

    await self._reset_event.wait()

  async def reset_for_new_run(self) -> None:
    """Clear every piece of per-run state so the next
    ``wait_for_start()``/``wait_for_reset()`` cycle starts clean, and tell
    every connected client to reset its own UI (clear the event log,
    re-enable the parameter inputs, hide "Reset" again) via a ``"reset"``
    broadcast.

    Deliberately drops the scene/state/event history too -- "start the
    entire thing over" means exactly that; a stale Replay of the previous
    run would be confusing once a new one is underway.
    """

    self._start_event.clear()
    self._start_params = {}
    self._finished_event.clear()
    self._reset_event.clear()
    self._scene = None
    self._num_channels = None
    self._run_params_fields = []
    self._latest_state.clear()
    self._events.clear()
    await self.broadcast({"type": "reset"})

  async def set_run_params(self, fields: List[Dict[str, Any]]) -> None:
    """Declare this protocol's own HUD input fields (opt-in -- most demos
    never call this, and the HUD's run-params row stays hidden for them,
    see index.html's ``#run-params`` CSS).

    Call once, any time before the browser might connect (typically right
    after :meth:`start`, alongside :meth:`set_scene`). ``fields`` is a list
    of plain dicts the frontend renders generically -- see
    ``frontend/main.js``'s ``renderRunParams()`` for the exact schema, but
    in short, three field types:

    - ``{"type": "number", "id", "label", "min", "max", "step", "default",
      "suffix"}``: an editable numeric input.
    - ``{"type": "text", "id", "label", "length", "default"}``: an
      editable text input, restricted client-side to uppercase ``A-Z0-9``
      and truncated to exactly ``length`` characters as you type (see
      ``pixel_art_demo.py``'s "word" field). "Start Protocol" stays
      disabled while any text field's current value is shorter than its
      declared ``length`` -- there's no partial/padded fallback the way
      numeric fields clamp out-of-range values, since a too-short *word*
      has no sensible default to fall back to mid-edit.
    - ``{"type": "computed", "basis": ..., ...}``: a derived, read-only
      readout the frontend knows how to compute (currently just
      ``"picogreen_working_solution"``, what ``picogreen_demo.py`` uses for
      its "PicoGreen 195uL" readout).

    Both "number" and "text" fields' current values are read back into
    :meth:`wait_for_start`'s returned params dict, keyed by ``id``, when
    "Start Protocol" is clicked. An unrecognized ``basis`` on a "computed"
    field is simply not rendered, so this can grow new computed kinds
    without breaking older ones.

    This intentionally isn't a general form/formula system: it's exactly
    general enough to describe the one demo (picogreen_demo.py) that has
    ever needed protocol-specific inputs, without hardcoding *that* demo's
    fields into the shared frontend for every other script to carry around
    unused (see docs/PLAN.md's "Review round 30" for the "why does this
    show up for every demo" complaint this replaced).
    """

    self._run_params_fields = fields
    await self.broadcast({"type": "run_params", "fields": fields})

  async def set_scene(self, scene: Dict[str, Any], *, num_channels: int) -> None:
    """Cache the deck scene graph and push it to every connected client.

    Newly-connecting clients also receive it immediately (see the websocket
    handler above), so this only needs to be called once per ``setup()``.
    """

    self._scene = scene
    self._num_channels = num_channels
    self._latest_state.clear()
    await self.broadcast({"type": "scene", "deck": scene, "num_channels": num_channels})

  def record_resource_state(self, resource_name: str, state: Dict[str, Any]) -> None:
    """Update the cached "latest known state" for ``resource_name`` *without*
    broadcasting it live.

    For tip_spot/well resources, ``VisualizerBackend`` delivers live updates
    via a different, timing-correct path (embedded directly in the relevant
    "op" event, applied by the frontend when the gantry animation actually
    arrives -- see ``channel_ops_event()``'s docstring for why) instead of a
    live state-update callback. That path doesn't otherwise touch
    :attr:`_latest_state`, so without this, a *new* connection made after
    some operations have already happened would see those two categories'
    stale pre-run state (from the one-time initial broadcast) instead of
    what actually happened -- this keeps the snapshot new connections get
    in sync without reintroducing the timing race that path exists to avoid.
    """

    self._latest_state[resource_name] = {"type": "state", "resource": resource_name, "state": state}

  def schedule_broadcast(self, event: Dict[str, Any]) -> None:
    """Fire-and-forget variant of :meth:`broadcast` for use from *synchronous*
    callbacks (e.g. ``Resource.register_state_update_callback``), which can't
    ``await``. Must be called while an event loop is running.
    """

    asyncio.create_task(self.broadcast(event))

  async def broadcast(self, event: Dict[str, Any]) -> None:
    # Recorded regardless of whether anyone's currently connected, so a
    # client that opens the page late (or reconnects) can still `replay()`
    # everything that happened before it arrived.
    self._events.append((time.monotonic(), event))
    if event.get("type") == "state":
      # Keep only the latest state per resource -- see _latest_state's
      # docstring for why new connections need this, not just history.
      self._latest_state[event["resource"]] = event
    for client in list(self._clients):
      try:
        await self._send(client, event)
      except Exception:  # noqa: BLE001 - a dead socket shouldn't break the run
        self._clients.discard(client)
        self._send_locks.pop(client, None)

  async def replay(self, websocket: WebSocket) -> None:
    """Re-send this server's whole recorded event history to ``websocket``,
    one client at a time, pacing sends to approximate the original timing
    (see ``MAX_REPLAY_GAP``).

    Always starts with the current scene, whether or not it's still in the
    (capped) event history -- the frontend's scene-load handling is what
    resets gantry position/tip/volume colors before replaying the rest, so
    skipping it would replay deltas against a stale or empty scene.
    """

    events = list(self._events)
    if not events and self._scene is None:
      return
    if self._scene is not None:
      await self._send(
        websocket, {"type": "scene", "deck": self._scene, "num_channels": self._num_channels}
      )
      # Avoid an immediate, redundant second scene-load: history's leading
      # entries are almost always the original set_scene() broadcast(s) we
      # just resent above. Only strips a *leading* run of scene events, so a
      # later, genuinely different scene mid-history still replays.
      while events and events[0][1].get("type") == "scene":
        events.pop(0)
    if not events:
      return
    prev_ts = events[0][0]
    for ts, event in events:
      gap = min(max(ts - prev_ts, 0.0), MAX_REPLAY_GAP)
      if gap > 0:
        await asyncio.sleep(gap)
      prev_ts = ts
      try:
        await self._send(websocket, event)
      except Exception:  # noqa: BLE001 - client disconnected mid-replay
        return

  async def _send(self, websocket: WebSocket, event: Dict[str, Any]) -> None:
    # Serialized per-connection: broadcast() and replay() can both be
    # sending to the same client around the same time (e.g. a live run
    # still trickling in while someone replays), and concurrent writes to
    # one websocket are not safe to interleave.
    lock = self._send_locks.get(websocket)
    message = json.dumps(_json_safe(event))
    if lock is None:
      await websocket.send_text(message)
    else:
      async with lock:
        await websocket.send_text(message)

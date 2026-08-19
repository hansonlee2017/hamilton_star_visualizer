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
from typing import Any, Deque, Dict, Optional, Set, Tuple

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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
    self._events: Deque[Tuple[float, Dict[str, Any]]] = deque(maxlen=MAX_EVENT_HISTORY)
    self._uv_server: Optional[uvicorn.Server] = None
    self._serve_task: Optional["asyncio.Task[None]"] = None
    self.app = self._build_app()

  def _build_app(self) -> FastAPI:
    if not FRONTEND_DIR.is_dir():
      raise RuntimeError(
        f"Frontend directory not found at {FRONTEND_DIR}. "
        "hamilton-visualizer must be run from a checkout of the repo "
        "(it is not packaged into installed wheels)."
      )

    app = FastAPI()

    # index.html and main.js are what you'd actually be iterating on; explicit
    # routes here (matched before the /static mount below) keep the browser
    # from serving a stale cached copy after an edit -- easy to lose time to
    # otherwise, since FileResponse/StaticFiles don't set no-cache by default.
    # The vendored third-party files under frontend/vendor/ are pinned and
    # don't change, so they're left cacheable via the mount.
    no_cache = {"Cache-Control": "no-store"}

    @app.get("/")
    async def index() -> FileResponse:
      return FileResponse(FRONTEND_DIR / "index.html", headers=no_cache)

    @app.get("/static/main.js")
    async def main_js() -> FileResponse:
      return FileResponse(FRONTEND_DIR / "main.js", headers=no_cache)

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
        while True:
          raw = await websocket.receive_text()
          try:
            msg = json.loads(raw)
          except ValueError:
            continue
          if msg.get("action") == "replay":
            await self.replay(websocket)
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

  async def set_scene(self, scene: Dict[str, Any], *, num_channels: int) -> None:
    """Cache the deck scene graph and push it to every connected client.

    Newly-connecting clients also receive it immediately (see the websocket
    handler above), so this only needs to be called once per ``setup()``.
    """

    self._scene = scene
    self._num_channels = num_channels
    await self.broadcast({"type": "scene", "deck": scene, "num_channels": num_channels})

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

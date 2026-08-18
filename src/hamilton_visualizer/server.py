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
from pathlib import Path
from typing import Any, Dict, Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# src/hamilton_visualizer/server.py -> repo root -> frontend/
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


class VisualizerServer:
  """Owns the websocket connections and the latest scene graph."""

  def __init__(self, host: str = "127.0.0.1", port: int = 8765):
    self.host = host
    self.port = port
    self._clients: Set[WebSocket] = set()
    self._scene: Optional[Dict[str, Any]] = None
    self._num_channels: Optional[int] = None
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

    @app.get("/")
    async def index() -> FileResponse:
      return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
      await websocket.accept()
      self._clients.add(websocket)
      logger.info("client connected (%d total)", len(self._clients))
      try:
        if self._scene is not None:
          await websocket.send_text(
            json.dumps(
              {"type": "scene", "deck": self._scene, "num_channels": self._num_channels}
            )
          )
        while True:
          # The browser doesn't send anything meaningful back; this just
          # blocks until the socket closes so we notice disconnects.
          await websocket.receive_text()
      except WebSocketDisconnect:
        pass
      finally:
        self._clients.discard(websocket)
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
    if not self._clients:
      return
    message = json.dumps(event)
    dead = []
    for client in self._clients:
      try:
        await client.send_text(message)
      except Exception:  # noqa: BLE001 - a dead socket shouldn't break the run
        dead.append(client)
    for client in dead:
      self._clients.discard(client)

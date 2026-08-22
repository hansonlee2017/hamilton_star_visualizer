"""``ThermocyclerBackend`` decorator that streams structured events to a
``VisualizerServer`` while forwarding every call unchanged to a wrapped
backend (a real Inheco/Thermo Fisher backend, or
``pylabrobot.thermocycling.chatterbox.ThermocyclerChatterboxBackend`` for
device-free development) -- the same wrap-and-forward pattern
``VisualizerBackend`` uses for ``LiquidHandlerBackend``, applied to
PyLabRobot's separate ``Thermocycler``/``ThermocyclerBackend`` machine
type (see ``pylabrobot.thermocycling``).

Unlike ``LiquidHandlerBackend``, whose every call carries the resource(s)
it acts on as op arguments, a ``ThermocyclerBackend`` is permanently bound
to exactly one ``Thermocycler`` resource (one backend instance per
machine, set once at construction -- see ``Machine.__init__``), and its
calls carry only plain values (temperatures, a ``Protocol``), never a
resource reference. So this class needs the resource's own name handed to
it directly at construction, not read off an op the way
``VisualizerBackend`` does.

This visualizer deliberately does not simulate real cycling time (see this
project's README/PLAN for why -- the same "animation timing is decoupled
from backend timing" philosophy the liquid-handling side already uses):
``run_protocol()`` is forwarded to a chatterbox-style inner backend that
completes instantly, and it's the *frontend* that manufactures a fixed
5-second "block shimmering" animation regardless of that -- see
``frontend/main.js``'s handling of the ``thermocycler_run_protocol`` op
event.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pylabrobot.thermocycling.backend import ThermocyclerBackend
from pylabrobot.thermocycling.standard import BlockStatus, LidStatus, Protocol

from hamilton_visualizer.server import VisualizerServer


def summarize_protocol(protocol: Protocol) -> str:
  """A short, human-readable line for the tooltip -- e.g. "95.0C 0:30, 55.0C
  0:30, 72.0C 1:00 (x30)" -- from a real PyLabRobot ``Protocol`` (see
  ``pylabrobot.thermocycling.standard``: a list of ``Stage``s, each a list
  of ``Step``s with ``temperature``/``hold_seconds``, repeated
  ``stage.repeats`` times).

  Multi-zone steps (``len(step.temperature) > 1``) show every zone's
  temperature, slash-separated, since a real block can hold different
  zones at different temperatures simultaneously.
  """

  def format_step(step) -> str:
    temps = "/".join(f"{t:g}C" for t in step.temperature)
    minutes, seconds = divmod(int(step.hold_seconds), 60)
    return f"{temps} {minutes}:{seconds:02d}"

  stage_strs = []
  for stage in protocol.stages:
    steps_str = ", ".join(format_step(step) for step in stage.steps)
    stage_strs.append(f"{steps_str} (x{stage.repeats})" if stage.repeats > 1 else steps_str)
  return "; ".join(stage_strs)


class VisualizerThermocyclerBackend(ThermocyclerBackend):
  """Wraps ``inner`` and mirrors every call to ``server``, tagged with
  ``resource_name`` (see this module's docstring for why that has to be
  passed in directly rather than read off an op).
  """

  def __init__(self, inner: ThermocyclerBackend, server: VisualizerServer, *, resource_name: str):
    super().__init__()
    self._inner = inner
    self._server = server
    self._resource_name = resource_name

  # -- lifecycle --------------------------------------------------------------
  async def setup(self) -> None:
    await self._inner.setup()

  async def stop(self) -> None:
    await self._inner.stop()

  # -- lid --------------------------------------------------------------------
  # Real Inheco ODTC hardware detail worth animating accurately: the lid
  # "opens and closes by horizontal move" (a slide, not a hinge) -- see
  # custom_labware.py's inheco_odtc_thermocycler() docstring. The event name
  # alone carries that; frontend/main.js is what actually renders it as a
  # horizontal slide instead of a generic rotate.
  async def open_lid(self, **backend_kwargs) -> None:
    await self._inner.open_lid(**backend_kwargs)
    await self._server.broadcast(
      {"type": "op", "op": "thermocycler_open_lid", "resource": self._resource_name}
    )

  async def close_lid(self, **backend_kwargs) -> None:
    await self._inner.close_lid(**backend_kwargs)
    await self._server.broadcast(
      {"type": "op", "op": "thermocycler_close_lid", "resource": self._resource_name}
    )

  # -- temperature control ----------------------------------------------------
  # Deliberately no visualizer event for these -- they're the low-level
  # primitives run_protocol() itself calls internally on a real backend;
  # broadcasting the whole protocol at run_protocol() (below) is the
  # meaningful, tooltip-worthy moment, not each individual temperature set.
  async def set_block_temperature(self, temperature: List[float], **backend_kwargs) -> None:
    await self._inner.set_block_temperature(temperature, **backend_kwargs)

  async def set_lid_temperature(self, temperature: List[float], **backend_kwargs) -> None:
    await self._inner.set_lid_temperature(temperature, **backend_kwargs)

  async def deactivate_block(self, **backend_kwargs) -> None:
    await self._inner.deactivate_block(**backend_kwargs)

  async def deactivate_lid(self, **backend_kwargs) -> None:
    await self._inner.deactivate_lid(**backend_kwargs)

  # -- the actual cycling run --------------------------------------------------
  async def run_protocol(self, protocol: Protocol, block_max_volume: float, **backend_kwargs) -> None:
    await self._inner.run_protocol(protocol, block_max_volume, **backend_kwargs)
    summary = summarize_protocol(protocol)
    # Cached (not just broadcast) so a client that connects *after* this
    # run -- or reloads the page -- still sees the last-run protocol in the
    # tooltip, the same reason channel_ops_event()'s embedded resource
    # state gets folded into VisualizerServer's cache elsewhere.
    self._server.record_resource_state(self._resource_name, {"protocol_summary": summary})
    await self._server.broadcast(
      {
        "type": "op",
        "op": "thermocycler_run_protocol",
        "resource": self._resource_name,
        "protocol_summary": summary,
      }
    )

  # -- status queries -- plain forwarding, no visualizer event -----------------
  async def get_block_current_temperature(self, **backend_kwargs) -> List[float]:
    return await self._inner.get_block_current_temperature(**backend_kwargs)

  async def get_block_target_temperature(self, **backend_kwargs) -> List[float]:
    return await self._inner.get_block_target_temperature(**backend_kwargs)

  async def get_lid_current_temperature(self, **backend_kwargs) -> List[float]:
    return await self._inner.get_lid_current_temperature(**backend_kwargs)

  async def get_lid_target_temperature(self, **backend_kwargs) -> List[float]:
    return await self._inner.get_lid_target_temperature(**backend_kwargs)

  async def get_lid_open(self, **backend_kwargs) -> bool:
    return await self._inner.get_lid_open(**backend_kwargs)

  async def get_lid_status(self, **backend_kwargs) -> LidStatus:
    return await self._inner.get_lid_status(**backend_kwargs)

  async def get_block_status(self, **backend_kwargs) -> BlockStatus:
    return await self._inner.get_block_status(**backend_kwargs)

  async def get_hold_time(self, **backend_kwargs) -> float:
    return await self._inner.get_hold_time(**backend_kwargs)

  async def get_current_cycle_index(self, **backend_kwargs) -> int:
    return await self._inner.get_current_cycle_index(**backend_kwargs)

  async def get_total_cycle_count(self, **backend_kwargs) -> int:
    return await self._inner.get_total_cycle_count(**backend_kwargs)

  async def get_current_step_index(self, **backend_kwargs) -> int:
    return await self._inner.get_current_step_index(**backend_kwargs)

  async def get_total_step_count(self, **backend_kwargs) -> int:
    return await self._inner.get_total_step_count(**backend_kwargs)

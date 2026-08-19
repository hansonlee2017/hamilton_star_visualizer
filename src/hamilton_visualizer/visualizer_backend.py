"""``LiquidHandlerBackend`` decorator that streams structured events to a
``VisualizerServer`` while forwarding every call unchanged to a wrapped
backend (a real Hamilton STAR backend, or a Chatterbox backend for
device-free development).

See ``docs/DESIGN.md`` section 2-3 for why this exists: PyLabRobot's own
Chatterbox backends only produce human-readable logs for a handful of gantry
jog calls -- ``pick_up_tips``/``aspirate``/``dispense``/``drop_tips`` end up
as raw, undocumented Hamilton firmware command strings with no reliable way
to recover which resource/channel/volume was involved. Wrapping the
``LiquidHandlerBackend`` interface instead -- the same pattern Chatterbox
itself uses -- gives us exact, structured events for free, and works
identically whether ``inner`` talks to real hardware or not.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from pylabrobot.liquid_handling.backends.backend import LiquidHandlerBackend
from pylabrobot.liquid_handling.standard import (
  Drop,
  DropTipRack,
  MultiHeadAspirationContainer,
  MultiHeadAspirationPlate,
  MultiHeadDispenseContainer,
  MultiHeadDispensePlate,
  Pickup,
  PickupTipRack,
  ResourceDrop,
  ResourceMove,
  ResourcePickup,
  SingleChannelAspiration,
  SingleChannelDispense,
)
from pylabrobot.resources import Deck, Tip, set_tip_tracking, set_volume_tracking
from pylabrobot.resources.tip_tracker import TipTracker

from hamilton_visualizer.events import channel_ops_event, resource_event
from hamilton_visualizer.scene import build_scene
from hamilton_visualizer.server import VisualizerServer


class VisualizerBackend(LiquidHandlerBackend):
  """Wraps ``inner`` and mirrors every call to ``server``.

  Tip-presence and liquid-volume visualization (Phase 2) relies on
  PyLabRobot's tip/volume trackers, which are **disabled by default**
  process-wide (``pylabrobot.resources.does_tip_tracking()`` /
  ``does_volume_tracking()`` both start ``False`` -- without them, resource
  state never changes and nothing is broadcast). ``enable_tracking=True``
  (the default) turns both on during ``setup()``. This is a global,
  process-wide setting and also makes PyLabRobot itself stricter (e.g. it
  will raise ``HasTipError``/``NoTipError`` on mismatched pick-ups); pass
  ``enable_tracking=False`` if that's not what you want and you're fine
  with tip/volume visualization staying inert.
  """

  def __init__(self, inner: LiquidHandlerBackend, server: VisualizerServer, *, enable_tracking: bool = True):
    super().__init__()
    self._inner = inner
    self._server = server
    self._enable_tracking = enable_tracking

  # -- passthrough properties -------------------------------------------
  @property
  def num_channels(self) -> int:
    return self._inner.num_channels

  @property
  def num_arms(self) -> int:
    return self._inner.num_arms

  @property
  def head96_installed(self) -> Optional[bool]:
    return self._inner.head96_installed

  # -- lifecycle ----------------------------------------------------------
  def set_deck(self, deck: Deck) -> None:
    super().set_deck(deck)
    self._inner.set_deck(deck)

  def set_heads(
    self, head: Dict[int, TipTracker], head96: Optional[Dict[int, TipTracker]] = None
  ) -> None:
    super().set_heads(head, head96)
    self._inner.set_heads(head, head96)

  async def setup(self) -> None:
    if self._enable_tracking:
      set_tip_tracking(True)
      set_volume_tracking(True)
    await super().setup()
    await self._inner.setup()
    self.setup_finished = True
    self._register_state_callbacks(self.deck)
    await self._server.set_scene(build_scene(self.deck), num_channels=self.num_channels)
    await self._broadcast_initial_state(self.deck)

  async def stop(self) -> None:
    await self._inner.stop()
    self.setup_finished = False

  def _register_state_callbacks(self, resource) -> None:
    """Recursively subscribe to tip-presence/liquid-volume changes so the
    frontend's static scene stays live (Phase 2)."""

    def make_callback(name: str):
      def _on_state_update(state: dict) -> None:
        self._server.schedule_broadcast({"type": "state", "resource": name, "state": state})

      return _on_state_update

    resource.register_state_update_callback(make_callback(resource.name))
    for child in resource.children:
      self._register_state_callbacks(child)

  async def _broadcast_initial_state(self, resource) -> None:
    """Send each resource's *current* state once at startup, not just future
    changes -- otherwise a tip rack that starts pre-filled with tips (the
    common case) renders as empty until its first pick-up touches each spot.
    This also means a replay starts from the correct initial state, since
    it's recorded in the server's event history like everything else.
    """

    await self._server.broadcast(
      {"type": "state", "resource": resource.name, "state": resource.serialize_state()}
    )
    for child in resource.children:
      await self._broadcast_initial_state(child)

  # -- pipetting ------------------------------------------------------------
  async def pick_up_tips(self, ops: List[Pickup], use_channels: List[int], **backend_kwargs) -> None:
    await self._inner.pick_up_tips(ops, use_channels, **backend_kwargs)
    await self._server.broadcast(channel_ops_event("pick_up_tips", ops, use_channels))

  async def drop_tips(self, ops: List[Drop], use_channels: List[int], **backend_kwargs) -> None:
    await self._inner.drop_tips(ops, use_channels, **backend_kwargs)
    await self._server.broadcast(channel_ops_event("drop_tips", ops, use_channels))

  async def aspirate(
    self, ops: List[SingleChannelAspiration], use_channels: List[int], **backend_kwargs
  ) -> None:
    await self._inner.aspirate(ops, use_channels, **backend_kwargs)
    await self._server.broadcast(channel_ops_event("aspirate", ops, use_channels, volume_attr="volume"))

  async def dispense(
    self, ops: List[SingleChannelDispense], use_channels: List[int], **backend_kwargs
  ) -> None:
    await self._inner.dispense(ops, use_channels, **backend_kwargs)
    await self._server.broadcast(channel_ops_event("dispense", ops, use_channels, volume_attr="volume"))

  # -- 96 head (forwarded for interface completeness; not animated in v1) --
  async def pick_up_tips96(self, pickup: PickupTipRack, **backend_kwargs) -> None:
    await self._inner.pick_up_tips96(pickup, **backend_kwargs)
    await self._server.broadcast(resource_event("pick_up_tips96", pickup.resource))

  async def drop_tips96(self, drop: DropTipRack, **backend_kwargs) -> None:
    await self._inner.drop_tips96(drop, **backend_kwargs)
    await self._server.broadcast(resource_event("drop_tips96", drop.resource))

  async def aspirate96(
    self, aspiration: Union[MultiHeadAspirationPlate, MultiHeadAspirationContainer]
  ) -> None:
    await self._inner.aspirate96(aspiration)
    resource = (
      aspiration.wells[0].parent
      if isinstance(aspiration, MultiHeadAspirationPlate)
      else aspiration.container
    )
    await self._server.broadcast(resource_event("aspirate96", resource, volume=aspiration.volume))

  async def dispense96(
    self, dispense: Union[MultiHeadDispensePlate, MultiHeadDispenseContainer]
  ) -> None:
    await self._inner.dispense96(dispense)
    resource = (
      dispense.wells[0].parent
      if isinstance(dispense, MultiHeadDispensePlate)
      else dispense.container
    )
    await self._server.broadcast(resource_event("dispense96", resource, volume=dispense.volume))

  # -- resource movement (moving plates is out of scope for v1 animation; --
  # -- forwarded and logged so the event log panel still shows it) --------
  async def pick_up_resource(self, pickup: ResourcePickup) -> None:
    await self._inner.pick_up_resource(pickup)
    await self._server.broadcast(resource_event("pick_up_resource", pickup.resource))

  async def move_picked_up_resource(self, move: ResourceMove) -> None:
    await self._inner.move_picked_up_resource(move)
    await self._server.broadcast(resource_event("move_picked_up_resource", move.resource))

  async def drop_resource(self, drop: ResourceDrop) -> None:
    await self._inner.drop_resource(drop)
    await self._server.broadcast(resource_event("drop_resource", drop.resource))

  # -- misc passthroughs ----------------------------------------------------
  async def request_tip_presence(self):
    return await self._inner.request_tip_presence()

  def can_pick_up_tip(self, channel_idx: int, tip: Tip) -> bool:
    return self._inner.can_pick_up_tip(channel_idx, tip)

  def get_channel_spacings(self, use_channels: List[int]) -> List[float]:
    return self._inner.get_channel_spacings(use_channels)

  async def prepare_for_manual_channel_operation(self, channel: int) -> None:
    await self._inner.prepare_for_manual_channel_operation(channel)

  async def move_channel_x(self, channel: int, x: float) -> None:
    await self._inner.move_channel_x(channel, x)
    await self._server.broadcast({"type": "op", "op": "move_channel", "channel": channel, "axis": "x", "value": x})

  async def move_channel_y(self, channel: int, y: float) -> None:
    await self._inner.move_channel_y(channel, y)
    await self._server.broadcast({"type": "op", "op": "move_channel", "channel": channel, "axis": "y", "value": y})

  async def move_channel_z(self, channel: int, z: float) -> None:
    await self._inner.move_channel_z(channel, z)
    await self._server.broadcast({"type": "op", "op": "move_channel", "channel": channel, "axis": "z", "value": z})

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

from typing import Any, Dict, List, Optional, Union

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
from pylabrobot.resources import Deck, Tip, TipRack, set_tip_tracking, set_volume_tracking
from pylabrobot.resources.tip_tracker import TipTracker

from hamilton_visualizer.events import channel_ops_event, resource_event
from hamilton_visualizer.scene import build_scene
from hamilton_visualizer.server import VisualizerServer


def _well_volume_entries(wells: List[Any]) -> List[Dict[str, Any]]:
  """Per-well ``{resource, resource_volume, resource_max_volume}`` entries
  for a 96-head aspirate96/dispense96 event -- field names deliberately
  match ``channel_ops_event()``'s own embedded per-channel shape (see
  events.py) so the frontend's existing ``applyEmbeddedResourceState()``
  can be reused verbatim per well, one call per entry, instead of a second
  parallel implementation of the same volume-tracker-reading logic.

  Same ``pending_volume`` reasoning as ``channel_ops_event()``: called
  after the inner backend call already succeeded, but ``LiquidHandler``
  queues each well's tracker change before calling the backend and only
  commits it (syncing ``volume`` from ``pending_volume``) afterwards --
  we're still inside that window here.
  """

  entries: List[Dict[str, Any]] = []
  for well in wells:
    entry: Dict[str, Any] = {"resource": well.name}
    tracker = getattr(well, "tracker", None)
    if tracker is not None and hasattr(tracker, "pending_volume"):
      entry["resource_volume"] = tracker.pending_volume
      entry["resource_max_volume"] = getattr(well, "max_volume", None)
    entries.append(entry)
  return entries


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

  async def wait_for_start(self) -> Dict[str, Any]:
    """Block until "Start Protocol" is clicked (``VisualizerServer.
    wait_for_start()``), then re-broadcast every resource's *current* state
    and return whatever params dict the click sent (``{}`` if none -- see
    ``VisualizerServer.wait_for_start()``'s docstring).

    Use this instead of calling ``self._server.wait_for_start()`` directly
    if your protocol does any manual state setup between ``lh.setup()`` and
    this call (e.g. pre-filling wells) -- ``_broadcast_initial_state()``
    already ran once, synchronously, inside ``setup()``, before that setup
    code had a chance to run, so it captured the *pre*-fill state. tip_spot/
    well changes aren't otherwise pushed live (see
    ``_LIVE_CALLBACK_EXCLUDED_CATEGORIES``), so without this, anything you
    changed during that window would stay invisible until an aspirate/
    dispense/pick_up_tips/drop_tips happened to touch it. Re-running it here
    -- exactly the point your protocol is telling the visualizer "initial
    setup is done" -- covers that gap.
    """

    params = await self._server.wait_for_start()
    await self.broadcast_state()
    return params

  async def broadcast_state(self) -> None:
    """Re-broadcast every resource's *current* state to all connected
    clients, same as the one-time push ``setup()`` already does.

    ``wait_for_start()`` calls this for you; call it directly instead if
    your protocol needs to skip straight from ``server.wait_for_start()``
    to doing param-dependent state setup (e.g. a run parameter entered in
    the HUD determines how many wells to pre-fill, so it can't happen
    before the browser's "Start Protocol" click carries it in -- see
    ``examples/picogreen_demo.py``). tip_spot/well/trough/tube changes
    aren't otherwise pushed live (see ``_LIVE_CALLBACK_EXCLUDED_
    CATEGORIES``), so without an explicit call here afterward, anything set
    up in that window would stay invisible until an aspirate/dispense/
    pick_up_tips/drop_tips happened to touch it.
    """

    await self._broadcast_initial_state(self.deck)

  # tip_spot/well/trough/tube changes driven by pick_up_tips/drop_tips/
  # aspirate/dispense are instead delivered by channel_ops_event() embedding
  # the resulting state directly in the "op" event -- see its docstring for
  # why: a live state callback fires the moment LiquidHandler queues the
  # tracker change, *before* it even calls this backend, so by the time it
  # reaches the frontend the color change has usually already been applied
  # ahead of the gantry animation that's supposed to cause it.
  # channel_ops_event()'s embedded-volume logic is category-agnostic (any
  # Container with a tracker), so this set is really "every category that
  # can be an aspirate/dispense target" -- trough and tube included, for a
  # reservoir and Eppendorf tubes. Skipping the live callback for just these
  # avoids that race; _broadcast_initial_state (a direct one-time push, not
  # a callback) still covers their starting color, and any other resource
  # category still gets live updates normally.
  _LIVE_CALLBACK_EXCLUDED_CATEGORIES = frozenset({"tip_spot", "well", "trough", "tube"})

  def _register_state_callbacks(self, resource) -> None:
    """Recursively subscribe to state changes so the frontend's static scene
    stays live (Phase 2) for everything not covered by embedded op-event
    data (see ``_LIVE_CALLBACK_EXCLUDED_CATEGORIES`` above)."""

    def make_callback(name: str):
      def _on_state_update(state: dict) -> None:
        self._server.schedule_broadcast({"type": "state", "resource": name, "state": state})

      return _on_state_update

    if resource.category not in self._LIVE_CALLBACK_EXCLUDED_CATEGORIES:
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

  def _sync_state_cache(self, event: Dict) -> None:
    """Fold a channel_ops_event()'s embedded resource_has_tip/resource_volume
    data back into the server's "latest known state" cache (without
    broadcasting it live -- see ``VisualizerServer.record_resource_state``'s
    docstring for why this is needed at all).
    """

    for entry in event.get("channels", []):
      if "resource_has_tip" in entry:
        state = {"tip": None if not entry["resource_has_tip"] else True}
      elif "resource_volume" in entry:
        state = {"volume": entry["resource_volume"], "max_volume": entry.get("resource_max_volume")}
      else:
        continue
      self._server.record_resource_state(entry["resource"], state)

  # -- pipetting ------------------------------------------------------------
  async def pick_up_tips(self, ops: List[Pickup], use_channels: List[int], **backend_kwargs) -> None:
    await self._inner.pick_up_tips(ops, use_channels, **backend_kwargs)
    event = channel_ops_event("pick_up_tips", ops, use_channels)
    self._sync_state_cache(event)
    await self._server.broadcast(event)

  async def drop_tips(self, ops: List[Drop], use_channels: List[int], **backend_kwargs) -> None:
    await self._inner.drop_tips(ops, use_channels, **backend_kwargs)
    event = channel_ops_event("drop_tips", ops, use_channels)
    self._sync_state_cache(event)
    await self._server.broadcast(event)

  async def aspirate(
    self, ops: List[SingleChannelAspiration], use_channels: List[int], **backend_kwargs
  ) -> None:
    await self._inner.aspirate(ops, use_channels, **backend_kwargs)
    # Real STARBackend.aspirate() kwargs (see channel_ops_event()'s
    # docstring) -- peeked at, not popped, so the full **backend_kwargs
    # (including these two) still reaches self._inner above unchanged, the
    # same as every other kwarg this method doesn't specifically care about.
    event = channel_ops_event(
      "aspirate",
      ops,
      use_channels,
      volume_attr="volume",
      traverse_height_mm=backend_kwargs.get("minimum_traverse_height_at_beginning_of_a_command"),
      end_height_mm=backend_kwargs.get("min_z_endpos"),
    )
    self._sync_state_cache(event)
    await self._server.broadcast(event)

  async def dispense(
    self, ops: List[SingleChannelDispense], use_channels: List[int], **backend_kwargs
  ) -> None:
    await self._inner.dispense(ops, use_channels, **backend_kwargs)
    event = channel_ops_event(
      "dispense",
      ops,
      use_channels,
      volume_attr="volume",
      traverse_height_mm=backend_kwargs.get("minimum_traverse_height_at_beginning_of_a_command"),
      end_height_mm=backend_kwargs.get("min_z_endpos"),
    )
    self._sync_state_cache(event)
    await self._server.broadcast(event)

  # -- 96 head (see frontend/gantry.js's Core96Head -- docs/PLAN.md's
  # "Review round 39") --
  async def pick_up_tips96(self, pickup: PickupTipRack, **backend_kwargs) -> None:
    await self._inner.pick_up_tips96(pickup, **backend_kwargs)
    event = resource_event("pick_up_tips96", pickup.resource, offset=pickup.offset)
    # No tracker read needed, same reasoning as channel_ops_event()'s own
    # resource_has_tip: a successful pick_up_tips96 always empties every
    # one of the rack's 96 spots (whether a given spot actually had a tip
    # or was already empty, it's empty either way afterward) -- if it
    # failed, we wouldn't have reached this line.
    event["tip_spots"] = [
      {"resource": spot.name, "resource_has_tip": False} for spot in pickup.resource.get_all_items()
    ]
    # A representative tip's real length/capacity, so Core96Head's own 96
    # tip cones can be sized/colored to match -- same fields
    # channel_ops_event() reports for a single-channel pick_up_tips (see
    # that function's own tip_length_mm/tip_max_volume_ul comment). Every
    # tip in one rack is normally the same model, so any present one
    # works as "the" tip, the same way a single-channel pickup only ever
    # has the one it actually grabbed. `None` if the rack was already
    # fully empty (shouldn't happen -- LiquidHandler.pick_up_tips96()
    # itself validates before this is ever reached -- but doesn't crash
    # either way if it somehow did).
    representative_tip = next((tip for tip in pickup.tips if tip is not None), None)
    if representative_tip is not None:
      event["tip_length_mm"] = representative_tip.total_tip_length
      event["tip_max_volume_ul"] = representative_tip.nominal_volume
    await self._server.broadcast(event)

  async def drop_tips96(self, drop: DropTipRack, **backend_kwargs) -> None:
    await self._inner.drop_tips96(drop, **backend_kwargs)
    event = resource_event("drop_tips96", drop.resource, offset=drop.offset)
    # Only meaningful when dropping back onto a TipRack (a Trash has no
    # individual spots to visually refill) -- same "successful op has a
    # deterministic end state" reasoning as pick_up_tips96 above.
    if isinstance(drop.resource, TipRack):
      event["tip_spots"] = [
        {"resource": spot.name, "resource_has_tip": True} for spot in drop.resource.get_all_items()
      ]
    await self._server.broadcast(event)

  async def aspirate96(
    self, aspiration: Union[MultiHeadAspirationPlate, MultiHeadAspirationContainer]
  ) -> None:
    await self._inner.aspirate96(aspiration)
    resource = (
      aspiration.wells[0].parent
      if isinstance(aspiration, MultiHeadAspirationPlate)
      else aspiration.container
    )
    event = resource_event("aspirate96", resource, offset=aspiration.offset, volume=aspiration.volume)
    if isinstance(aspiration, MultiHeadAspirationPlate):
      event["wells"] = _well_volume_entries(aspiration.wells)
    await self._server.broadcast(event)

  async def dispense96(
    self, dispense: Union[MultiHeadDispensePlate, MultiHeadDispenseContainer]
  ) -> None:
    await self._inner.dispense96(dispense)
    resource = (
      dispense.wells[0].parent
      if isinstance(dispense, MultiHeadDispensePlate)
      else dispense.container
    )
    event = resource_event("dispense96", resource, offset=dispense.offset, volume=dispense.volume)
    if isinstance(dispense, MultiHeadDispensePlate):
      event["wells"] = _well_volume_entries(dispense.wells)
    await self._server.broadcast(event)

  # -- resource movement (moving plates is out of scope for v1 animation; --
  # -- forwarded and logged so the event log panel still shows it) --------
  async def pick_up_resource(self, pickup: ResourcePickup) -> None:
    await self._inner.pick_up_resource(pickup)
    await self._server.broadcast(resource_event("pick_up_resource", pickup.resource, offset=pickup.offset))

  async def move_picked_up_resource(self, move: ResourceMove) -> None:
    await self._inner.move_picked_up_resource(move)
    await self._server.broadcast(resource_event("move_picked_up_resource", move.resource, offset=move.offset))

  async def drop_resource(self, drop: ResourceDrop) -> None:
    await self._inner.drop_resource(drop)
    await self._server.broadcast(resource_event("drop_resource", drop.resource, offset=drop.offset))

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

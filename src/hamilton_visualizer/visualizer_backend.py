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

from typing import Any, Dict, List, Optional, Tuple, Union

from pylabrobot.liquid_handling.backends.backend import LiquidHandlerBackend
from pylabrobot.liquid_handling.backends.chatterbox import LiquidHandlerChatterboxBackend
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

from hamilton_visualizer.events import channel_ops_event, resource_drop_point, resource_event, resource_move_point
from hamilton_visualizer.scene import build_scene
from hamilton_visualizer.server import VisualizerServer


def _patch_chatterbox_resource_kwargs() -> None:
  """Monkey-patch ``LiquidHandlerChatterboxBackend.pick_up_resource``/
  ``move_picked_up_resource``/``drop_resource`` to accept (and print)
  arbitrary ``**backend_kwargs``, matching every *other* chatterbox
  method's own signature.

  Confirmed by reading ``chatterbox.py``: ``pick_up_tips``/``drop_tips``/
  ``pick_up_tips96``/``drop_tips96``/``aspirate``/``dispense`` all accept
  ``**backend_kwargs`` (aspirate/dispense even print a couple of them),
  but these three resource-movement methods take *only* their one
  positional dataclass argument -- a real gap in chatterbox.py, not a
  deliberate difference, since a real hardware backend (see
  ``STARBackend.pick_up_resource``/``drop_resource``) very much accepts
  extra kwargs here (``use_arm``, ``core_front_channel``, etc.). Without
  this patch, ``VisualizerBackend`` blind-forwarding ``use_arm="core"``
  etc. to ``self._inner.X(dataclass, **backend_kwargs)`` -- the same
  established pattern ``pick_up_tips``/``aspirate``/``dispense`` already
  use below -- would crash every demo in this project the moment a
  CoRe-gripper call is made (they all run on a chatterbox backend).

  Applied once, to the class itself, at import time -- every
  ``LiquidHandlerChatterboxBackend`` instance is affected, not just ones
  wrapped by a ``VisualizerBackend``, matching this being a genuine
  upstream gap rather than something specific to this project.
  """

  if getattr(LiquidHandlerChatterboxBackend, "_hamilton_visualizer_resource_kwargs_patched", False):
    return  # idempotent -- guards against this module being imported more than once

  for method_name in ("pick_up_resource", "move_picked_up_resource", "drop_resource"):
    original = getattr(LiquidHandlerChatterboxBackend, method_name)

    def make_patched(original=original):
      async def patched(self, arg, **backend_kwargs):
        result = await original(self, arg)
        if backend_kwargs:
          print(f"  ({', '.join(f'{k}={v!r}' for k, v in backend_kwargs.items())})")
        return result

      return patched

    setattr(LiquidHandlerChatterboxBackend, method_name, make_patched())

  LiquidHandlerChatterboxBackend._hamilton_visualizer_resource_kwargs_patched = True


_patch_chatterbox_resource_kwargs()


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
    # (back_channel, front_channel) currently holding the CoRe gripper
    # pads, or None if they're parked at core_grippers -- our own copy of
    # what STARBackend tracks internally as `core_parked` (see
    # STAR_backend.py's pick_up_core_gripper_tools()/
    # return_core_gripper_tools()), needed regardless of what `inner`
    # actually is (a chatterbox backend doesn't track this at all, and we
    # need to know it either way to decide whether a pickup needs its own
    # "channels attach to the pads first" animation -- see
    # core_pick_up_resource()'s own comment). Per user direction: persists
    # across moves, matching real hardware, rather than re-attaching on
    # every single core-arm pickup regardless.
    self._core_gripper_channels: Optional[Tuple[int, int]] = None

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

  # -- resource movement ----------------------------------------------------
  # Two arms can move a resource in real PyLabRobot: the iSWAP (the
  # default -- a separate, unmodeled-in-this-project mechanism) and the
  # CoRe gripper (``use_arm="core"``, explicit opt-in per user direction --
  # two of the 8 pipetting channels grab a pair of gripper pads parked at
  # the deck's own ``core_grippers`` resource -- see hamilton_decks.py's
  # ``hamilton_core_gripper_1000uL_5mL_on_waste()``, every ``STARDeck``/
  # ``STARLetDeck``'s default -- and use them to clamp and carry a plate).
  # Only ``use_arm="core"`` calls get the new attach-pads/carry-plate
  # animation (``core_pick_up_resource``/``core_move_picked_up_resource``/
  # ``core_drop_resource`` events below); everything else (the default, or
  # an explicit ``use_arm="iswap"``) keeps the original plain
  # ``resource_event()`` broadcast -- log-only/unanimated, same as before
  # this feature existed.
  #
  # ``use_arm``/``core_front_channel``/``channel_1``/``channel_2``/
  # ``return_core_gripper`` are peeked out of ``backend_kwargs`` (not
  # popped), mirroring aspirate()/dispense()'s own
  # ``traverse_height_mm``/``end_height_mm`` handling just above -- the
  # full dict still gets forwarded to ``self._inner`` unchanged, matching
  # every other op in this class. This only works against a chatterbox
  # inner because of ``_patch_chatterbox_resource_kwargs()`` above -- see
  # its own docstring; a real ``STARBackend`` already accepts every one of
  # these natively.
  async def pick_up_resource(self, pickup: ResourcePickup, **backend_kwargs) -> None:
    await self._inner.pick_up_resource(pickup, **backend_kwargs)

    use_arm = backend_kwargs.get("use_arm", "iswap")
    if use_arm != "core":
      await self._server.broadcast(resource_event("pick_up_resource", pickup.resource, offset=pickup.offset))
      return

    # Same resolution STARBackend.pick_up_resource() itself does for its
    # deprecated channel_1/channel_2 pair (both must be given together;
    # channel_2 must be channel_1 + 1; front_channel = channel_2 - 1, i.e.
    # channel_1) -- see STAR_backend.py's own pick_up_resource().
    channel_1 = backend_kwargs.get("channel_1")
    channel_2 = backend_kwargs.get("channel_2")
    front_channel = backend_kwargs.get("core_front_channel", 7)
    if channel_1 is not None or channel_2 is not None:
      assert channel_1 is not None and channel_2 is not None, "Both channel_1 and channel_2 must be provided"
      assert channel_1 + 1 == channel_2, "channel_2 must be channel_1 + 1"
      front_channel = channel_2 - 1
    back_channel = front_channel - 1

    # Mirrors STARBackend's own core_parked/pick_up_core_gripper_tools()
    # gating (see core_pick_up_resource(): "if self.core_parked: await
    # self.pick_up_core_gripper_tools(front_channel=front_channel)") --
    # pads only need a fresh "channels attach to the pads" animation when
    # they aren't already attached to this exact channel pair. Persists
    # across moves rather than re-attaching on every pickup, per user
    # direction: matches real hardware, where the pads stay clamped onto
    # the channels between moves unless explicitly returned (see
    # drop_resource() below).
    needs_attach = (back_channel, front_channel) != self._core_gripper_channels
    self._core_gripper_channels = (back_channel, front_channel)

    await self._server.broadcast(
      resource_event(
        "core_pick_up_resource",
        pickup.resource,
        offset=pickup.offset,
        back_channel=back_channel,
        front_channel=front_channel,
        needs_attach=needs_attach,
      )
    )

  async def move_picked_up_resource(self, move: ResourceMove, **backend_kwargs) -> None:
    await self._inner.move_picked_up_resource(move, **backend_kwargs)

    use_arm = backend_kwargs.get("use_arm", "iswap")
    op_name = "core_move_picked_up_resource" if use_arm == "core" else "move_picked_up_resource"
    # Uses resource_move_point(), not resource_event()'s usual
    # resource_point() -- same staleness reasoning as drop_resource()'s own
    # resource_drop_point() below: a resource being carried through an
    # intermediate waypoint is never reparented mid-carry (only the final
    # drop_resource() does that), so it's still parented at its *original*
    # pre-pickup location for the whole carry.
    event = {
      "type": "op",
      "op": op_name,
      "resource": move.resource.name,
      **resource_move_point(move),
    }
    # self._core_gripper_channels should always be set by this point for a
    # real protocol (move_picked_up_resource only ever follows a
    # pick_up_resource for the same resource), but a None guard costs
    # nothing and avoids a crash if this is ever called out of that order.
    if use_arm == "core" and self._core_gripper_channels is not None:
      event["back_channel"], event["front_channel"] = self._core_gripper_channels
    await self._server.broadcast(event)

  async def drop_resource(self, drop: ResourceDrop, **backend_kwargs) -> None:
    await self._inner.drop_resource(drop, **backend_kwargs)

    use_arm = backend_kwargs.get("use_arm", "iswap")
    if use_arm != "core":
      await self._server.broadcast(resource_event("drop_resource", drop.resource, offset=drop.offset))
      return

    return_core_gripper = backend_kwargs.get("return_core_gripper", True)
    back_channel, front_channel = self._core_gripper_channels or (None, None)
    if return_core_gripper:
      # Mirrors STARBackend's own core_release_picked_up_resource(...,
      # return_tool=return_core_gripper)/return_core_gripper_tools() --
      # pads go back to core_grippers and need a fresh attach next pickup.
      self._core_gripper_channels = None

    # Uses resource_drop_point(), not resource_event()'s usual
    # resource_point() -- see that function's own docstring for why a live
    # location lookup on drop.resource would be wrong here (it's still
    # parented at its *old* location at this point in the call).
    await self._server.broadcast(
      {
        "type": "op",
        "op": "core_drop_resource",
        "resource": drop.resource.name,
        **resource_drop_point(drop),
        "back_channel": back_channel,
        "front_channel": front_channel,
        "return_core_gripper": return_core_gripper,
      }
    )

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

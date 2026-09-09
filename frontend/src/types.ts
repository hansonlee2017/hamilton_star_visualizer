// Shared shapes for the data streamed from VisualizerServer -- the scene
// graph (scene.py), the "op" events (events.py), and the HUD run-params
// (server.py's set_run_params()). These are deliberately loose where the
// Python side is loose: most fields are optional because a given message
// only carries the ones relevant to its own `op`/`type`.

// PyLabRobot coordinate (mm): x right, y "back", z up -- see coordinates.ts.
export interface Coord {
  x: number;
  y: number;
  z: number;
}

// ---------------------------------------------------------------------------
// Scene graph (scene.py -> Resource.serialize() plus a few injected fields)
// ---------------------------------------------------------------------------
export interface SceneNode {
  name: string;
  type?: string;
  category?: string;
  model?: string | null;
  location?: Partial<Coord> | null;
  rotation?: { x?: number; y?: number; z?: number } | null;
  size_x?: number;
  size_y?: number;
  size_z?: number;
  max_volume?: number | null;
  // Deck-only
  num_rails?: number | null;
  // Carrier ResourceHolder slot height when nothing is parked there yet
  child_location?: Partial<Coord> | null;
  // Well shape (Resource.serialize())
  bottom_type?: "flat" | "U" | "V" | "unknown" | string;
  cross_section_type?: "circle" | "rectangle" | string;
  // Tip-rack-only (scene.py adds these)
  tip_length_mm?: number | null;
  tip_max_volume_ul?: number | null;
  children?: SceneNode[];
}

// ---------------------------------------------------------------------------
// HUD run-params (server.py set_run_params(); rendered by dom.ts)
// ---------------------------------------------------------------------------
export interface NumberField {
  type: "number";
  id: string;
  label?: string;
  title?: string;
  min?: number;
  max?: number;
  step?: number;
  default?: number;
  suffix?: string;
}
export interface TextField {
  type: "text";
  id: string;
  label?: string;
  title?: string;
  length?: number;
  default?: string;
}
export interface ComputedField {
  type: "computed";
  basis?: string;
  of?: string;
  total?: number;
  title?: string;
}
export type RunParamField = NumberField | TextField | ComputedField;

// ---------------------------------------------------------------------------
// "op" events (events.py). One broad shape -- a given op only sets the
// fields it needs; handleOpEvent() switches on `op` and reads accordingly.
// ---------------------------------------------------------------------------

// One channel's slice of a multi-channel pick_up_tips/drop_tips/aspirate/
// dispense op (msg.channels[]).
export interface ChannelEntry {
  channel: number;
  resource: string;
  x: number;
  y: number;
  z: number;
  volume?: number;
  tip_length_mm?: number | null;
  tip_max_volume_ul?: number | null;
  mix_repetitions?: number | null;
  // Embedded resulting resource state, applied on gantry arrival
  resource_has_tip?: boolean;
  resource_volume?: number | null;
  resource_max_volume?: number | null;
}

// A per-well / per-tip-spot slice of a 96-head op (msg.wells[] / msg.tip_spots[]).
export interface ResourceStateEntry {
  resource: string;
  resource_has_tip?: boolean;
  resource_volume?: number | null;
  resource_max_volume?: number | null;
}

export interface OpEvent {
  op: string;
  resource?: string;
  // Multi-channel ops
  channels?: ChannelEntry[];
  traverse_height_mm?: number | null;
  end_height_mm?: number | null;
  // 96-head ops
  x?: number;
  y?: number;
  z?: number;
  volume?: number;
  tip_length_mm?: number | null;
  tip_max_volume_ul?: number | null;
  mix_repetitions?: number | null;
  wells?: ResourceStateEntry[];
  tip_spots?: ResourceStateEntry[];
  // Thermocycler
  protocol_summary?: string | null;
  // CoRe gripper
  back_channel?: number;
  front_channel?: number;
  needs_attach?: boolean;
  return_core_gripper?: boolean;
  pad_x?: number | null;
  pad_y?: number | null;
  pad_z?: number | null;
  // resource_reparented
  parent?: string | null;
  // incubate
  resources?: string[];
  duration_s?: number | null;
}

// ---------------------------------------------------------------------------
// WebSocket messages (server.py broadcasts)
// ---------------------------------------------------------------------------
export interface SceneMessage {
  type: "scene";
  deck: SceneNode;
  num_channels?: number | null;
}
export interface RunParamsMessage {
  type: "run_params";
  fields: RunParamField[];
}
export interface StateMessage {
  type: "state";
  resource: string;
  state: {
    tip?: unknown;
    volume?: number | null;
    max_volume?: number | null;
    protocol_summary?: string | null;
  };
}
export interface StartStatusMessage {
  type: "start_status";
  started: boolean;
}
export interface RunStatusMessage {
  type: "run_status";
  finished: boolean;
}
export interface ResetMessage {
  type: "reset";
}
export type OpMessage = OpEvent & { type: "op" };
export type ServerMessage =
  | SceneMessage
  | RunParamsMessage
  | StateMessage
  | StartStatusMessage
  | RunStatusMessage
  | ResetMessage
  | OpMessage;

// Outbound (browser -> server) actions.
export interface ClientAction {
  action: "replay" | "start_protocol" | "reset";
  params?: Record<string, number | string>;
}

export interface WsHandlers {
  onOpen?: () => void;
  onClose?: () => void;
  onScene?: (msg: SceneMessage) => void;
  onRunParams?: (fields: RunParamField[]) => void;
  onState?: (msg: StateMessage) => void;
  onOp?: (msg: OpEvent) => void;
  onStartStatus?: (started: boolean) => void;
  onRunStatus?: (finished: boolean) => void;
  onReset?: () => void;
}

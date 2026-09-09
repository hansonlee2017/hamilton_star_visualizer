// WebSocket connection to VisualizerServer. Deliberately DOM-agnostic (no
// imports from dom.ts/scene-builder.ts/etc.) -- callers (main.ts) pass in a
// `handlers` object and this module just dispatches parsed messages to it,
// so this stays a clean leaf module and dom.ts can import send() from here
// (for the Start/Reset/Replay buttons) without any risk of a cycle.

import type { ClientAction, OpMessage, ServerMessage, WsHandlers } from "./types";

let currentWs: WebSocket | null = null;

// handlers: { onOpen, onClose, onScene(msg), onRunParams(fields),
// onState(msg), onOp(msg), onStartStatus(started), onRunStatus(finished),
// onReset() } -- every key optional.
export function connect(handlers: WsHandlers): void {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
  currentWs = ws;

  ws.onopen = () => {
    if (ws !== currentWs) return; // stale socket superseded by a newer connect()
    handlers.onOpen?.();
  };
  ws.onclose = () => {
    if (ws !== currentWs) return; // ditto -- don't let an old socket's close
    // clobber state a newer, already-open connection just set
    handlers.onClose?.();
    setTimeout(() => connect(handlers), 1500);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = (event: MessageEvent<string>) => {
    let msg: ServerMessage;
    try {
      msg = JSON.parse(event.data) as ServerMessage;
    } catch {
      return; // a frame that isn't JSON at all -- ignore it, keep the socket
    }
    switch (msg.type) {
      case "scene":
        handlers.onScene?.(msg);
        break;
      case "run_params":
        handlers.onRunParams?.(msg.fields);
        break;
      case "state":
        handlers.onState?.(msg);
        break;
      case "op":
        handlers.onOp?.(msg as OpMessage);
        break;
      case "start_status":
        handlers.onStartStatus?.(msg.started);
        break;
      case "run_status":
        handlers.onRunStatus?.(msg.finished);
        break;
      case "reset":
        handlers.onReset?.();
        break;
      default:
        break;
    }
  };
}

// Used by dom.ts's Start/Reset/Replay button handlers. A silent no-op if
// there's no open connection -- every caller already only wires up its
// click listener with this same guard in mind (matches the original
// inline `if (!currentWs || currentWs.readyState !== WebSocket.OPEN)
// return;` checks each handler used to do for itself).
export function send(obj: ClientAction): void {
  if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return;
  currentWs.send(JSON.stringify(obj));
}

export function isOpen(): boolean {
  return !!currentWs && currentWs.readyState === WebSocket.OPEN;
}

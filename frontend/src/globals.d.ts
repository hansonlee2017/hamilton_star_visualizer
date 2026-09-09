// Debug hooks main.ts hangs off `window` for browser-console / automated
// inspection -- see main.ts's own `window.__viz` / `window.__log` comments,
// and log.ts for `__log`. Typed loosely on purpose: these are a debugging
// surface, not an API.
import type { LEVELS } from "./log";

declare global {
  interface Window {
    __viz?: Record<string, unknown>;
    __log?: {
      setLevel: (nameOrValue: string | number) => void;
      getLevel: () => number;
      LEVELS: typeof LEVELS;
    };
    __lastStateMessages?: unknown[];
  }
}

export {};

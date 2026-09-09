// Optional, leveled debug logging -- Python's `logging` module's own
// DEBUG/INFO/WARNING/ERROR levels, ported to this project's console.
// Silent by default (this is a debugging aid, not something every user's
// console should be spammed with on an ordinary run) -- turn it on with
// `window.__log.setLevel("debug")` in devtools, or once at page load with
// a `?logLevel=debug` URL query param (handy for a scripted/automated
// session that can't easily type into devtools -- see main.ts's own
// wiring of both).
//
// Exists specifically so a future debugging session (human or Claude) can
// capture *why* an animation looked wrong from a plain timestamped trace
// instead of by watching playback or comparing screenshots -- see
// docs/PLAN.md's "Review round 46"-"48" for the class of bug (a queue
// silently stacking redundant waits, waiting on the wrong condition,
// snapping to the wrong position) a trace of "what got attached/waited
// on/enqueued, and when" would have surfaced immediately, instead of
// needing a whole separate deterministic replay harness built from
// scratch each time. Once `window.__log.setLevel("debug")` is set, this
// project's own `mcp__Claude_Browser__read_console_messages` tool can
// pull the resulting trace straight out of the page with no screenshot
// or live-watching involved at all.

export const LEVELS = { DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40, OFF: 100 } as const;
export type LevelName = keyof typeof LEVELS;

let level: number = LEVELS.OFF;

// Accepts either a level name ("debug", case-insensitive) or one of the
// numeric LEVELS values directly -- the string form is what a `?logLevel=`
// query param or a quick devtools call actually types out.
export function setLevel(nameOrValue: string | number): void {
  const resolved =
    typeof nameOrValue === "string"
      ? (LEVELS as Record<string, number>)[nameOrValue.toUpperCase()]
      : nameOrValue;
  if (typeof resolved !== "number") {
    console.warn(
      `log.setLevel(): unknown level ${JSON.stringify(nameOrValue)} -- use one of ${Object.keys(
        LEVELS
      ).join(", ")}`
    );
    return;
  }
  level = resolved;
}

export function getLevel(): number {
  return level;
}

// `scope`: a short, fixed string identifying which module/subsystem a
// message came from (e.g. "gantry", "thermocycler") -- lets a reader (or
// a grep over a captured console log) filter a busy trace down to just
// the part they care about, the same role a Python logger's own
// `__name__` plays.
type ConsoleFn = (...args: unknown[]) => void;
function emit(consoleFn: ConsoleFn, levelValue: number, scope: string, args: unknown[]): void {
  if (levelValue < level) return;
  // performance.now() (ms since page load), not wall-clock time -- this
  // project's own deterministic Node replay tests key off the same
  // "simulated ms since the run started" convention (see
  // test/*.test.ts's own tick() helpers), so a browser trace
  // and a replay test's own console output read the same way side by
  // side.
  consoleFn(`[${performance.now().toFixed(1)}ms] [${scope}]`, ...args);
}

export interface Logger {
  debug: (...args: unknown[]) => void;
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
}

// One of these per calling module (see gantry.ts/thermocycler.ts's own
// `const log = makeLogger("gantry")`), rather than a single shared
// logger every call site has to pass its own scope string into by hand.
export function makeLogger(scope: string): Logger {
  return {
    debug: (...args: unknown[]) => emit(console.debug, LEVELS.DEBUG, scope, args),
    info: (...args: unknown[]) => emit(console.info, LEVELS.INFO, scope, args),
    warn: (...args: unknown[]) => emit(console.warn, LEVELS.WARN, scope, args),
    error: (...args: unknown[]) => emit(console.error, LEVELS.ERROR, scope, args),
  };
}

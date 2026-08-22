// Unit tests for frontend/log.js's leveled debug logging. Run with:
//
//     node --test tests/frontend/

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { LEVELS, setLevel, getLevel, makeLogger } from "../../frontend/log.js";

describe("log", () => {
  // console.debug/info/warn/error are stubbed per test and restored
  // afterward, so these tests can run in any order/in parallel with
  // other test files without fighting over the real console.
  let calls;
  let originals;
  beforeEach(() => {
    calls = [];
    originals = { debug: console.debug, info: console.info, warn: console.warn, error: console.error };
    for (const name of ["debug", "info", "warn", "error"]) {
      console[name] = (...args) => calls.push({ level: name, args });
    }
    setLevel(LEVELS.OFF); // reset between tests -- setLevel() is module-level state
  });
  afterEach(() => {
    Object.assign(console, originals);
  });

  test("silent by default (OFF)", () => {
    assert.equal(getLevel(), LEVELS.OFF);
    const log = makeLogger("test");
    log.debug("hello");
    log.info("hello");
    log.warn("hello");
    log.error("hello");
    assert.deepEqual(calls, []);
  });

  test("setLevel(\"debug\") (a string, case-insensitive) lets everything through", () => {
    setLevel("DeBuG");
    const log = makeLogger("test");
    log.debug("a");
    log.info("b");
    log.warn("c");
    log.error("d");
    assert.equal(calls.length, 4);
  });

  test("a numeric threshold only lets levels at or above it through", () => {
    setLevel(LEVELS.WARN);
    const log = makeLogger("test");
    log.debug("nope");
    log.info("nope");
    log.warn("yes");
    log.error("yes");
    assert.equal(calls.length, 2);
    assert.deepEqual(calls.map((c) => c.level), ["warn", "error"]);
  });

  test("an unrecognized level name warns and leaves the threshold unchanged", () => {
    setLevel(LEVELS.INFO);
    setLevel("nonsense");
    assert.equal(getLevel(), LEVELS.INFO, "threshold untouched by the bad call");
    // The warning itself goes through console.warn -- expected, not a bug.
    assert.equal(calls.length, 1);
    assert.equal(calls[0].level, "warn");
  });

  test("each call is prefixed with a single combined timestamp+scope string, args passed through unchanged", () => {
    setLevel(LEVELS.DEBUG);
    const log = makeLogger("my-scope");
    log.info("count:", 3, { ok: true });
    assert.equal(calls.length, 1);
    const [prefix, ...rest] = calls[0].args;
    assert.match(prefix, /^\[\d+(\.\d+)?ms\] \[my-scope\]$/);
    assert.deepEqual(rest, ["count:", 3, { ok: true }]);
  });

  test("two loggers from makeLogger() carry independent scopes but share the one module-level threshold", () => {
    setLevel(LEVELS.ERROR);
    const a = makeLogger("a");
    const b = makeLogger("b");
    a.warn("dropped");
    b.error("kept");
    assert.equal(calls.length, 1);
    assert.match(calls[0].args[0], /\[b\]$/);
    assert.equal(calls[0].args[1], "kept");
  });
});

# Frontend unit tests

Zero-dependency tests for `src/hamilton_visualizer/frontend/`'s pure logic
(no browser, no THREE.js rendering, no DOM) via Node's built-in test runner
-- no npm install, no build step, matching this repo's existing "no build
step" convention (see
`src/hamilton_visualizer/frontend/node_modules/three/package.json` for how
the one module that *does* import `three` resolves that bare specifier under
plain Node without an actual npm dependency).

Run with:

```
node --test ./tests/frontend/*.test.js
```

(Node's own `--test <directory>` auto-discovery didn't reliably pick up
this directory on Windows in testing -- an explicit glob for the *.test.js
files does.)

What's covered, and why these specifically: `gantry-planning.js`'s
`resolveChannelYs()`/`planGantryPasses()` are the least-obvious logic in the
whole frontend (a change-of-variable feasibility solver, plus the per-x
gantry-stop grouping built on top of it -- see that file's own docstrings),
and have been the source of real, previously-live-debugged desync bugs
(docs/PLAN.md's "Review round 34", "Review round 15") -- exactly the kind
of regression a unit test catches before a demo does. `categories.js`'s
`tipColorForVolume()` and `resource-state.js`'s `volumeVisual()`/
`tipVisual()` are simpler but still real threshold/interpolation logic
worth pinning down. Everything else in the frontend is THREE.js rendering or
DOM/websocket plumbing, not meaningfully unit-testable without a browser --
that's covered by hand (see docs/PLAN.md's various "verified live" write-ups)
instead.

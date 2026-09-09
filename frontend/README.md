# Frontend

The Hamilton Visualizer browser UI: a [Vite](https://vite.dev/) +
[TypeScript](https://www.typescriptlang.org/) + [Three.js](https://threejs.org/)
single-page app.

This directory is **development-only**. It is not part of the Python
distribution. The production build is committed to
`../src/hamilton_visualizer/frontend/` (`index.html` + content-hashed
`assets/`), and that is what the `hamilton_visualizer` package ships and
what `server.py` serves -- so installing and running the visualizer never
needs Node.

## Layout

```
src/               the app, one module per concern
  main.ts          thin orchestrator: viewport/camera, websocket wiring, render loop
  types.ts         shapes of the data streamed from VisualizerServer (scene, ops, run-params)
  coordinates.ts   PyLabRobot <-> Three.js coordinate mapping
  categories.ts    category/tip color palette + legend data
  duration-scale.ts the HUD's playback-speed multiplier
  log.ts           optional leveled debug logging (off by default)
  animation-queue.ts / motion-unit.ts  the generic per-owner tween queue mechanics
  gantry-planning.ts  pure multi-channel motion-planning math (unit-tested)
  gantry.ts        the 8-channel arm, the CO-RE 96 head, the CoRe gripper, op dispatch
  scene-builder.ts scene graph -> Three.js object tree
  resource-state.ts  live tip/volume/protocol-summary updates
  thermocycler.ts / incubate.ts  resource-timeline animations
  dom.ts           DOM handles, event log, HUD controls
  websocket.ts     the websocket connection
  tooltip.ts       hover tooltips
test/              Vitest unit tests for the pure-logic modules (no browser/DOM)
```

## Commands

```bash
npm install            # once

npm run dev            # Vite dev server on :5173 with HMR; proxies /ws -> :8765
npm run build          # tsc --noEmit + vite build -> ../src/hamilton_visualizer/frontend/
npm run typecheck      # tsc --noEmit only
npm test               # vitest run
```

### Dev loop

`npm run dev` serves the UI but has no data of its own. Run a protocol in
another terminal to provide the websocket stream:

```bash
uv run python examples/demo_protocol.py   # from the repo root -- server on :8765
```

Vite's dev server proxies `/ws` to `127.0.0.1:8765`, so the app running at
`http://localhost:5173/static/` connects to that protocol and hot-reloads
on every edit to `src/*.ts`.

## After changing anything under `src/`

Run `npm run build` and commit the regenerated
`../src/hamilton_visualizer/frontend/` -- CI and `pip install` do not run
Vite, so a stale committed build ships a stale UI.

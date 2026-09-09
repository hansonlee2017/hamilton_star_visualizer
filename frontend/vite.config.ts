/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";

// The Python package (src/hamilton_visualizer/server.py) serves the built
// frontend as static files: index.html at "/", hashed assets under
// "/static/". `base` matches that so the built index.html references
// "/static/assets/*". In dev, Vite serves the same tree under "/static/"
// and proxies the websocket through to a running protocol script's
// VisualizerServer on :8765 -- so `npm run dev` gives you HMR while an
// `examples/*.py` demo (or your own protocol) provides the live data.
export default defineConfig({
  base: "/static/",
  build: {
    // Committed to git so `uv build` / `pip install` needs no Node -- see
    // this directory's README.md and pyproject.toml's build config.
    outDir: "../src/hamilton_visualizer/frontend",
    emptyOutDir: true,
    target: "es2022",
    // No sourcemap in the committed/shipped build -- it's ~3MB of mostly
    // minified Three.js and the debugging path is `npm run dev` (full HMR,
    // real sourcemaps) against a running protocol, not the packaged bundle.
    sourcemap: false,
    // The one chunk is the app plus Three.js (~575kB). Code-splitting a
    // single-page visualizer with no routes buys nothing; raise the limit
    // so a clean build has no spurious warning.
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    proxy: {
      "/ws": {
        target: "http://127.0.0.1:8765",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  test: {
    // Pure-logic modules only -- no browser, no DOM. jsdom isn't needed
    // (and the modules under test never touch `document` at import time).
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});

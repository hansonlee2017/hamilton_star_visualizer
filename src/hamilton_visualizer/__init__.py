"""Browser-based isometric visualizer for PyLabRobot / Hamilton STAR runs.

Typical usage in your own protocol script::

    from hamilton_visualizer import VisualizerBackend, VisualizerServer

    server = VisualizerServer()
    await server.start()  # prints the URL to open in a browser

    real_backend = STARBackend()  # or STARChatterboxBackend() for testing
    lh = LiquidHandler(backend=VisualizerBackend(real_backend, server), deck=deck)
    await lh.setup()
    ... run your protocol as normal ...

See ``docs/DESIGN.md`` and ``examples/demo_protocol.py``.
"""

from hamilton_visualizer.server import VisualizerServer
from hamilton_visualizer.thermocycler_backend import VisualizerThermocyclerBackend
from hamilton_visualizer.visualizer_backend import VisualizerBackend, attach_sleep

__all__ = ["VisualizerServer", "VisualizerBackend", "VisualizerThermocyclerBackend", "attach_sleep"]


def main() -> None:
  """Entry point for the `hamilton-visualizer` console script -- this package
  is a library you import into your own protocol, not a standalone app, so
  this just points you at how to use it."""

  print(
    "hamilton-visualizer is a library you import into your own PyLabRobot\n"
    "protocol script:\n\n"
    "    from hamilton_visualizer import VisualizerBackend, VisualizerServer\n\n"
    "See the README for the full wiring, and the runnable, hardware-free\n"
    "demos under examples/ in the source repo (clone it, then run e.g.\n"
    "`uv run python examples/demo_protocol.py`).\n"
  )

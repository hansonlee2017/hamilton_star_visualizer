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
  """Entry point for `uv run hamilton-visualizer` -- this package is a
  library, not a standalone app, so this just points you at the demo."""

  print(
    "hamilton-visualizer is a library you import into your own PyLabRobot\n"
    "protocol script (see the module docstring / README.md). To see it in\n"
    "action without any hardware, run the bundled demo instead:\n\n"
    "    uv run python examples/demo_protocol.py\n"
  )

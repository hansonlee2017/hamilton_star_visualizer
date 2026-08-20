"""Custom labware not (yet) in PyLabRobot's own catalog.

Follows the same pattern PyLabRobot's own resource definitions use (see
e.g. ``pylabrobot.resources.thermo_fisher.plates.
thermo_AB_384_wellplate_40uL_Vb_MicroAmp`` for a real 384-well plate built
the same way) -- a plain factory function returning a ``Plate`` built via
``create_ordered_items_2d``, not a new subclass; that's all PyLabRobot's
own catalog entries are underneath their factory functions too.
"""

from __future__ import annotations

from pylabrobot.resources.plate import Plate
from pylabrobot.resources.utils import create_ordered_items_2d
from pylabrobot.resources.well import CrossSectionType, Well, WellBottomType


def cellvis_384_wellplate_120uL_Fb(name: str) -> Plate:
  """Cellvis 384-well glass-bottom plate, #1.5 high-performance cover glass
  (product ID 53): https://www.cellvis.com/_384-well-glass-bottom-plate-
  with-high-performance-number-1.5-cover-glass_/product_detail.php?product_id=53

  Square wells (bottom area 10.89mm^2 -- exactly 3.3mm^2, not stated
  directly on the product page but unambiguous from that figure, and
  matching the "3.3" callout in the manufacturer's own engineering
  drawing), flat glass bottom, standard 384-well SBS pitch (4.5mm).

  Dimensions, all from the product page and cross-checked against the
  manufacturer's engineering drawing (both agree everywhere they overlap):
    - Plate footprint: 127.60 x 85.60mm (standard SBS). Height (without
      lid): 14.33mm.
    - Well pitch: 4.50mm, both axes.
    - Well bottom area: 10.89mm^2 -> a 3.3 x 3.3mm square well (matches the
      drawing's own "3.3" bottom-opening callout exactly: 3.3 * 3.3 =
      10.89).
    - Max volume: 0.12mL (120uL), stated directly on the product page --
      used here as an explicit override rather than left to the ~124uL a
      plain size_x * size_y * size_z estimate would give, since a real
      well's usable volume is always a little less than its full
      rectangular envelope.
    - Cover glass: 0.170mm +/- 0.005mm thick (#1.5 high-performance),
      sitting 2.78mm above the plate's own bottom exterior surface. Well
      depth (size_z) is derived from these two: 14.33mm total plate height
      - 2.78mm (glass's own bottom face) - 0.17mm (glass thickness) =
      11.38mm of usable internal depth above the glass -- matching the
      drawing's own "11.38" callout exactly, not a coincidence: it's the
      same quantity, just labeled differently in the two sources.
    - A1's center: 12.05mm from the left edge, 9.05mm from the near edge
      (the drawing's own "12.05"/"9.05" callouts) -- converted to
      `create_ordered_items_2d`'s "well origin" convention (its bottom-left
      corner, not center) by subtracting half the well width (1.65mm) from
      each: dx=10.40, dy=7.40.
  """

  well_size = 3.3  # mm, square (see docstring: bottom area 10.89mm^2 = 3.3^2)
  glass_thickness = 0.170  # mm, #1.5 high-performance cover glass
  glass_bottom_z = 2.78  # mm, cover glass's own bottom face above the plate's exterior bottom
  plate_size_z = 14.33  # mm, overall plate height (without lid)
  a1_center_x = 12.05  # mm, from the product's engineering drawing
  a1_center_y = 9.05  # mm, from the product's engineering drawing

  return Plate(
    name=name,
    size_x=127.60,
    size_y=85.60,
    size_z=plate_size_z,
    lid=None,
    model=cellvis_384_wellplate_120uL_Fb.__name__,
    plate_type="skirted",
    ordered_items=create_ordered_items_2d(
      Well,
      num_items_x=24,
      num_items_y=16,
      dx=a1_center_x - well_size / 2,
      dy=a1_center_y - well_size / 2,
      dz=glass_bottom_z,
      item_dx=4.50,
      item_dy=4.50,
      size_x=well_size,
      size_y=well_size,
      size_z=plate_size_z - glass_bottom_z - glass_thickness,
      material_z_thickness=glass_thickness,
      bottom_type=WellBottomType.FLAT,
      cross_section_type=CrossSectionType.RECTANGLE,
      max_volume=120.0,
    ),
  )

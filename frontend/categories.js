// Category -> color palette (simple bounding boxes, no textures/materials
// beyond flat color, per the project's "keep it simple" scope), plus the
// tip-capacity color bucketing shared by resting tips (scene-builder.js),
// carried tips (gantry.js), and live tip-presence updates
// (resource-state.js).

export const CATEGORY_COLORS = {
  deck: 0x3a3f47,
  tip_carrier: 0x5a6270,
  plate_carrier: 0x5a6270,
  plate_holder: 0x5a6270,
  mfx_carrier: 0x5a6270,
  tube_carrier: 0x5a6270,
  trough_carrier: 0x5a6270,
  tip_rack: 0x3d6fa8,
  // Same teal as "well" -- a trough/tube is a liquid container too, and
  // gets the same volumeVisual() fill-level color/opacity treatment
  // automatically (that logic isn't well-specific, just Container-shaped
  // "has a volume" state), so starting from the same base color keeps
  // that gradient reading the same way.
  trough: 0x59c9a5,
  tube: 0x59c9a5,
  // Deliberately *not* a shade of green: a plate's base needs to read as a
  // distinct supporting structure underneath its wells, the same way the
  // tip rack's blue base reads as distinct from its amber/black tips --
  // sharing the well-fill-gradient's hue (green, previously 0x3d9970) made
  // the base blend into its own contents instead of standing apart from it.
  plate: 0x6a5a94,
  well: 0x59c9a5,
  tip_spot: 0x8a8f98,
  trash: 0x8a3d3d,
  // Distinct from every carrier's neutral grey -- this is an active
  // instrument, not passive labware support, and the warm tone previews
  // the shimmer effect run_protocol() triggers (see animateThermocycler
  // Shimmer()).
  thermocycler: 0x8a5a3d,
};
export const DEFAULT_COLOR = 0x6b7280;

// Deck and carrier resources declare a size_z that reflects their whole
// envelope (for a deck, ~900mm can be the instrument housing; for a
// carrier, ~130mm is the full rail height, not the height of the carrier's
// own structure) -- not a value you'd want to draw as a solid box directly.
// The deck is drawn as a thin platform; carriers are drawn as a shaft from
// their base up to their payload's holder -- see scene-builder.js's
// buildResourceObject().
export const CARRIER_CATEGORIES = new Set([
  "tip_carrier",
  "plate_carrier",
  "mfx_carrier",
  "tube_carrier",
  // Confirmed the same envelope-vs-payload gap as every other carrier here
  // (e.g. Trough_CAR_5R60_A00: declared size_z=104mm, but its trough site
  // attaches at only z=63.5mm) -- without this, a reservoir carrier renders
  // as a full-height solid box that buries its own trough, the same bug
  // already fixed for the others in round 7.
  "trough_carrier",
  // Per user direction: render the thermocycler the same "solid block up
  // to the payload holder" way as any other carrier -- its own declared
  // size_z (124.3mm, the ODTC's real full housing height -- see
  // custom_labware.py) is likewise bigger than the visible payload
  // surface (child_location.z, ~74.6mm, where a PCR plate actually sits).
  // A separate lid mesh (see scene-builder.js's buildResourceObject()) sits
  // above this block, not part of it -- the lid is the one part of a real
  // ODTC that visibly moves (see thermocycler_backend.py's docstring:
  // "opens and closes by horizontal move").
  "thermocycler",
]);
// tip_rack and plate have the same "declared size_z is bigger than the
// visible surface" problem as carriers -- their actual payload (a TipSpot's
// tip, a Well's liquid) sits recessed *inside* that declared height, so a
// solid box the full height buries it. Rendered the same way as carriers:
// a thin slab, not the full block.
export const THIN_CATEGORIES = new Set(["tip_rack", "plate"]);

// A present tip's color depends on its nameplate capacity (real Hamilton
// tips physically come in these -- see hamilton_96_tiprack_{50,300,1000}uL_
// filter in this project's demos), read from tip_max_volume_ul wherever a
// tip actually appears (a TipRack's own scene node for resting tips --
// scene-builder.js's buildResourceObject() -- or a pick_up_tips op entry
// for a channel's carried tip -- gantry.js's handleOpEvent()). Picking a
// tip size by transfer volume matters for realism (a 5uL transfer in a
// 1000uL tip is inaccurate on a real instrument) but isn't this file's job
// to enforce -- it just needs to render whichever tip a protocol actually
// used with the right color.
const TIP_COLOR_BY_VOLUME = [
  [50, 0xf48fb1], // pink
  [300, 0xffd54f], // yellow
  [Infinity, 0xffffff], // white
];
// Unknown capacity -- the old flat amber. Exported so gantry.js's
// Core96Head can color its own "tips attached" glyph the same way (it has
// no per-item tip capacity to bucket by, the same "unknown" case this
// covers for a single channel/tip_spot).
export const TIP_PRESENT_COLOR_FALLBACK = 0xe0b23d;
export function tipColorForVolume(maxVolumeUl) {
  if (maxVolumeUl == null) return TIP_PRESENT_COLOR_FALLBACK;
  for (const [threshold, color] of TIP_COLOR_BY_VOLUME) {
    if (maxVolumeUl <= threshold) return color;
  }
  return TIP_PRESENT_COLOR_FALLBACK;
}
// Empty tip spots/wells are always rendered (not hidden) so a slot reads
// as "empty" rather than "missing" -- black distinguishes that at a glance
// from an occupied one, per user feedback.
export const EMPTY_COLOR = 0x000000;
// Shared by scene-builder.js (a tip_spot's initial material, before any
// live state arrives) and resource-state.js (volumeVisual()/tipVisual(),
// which fade between these two opacities by fill fraction).
export const EMPTY_OPACITY = 0.5;
export const FULL_OPACITY = 1.0;

export const LEGEND_ENTRIES = [
  ["Carrier", 0x5a6270],
  ["Tip rack", 0x3d6fa8],
  ["Tip spot (empty)", 0x8a8f98],
  ["Tip (<=50uL)", 0xf48fb1],
  ["Tip (<=300uL)", 0xffd54f],
  ["Tip (<=1000uL)", 0xffffff],
  ["Plate", 0x6a5a94],
  ["Well (fill level)", 0x59c9a5],
  ["Trash", 0x8a3d3d],
  ["Gantry channel", 0xe0b23d],
  ["Thermocycler", 0x8a5a3d],
  ["CO-RE 96 head", 0x4fa8c9],
];

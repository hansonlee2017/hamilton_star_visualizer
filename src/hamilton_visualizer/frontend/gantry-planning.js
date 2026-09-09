// Pure gantry motion-planning math -- no THREE.js, no DOM, nothing browser-
// specific -- split out of gantry.js so it can be exercised directly by
// `node --test` (see tests/frontend/gantry-planning.test.js). gantry.js
// imports these and calls planGantryPasses(entries, channels) with its own
// live Channel array; a test just needs plain `{ pos: { y } }` objects.

// Hamilton STAR's standard channel spacing -- also the minimum center-to-
// center distance two channels can be at without colliding.
export const CHANNEL_PITCH_MM = 9.0;
const ROUND_MM = (v) => Math.round(v * 1000) / 1000;

// Assigns every channel in `channelIndices` (sorted ascending) a y for one
// gantry stop: y must decrease by at least `pitchMm` from each channel to
// the next (channel 0 is the highest-y channel -- see planGantryPasses()'s
// docstring). `fixedY` entries (Map) are non-negotiable -- this stop's real
// targets; every other channel is nudged off its preferred y (also a Map)
// no further than needed to keep the whole sequence in order.
//
// Solved with a change of variable, z[k] = y[channelIndices[k]] + k *
// pitchMm, turning "must decrease by >= pitchMm per step" into the simpler
// "must be non-increasing" -- then one forward pass (each value capped by
// the *actual resolved* value before it -- a fixed value is never capped,
// even if that means it's higher than what came before; that just means
// the earlier ones were resolved too low, corrected next) and one backward
// pass (each value raised to the actual resolved value after it, same
// exception for fixed values) converge on the unique tightest solution. A
// free channel sandwiched between two fixed ones always ends up consistent
// this way; the only way the *final* sequence can still be out of order is
// two fixed channels that are themselves mutually incompatible (out of
// order, or too close together), which is when this throws.
//
// (This is a direct port of hamilton_visualizer.gantry._resolve_ys --
// keep the two in sync if either changes. It lives here, not just
// server-side, because the whole point of moving this logic client-side
// is to sequence passes off each channel's own already-enqueued state --
// see planGantryPasses()'s docstring.)
export function resolveChannelYs(channelIndices, fixedY, preferredY, pitchMm) {
  const eps = 1e-6;
  const n = channelIndices;
  const fixedZ = new Map();
  const preferredZ = new Map();
  n.forEach((ch, k) => {
    if (fixedY.has(ch)) fixedZ.set(k, fixedY.get(ch) + k * pitchMm);
    else preferredZ.set(k, preferredY.get(ch) + k * pitchMm);
  });

  const z = new Array(n.length).fill(0);
  let running = Infinity;
  for (let k = 0; k < n.length; k++) {
    const v = fixedZ.has(k) ? fixedZ.get(k) : Math.min(preferredZ.get(k), running);
    z[k] = v;
    running = v;
  }
  running = -Infinity;
  for (let k = n.length - 1; k >= 0; k--) {
    const v = fixedZ.has(k) ? fixedZ.get(k) : Math.max(z[k], running);
    z[k] = v;
    running = v;
  }
  for (let k = 0; k < n.length - 1; k++) {
    if (z[k] < z[k + 1] - eps) {
      throw new Error(
        `channels ${n[k]} and ${n[k + 1]} need y positions here that put them out of ` +
          `order or closer than ${pitchMm}mm apart -- this combination of targets isn't ` +
          "reachable in one gantry stop"
      );
    }
  }
  const result = new Map();
  n.forEach((ch, k) => result.set(ch, z[k] - k * pitchMm));
  return result;
}

// Groups a single multi-channel op's entries (msg.channels from one
// pick_up_tips/drop_tips/aspirate/dispense event) into a sequence of
// hardware-feasible gantry stops. A real Hamilton STAR's 8 channels are
// all bolted to one arm with a single x motor -- every loaded channel is
// always at the *same* x, whether or not it's doing anything there -- so a
// call whose targets don't share one x can't be reached in a single move,
// the way the naive "animate every entry's own (x, y) independently" code
// this replaced assumed.
//
// Channel-index-to-y direction: channel 0 is the highest-y (e.g. row "A")
// channel, increasing index means decreasing y -- matches how every demo
// in this repo assigns channels (`plate["A1:H1"]` assigns row A to channel
// 0 through row H to channel 7, and row A's y is larger than row H's).
//
// For each distinct x (ascending), every channel in this op with a target
// there is tried simultaneously first; if `resolveChannelYs` can't
// reconcile them (two channels needing y's whose gap, given how many
// channel-slots apart they are, exceeds their actual row gap), it falls
// back to one channel at a time, smallest index first -- exactly what a
// real instrument does when a single move can't reach both. Every *other*
// loaded channel -- whether idle for this whole op (this call doesn't
// target it at all, e.g. the other 7 channels while one alone does a
// single-channel serial dilution) or just this one stop -- gets nudged
// only as far as needed to stay clear, using each channel's own live
// `pos.y` (not a value threaded in from the protocol script) as its
// preferred position. "Loaded" here means "currently has a tip on"
// (`Channel.hasTip`), read directly off the renderer's own live state, not
// just "present in this call's entries" -- so this needs no cooperation
// from the Python side beyond issuing one normal multi-channel (or even
// single-channel) call; it also means a lopsided single-channel stage no
// longer leaves other channels' queues shorter than the busy one's (round
// 15 needed a calculated wait to paper over exactly that gap).
//
// `channels`: an array (index = channel number) of objects with a `.pos.y`
// -- gantry.js passes its own live `Channel[]`; tests just need plain
// `{ pos: { y } }` objects, nothing THREE.js-shaped.
//
// Returns passes ordered so that simply enqueuing each one's legs in
// order -- onto every channel's own independent FIFO queue, see
// gantry.js's Channel.enqueue()'s docstring -- produces correct motion
// with no external timing/sleeping needed at all: each channel's queue
// naturally plays its own legs out in the order they were enqueued, and
// every pass here is only ever enqueued after the previous one.
export function planGantryPasses(entries, channels) {
  const targetedChannels = entries.map((e) => e.channel).sort((a, b) => a - b);
  const byChannel = new Map(entries.map((e) => [e.channel, e]));
  // Every *other* channel is dragged along too, tip or no tip -- a real
  // Hamilton's 8 channels share one arm, so a channel physically cannot
  // stay parked while a call that only targets *some* channels (a
  // single-channel serial dilution, or any multi-channel call with fewer
  // than 8 active entries) moves the arm somewhere else, regardless of
  // whether that channel happens to be carrying a tip right now.
  //
  // This used to be restricted to `loadedChannelsEager` (tip-carrying
  // channels only) -- deliberately widened to *every* channel (confirmed
  // live: a normalization-protocol run's un-targeted, tip-less channels
  // fell badly behind the targeted ones in queued animation time, since
  // they'd previously gotten nothing enqueued at all for calls that
  // didn't target them, eventually catching up to and animating a
  // *later* op -- picking up a tip from a different rack -- while the
  // targeted channels were still working through an earlier one; see
  // docs/PLAN.md's "Review round 34"). nudgeChannel()'s own total
  // duration already equals animateChannelOp()'s (same six leg-durations,
  // just the last three folded into one enqueue() call -- see gantry.js),
  // so dragging every channel along for every op keeps all of them
  // accumulating identical total animation time regardless of which ones
  // a given call actually targets -- true lockstep by construction, for
  // any protocol, not just ones that happen to use every channel evenly.
  const channelIndices = [...new Set([...targetedChannels, ...channels.keys()])].sort(
    (a, b) => a - b
  );
  // xs only ever comes from targeted channels -- a merely-dragged-along
  // channel has no target/x of its own to contribute a stop.
  const xs = [...new Set(targetedChannels.map((ch) => ROUND_MM(byChannel.get(ch).x)))].sort(
    (a, b) => a - b
  );

  // Seeded from each channel's own current position -- always accurate,
  // since it's the same state the renderer itself is driven by -- rather
  // than a snapshot the caller would otherwise have to compute by hand.
  const currentY = new Map(channelIndices.map((ch) => [ch, channels[ch].pos.y]));
  const passes = [];

  for (const x of xs) {
    const columnChannels = targetedChannels.filter((ch) => ROUND_MM(byChannel.get(ch).x) === x);

    let groups = [columnChannels];
    try {
      const fixedY = new Map(columnChannels.map((ch) => [ch, byChannel.get(ch).y]));
      const preferredY = new Map(
        channelIndices
          .filter((ch) => !columnChannels.includes(ch))
          .map((ch) => [ch, currentY.get(ch)])
      );
      resolveChannelYs(channelIndices, fixedY, preferredY, CHANNEL_PITCH_MM);
    } catch {
      groups = columnChannels.map((ch) => [ch]);
    }

    for (const group of groups) {
      const fixedY = new Map(group.map((ch) => [ch, byChannel.get(ch).y]));
      const preferredY = new Map(
        channelIndices.filter((ch) => !group.includes(ch)).map((ch) => [ch, currentY.get(ch)])
      );
      const resolved = resolveChannelYs(channelIndices, fixedY, preferredY, CHANNEL_PITCH_MM);
      for (const [ch, y] of resolved) currentY.set(ch, y);
      const idleMoves = new Map(
        channelIndices.filter((ch) => !group.includes(ch)).map((ch) => [ch, resolved.get(ch)])
      );
      passes.push({ x, active: group.map((ch) => byChannel.get(ch)), idleMoves });
    }
  }
  return passes;
}

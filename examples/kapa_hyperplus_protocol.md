# KAPA HyperPlus Library Prep — Deck Layout & Protocol Reference

Companion reference for [`kapa_hyperplus_demo.py`](kapa_hyperplus_demo.py) — a Hamilton STAR
(PyLabRobot) automation of Chapters 3 & 4 of Roche's **KAPA HyperPlus Kit Instructions for Use**
(v12.0, August 2025), using an Inheco ODTC for thermal cycling and an Alpaqua magnetic plate
adapter for SPRI bead cleanups.

**Assumptions baked into this protocol:** KAPA UDI Adapters (not KAPA Universal Adapter + KAPA UDI
Primer Mixes); Library Amplification included (not a PCR-free stop); 100 ng DNA input targeting
~350 bp fragments (10 min at 37°C); 2 amplification cycles (of the 0–2 Table 4 allows for this
input); no double-sided size selection; no EDTA/Conditioning Solution handling. All volumes and
incubation times below are the IFU's own published numbers.

---

## 1. Deck layout

10 carriers/devices across 48 of the STAR deck's 56 rails:

| Rails | Resource | Contents |
|---|---|---|
| 1–6 | `tip_carrier_1` (`TIP_CAR_480_A00`) | 50µL tip racks — Frag Mix, ERAT Mix, Adapter, Ligation Mix, Elution Add 1 |
| 7–12 | `tip_carrier_2` (`TIP_CAR_480_A00`) | 50µL tip racks — PCR Mix, Bead 2, Elution Add 2 |
| 13–18 | `tip_carrier_3` (`TIP_CAR_480_A00`) | 300µL tip racks — Bead 1, Remove Supernatant 1, EtOH Wash 1a, EtOH Wash 1b, Remove Supernatant 2 |
| 19–24 | `tip_carrier_4` (`TIP_CAR_480_A00`) | 300µL tip racks — EtOH Wash 2a, EtOH Wash 2b |
| 25 | `tube_carrier_small` (`hamilton_tube_carrier_32_a00_insert_eppendorf_1_5mL`) | 1.5mL Eppendorf tube — ERAT Mix |
| 26 | `tube_carrier_large` (`Tube_CAR_24_A00`) | 5mL snap-cap Eppendorf tubes — Frag Mix, Ligation Mix, PCR Mix |
| 27 | `reagent_carrier` (`Trough_CAR_5R60_A00`) | 60mL trough — SPRI beads |
| 28–33 | `plate_carrier_1` (`PLT_CAR_L5AC_A00`) | `working_plate`, `working_plate_lid`, Alpaqua magnetic rack, `amp_plate`, `amp_plate_lid` |
| 35–40 | `plate_carrier_2` (`PLT_CAR_L5AC_A00`) | `adapter_plate`, `output_plate`, ethanol troughplate, elution troughplate |
| 42–48 | Inheco ODTC | Pure cycling destination — never holds a resident plate, no liquid handling here |

Tip racks are grouped by size (50µL on carriers 1–2, 300µL on carriers 3–4) so loading/unloading
tips only ever means visiting one size group. Reagent tubes/trough are placed at site ≥6 on their
carriers (never the front-most sites) so an 8-channel head can align onto them — the same
placement convention this repo's `picogreen_demo.py` already uses.

### 1.1 Tip carrier detail

| Carrier | Site | Tip rack | Size | Used for |
|---|---|---|---|---|
| `tip_carrier_1` | 0 | `tip_rack_frag_mix` | 50µL | Frag Mix addition (15µL transfer, 25µL mix) |
| | 1 | `tip_rack_erat_mix` | 50µL | ERAT Mix addition (10µL transfer, 30µL mix) |
| | 2 | `tip_rack_adapter` | 50µL | KAPA UDI Adapter transfer (5µL, no mix) |
| | 3 | `tip_rack_ligation_mix` | 50µL | Ligation Mix addition (45µL transfer, 50µL mix) |
| | 4 | `tip_rack_elution_add_1` | 50µL | Post-ligation elution buffer (25µL transfer, 15µL mix) **and** the post-ligation eluate transfer (20µL) — same tips, reused, not discarded in between |
| `tip_carrier_2` | 0 | `tip_rack_pcr_mix` | 50µL | PCR Mix addition (30µL transfer, 25µL mix) |
| | 1 | `tip_rack_bead_2` | 50µL | Post-amplification bead addition (50µL transfer, 40µL mix) |
| | 2 | `tip_rack_elution_add_2` | 50µL | Post-amplification elution buffer (25µL transfer, 15µL mix) **and** the final eluate transfer (20µL) — same tips, reused |
| `tip_carrier_3` | 0 | `tip_rack_bead_1` | 300µL | Post-ligation bead addition (88µL transfer, 50µL mix) |
| | 1 | `tip_rack_remove_sup_1` | 300µL | Post-ligation supernatant removal (198µL) |
| | 2 | `tip_rack_etoh1_1` | 300µL | Post-ligation ethanol wash 1 (200µL add + remove) |
| | 3 | `tip_rack_etoh2_1` | 300µL | Post-ligation ethanol wash 2 (200µL add + remove) |
| | 4 | `tip_rack_remove_sup_2` | 300µL | Post-amplification supernatant removal (100µL) |
| `tip_carrier_4` | 0 | `tip_rack_etoh1_2` | 300µL | Post-amplification ethanol wash 1 (200µL add + remove) |
| | 1 | `tip_rack_etoh2_2` | 300µL | Post-amplification ethanol wash 2 (200µL add + remove) |

### 1.2 Plate carrier detail

| Carrier | Site | Resource | Role |
|---|---|---|---|
| `plate_carrier_1` | 0 | `working_plate` | Chapter 3's own plate — fragmentation → ERAT → ligation → post-ligation cleanup |
| | 1 | `working_plate_lid` | Parked here whenever off `working_plate` |
| | 2 | `alpaqua_rack` | Alpaqua magnetic plate adapter — shared by both SPRI cleanups |
| | 3 | `amp_plate` | Chapter 4's own plate — receives the post-ligation eluate, then amplification + post-amp cleanup |
| | 4 | `amp_plate_lid` | Parked here whenever off `amp_plate` |
| `plate_carrier_2` | 0 | `adapter_plate` | KAPA UDI Adapter Kit plate — a 96-well PCR plate (`azenta_96_wellplate_200uL_Vb_4titudeframestar`, same type as `working_plate`/`amp_plate`/`output_plate`), not flat-bottom |
| | 1 | `output_plate` | Final sequencing-ready library |
| | 2 | `ethanol_reservoir` | 80% ethanol, full-footprint troughplate |
| | 3 | `elution_reservoir` | Elution buffer, full-footprint troughplate |

---

## 2. Reagent preparation — what to load, and where

All recipes below are scaled to the exact 96-reaction requirement; the "tube/reservoir fill"
column is what the demo actually loads (including working headroom).

### 2.1 Eppendorf tube premixes

| Premix | Tube | Deck site | Recipe (96 reactions) | Minimum needed | Tube fill (as modeled) |
|---|---|---|---|---|---|
| **Frag Mix** | 5mL snap-cap | `tube_carrier_large`, site 6 | 480µL KAPA Frag Buffer (10X) + 960µL KAPA Frag Enzyme | 1,440µL | 2,000µL |
| **ERAT Mix** | 1.5mL Eppendorf | `tube_carrier_small`, site 6 | 672µL End Repair & A-Tailing Buffer + 288µL End Repair & A-Tailing Enzyme Mix | 960µL | 1,200µL |
| **Ligation Mix** | 5mL snap-cap | `tube_carrier_large`, site 7 | 480µL PCR-grade water + 2,880µL Ligation Buffer + 960µL DNA Ligase | 4,320µL | 4,700µL |
| **PCR Mix** | 5mL snap-cap | `tube_carrier_large`, site 8 | 2,400µL KAPA HiFi HotStart ReadyMix (2X) + 480µL Library Amplification Primer Mix (10X) | 2,880µL | 3,200µL |

> **Ligation Mix's 4,700µL fill is genuinely tight** against the 5mL tube's 5,000µL cap (only
> ~6% headroom) — not a modeling shortcut. The kit's own 96-reaction component volumes (3.8mL
> Ligation Buffer + 1.26mL DNA Ligase, before the water above) already total just over 5mL, so a
> real run at this scale is right at a single 5mL Eppendorf tube's own limit. Consider splitting
> across two tubes if preparing by hand.

Per the IFU, each premix should be freshly combined and used promptly (Frag/ERAT/Ligation
premixes are stable ≤24 hrs at room temperature, ≤3 days at +2°C to +8°C, or ≤4 weeks at
−15°C to −25°C).

### 2.2 Bulk reservoirs

| Reagent | Container | Deck site | Total draw (both cleanups) | Reservoir fill (as modeled) |
|---|---|---|---|---|
| **KAPA HyperPure Beads** | 60mL trough | `reagent_carrier`, site 1 | 13,248µL (8,448µL post-ligation @ 88µL/well + 4,800µL post-amplification @ 50µL/well) | 18,000µL |
| **80% ethanol** (freshly prepared: 4 parts 200-proof ethanol : 1 part nuclease-free water) | Troughplate | `plate_carrier_2`, site 2 | 76,800µL (4 washes × 96 wells × 200µL) | 90,000µL |
| **Elution buffer** (10mM Tris-HCl, pH 8.0–8.5) | Troughplate | `plate_carrier_2`, site 3 | 4,800µL (2 elutions × 96 wells × 25µL) | 6,000µL |

Equilibrate KAPA HyperPure Beads to room temperature ≥30 min before starting, and protect from
light during storage. Prepare ethanol fresh each run — long-term storage evaporates it below 80%.

### 2.3 Plates loaded before Start

| Plate | Deck site | Fill | Source |
|---|---|---|---|
| `working_plate` | `plate_carrier_1`, site 0 | 35µL/well diluted dsDNA (targeting 100 ng input) | User's own sample, diluted in 10mM Tris-HCl pH 8.0–8.5 |
| `adapter_plate` | `plate_carrier_2`, site 0 | 20µL/well KAPA UDI Adapter | KAPA Unique Dual-Indexed Adapter Kit plate, thawed/centrifuged per kit instructions; well position must align 1:1 with `working_plate` |

`amp_plate` and `output_plate` start empty — filled during the run.

---

## 3. Liquid handling steps

Every reagent addition happens with the plate at its own carrier site, never on the ODTC —
**except Enzymatic Fragmentation** (Step 1 below), which the IFU specifically calls out as needing
to be "assembled on ice"; the ODTC's own pre-cooled block substitutes for a benchtop ice bucket for
that one step only. Every other ODTC visit is a full **cap → open door → load → close door →
cycle → open door → unload → close door → uncap** sequence.

Two more conventions worth flagging up front: the Alpaqua rack only ever holds one plate at a
time, so `working_plate` explicitly vacates it (step 25 below) before `amp_plate` needs it for its
own post-amplification cleanup; and each cleanup's elution-buffer tips are held rather than
discarded, then reused directly to aspirate the clarified eluate for the final transfer (steps
20/24 and 38/40) — they never touch anything but elution buffer and that one plate's own wells,
so there's no contamination reason to swap tips in between.

### Chapter 3 — Prepare the Sample Library

**Step 1. Enzymatic Fragmentation** — reagent addition happens *on* the ODTC, not at
`working_plate`'s own site (see note above)
1. Pre-cool the ODTC block to 4°C (`tc.set_block_temperature([4.0])`, Chapter 3 Step 1 item 4a —
   a silent call, no visualizer animation).
2. Open the ODTC door; move the bare, uncapped `working_plate` onto the now-cold block.
3. `add_premix_from_tube`, with `working_plate` sitting on the ODTC: for each of 12 columns —
   pick up 8× 50µL tips, aspirate 15µL from `frag_mix_tube` one channel at a time (only one
   channel fits the tube's ~10mm opening), dispense with an in-tip mix (25µL × 5 reps), discard
   tips. Well: 35 → **50µL**, kept cold throughout assembly.
4. Cap `working_plate` with `working_plate_lid` — only now, immediately before cycling starts.
5. Close the ODTC door; run **37°C, 10 min**; open the door; move the plate back to
   `plate_carrier_1[0]`; close the door; uncap.

**Step 2. End Repair & A-Tailing**
6. `add_premix_from_tube`: 10µL of `erat_mix_tube` per well (5 mix reps at 30µL), same 12-column
   pattern. Well: 50 → **60µL**.
7. `run_thermal_step`: cap → load → **65°C, 30 min** → unload → uncap.

**Step 3. Adapter Ligation**
8. 96-head, single pass: pick up 96 tips from `tip_rack_adapter` → aspirate 5µL from
   `adapter_plate` (well-for-well) → dispense into `working_plate` → discard. No mix (the next
   step's mix covers it). Well: 60 → **65µL**.
9. `add_premix_from_tube`: 45µL of `ligation_mix_tube` per well (6 mix reps at 50µL). Well: 65 →
   **110µL**.
10. `run_thermal_step`: cap → load → **20°C, 15 min** (the IFU explicitly calls for this "on a
    thermocycler") → unload → uncap.

**Step 4. Post-ligation SPRI cleanup** (`run_spri_cleanup`, home site = `plate_carrier_1[0]`)
11. Bind: 8-channel, per column, 88µL beads from `bead_reservoir` into `working_plate`, in-tip mix
    (50µL × 8). Well → **198µL**.
12. `lh.sleep()` 5 min bind incubation.
13. Move `working_plate` → Alpaqua rack.
14. `lh.sleep()` 5 min magnetic separation.
15. 96-head: remove 198µL supernatant, discard tips.
16. Wash 1: 96-head add 200µL 80% EtOH → `lh.sleep()` 30 sec → remove 200µL (same tips) → discard.
17. Wash 2: repeat wash 1.
18. `lh.sleep()` 3 min dry incubation.
19. Move `working_plate` → back to `plate_carrier_1[0]`.
20. 96-head: pick up `tip_rack_elution_add_1`, add 25µL elution buffer, mix (15µL × 6). Tips are
    **not** discarded here.
21. `lh.sleep()` 2 min elution incubation.
22. Move `working_plate` → Alpaqua rack.
23. `lh.sleep()` 2 min clarify incubation.
24. Reusing the *same* tips from step 20 (no fresh pickup): transfer 20µL clarified eluate →
    `amp_plate`, then discard. (5µL deliberately left over the bead pellet.)
25. Move `working_plate` → back to `plate_carrier_1[0]`, off the Alpaqua rack — it would otherwise
    still be occupying the one magnetic rack this deck has when `amp_plate` needs it next.

`working_plate`'s job ends here. `amp_plate` now holds the purified, adapter-ligated library.

### Chapter 4 — Amplify the Sample Library

**Step 1. Prepare the Library Amplification Reaction**
26. `add_premix_from_tube`, at `amp_plate`'s own site: 30µL of `pcr_mix_tube` per well (5 mix reps
    at 25µL). Well: 20 → **50µL**.

**Step 2. Perform the Library Amplification**
27. `run_thermal_step`: cap `amp_plate` with `amp_plate_lid` → open door → move onto ODTC → close
    door → run **98°C/45s → 2× (98°C/15s, 60°C/30s, 72°C/30s) → 72°C/60s** → open door → move back
    to `plate_carrier_1[3]` → close door → uncap.

**Step 3. Post-amplification SPRI cleanup** (`run_spri_cleanup`, home site = `plate_carrier_1[3]`)
28. Bind: 50µL beads (1.0X), in-tip mix (40µL × 8). Well → **100µL**.
29–36. Same 5-min bind incubation / move-to-magnet / 5-min separation / remove supernatant / 2×
    EtOH wash (30s each) / 3-min dry / move-back sequence as Chapter 3's own steps 12–19 (8 items).
37. Pick up `tip_rack_elution_add_2`, add 25µL elution buffer, mix (15µL × 6) — tips held, not
    discarded.
38. `lh.sleep()` 2 min elution incubation; move to Alpaqua rack; `lh.sleep()` 2 min clarify
    incubation.
39. Reusing the same tips from step 37: transfer final **20µL** sequencing-ready library →
    `output_plate`, then discard.

Protocol ends; `mark_finished()` flips the HUD to Reset/Replay.

---

## 4. Volume ladder

| Stage | Well volume |
|---|---|
| DNA input | 35µL |
| + Frag Mix | 50µL |
| + ERAT Mix | 60µL |
| + KAPA UDI Adapter | 65µL |
| + Ligation Mix | 110µL |
| + SPRI beads (0.8X) | 198µL |
| Post-ligation eluate transferred | 20µL |
| + PCR Mix | 50µL |
| + SPRI beads (1.0X) | 100µL |
| **Final library transferred** | **20µL** |

## 5. Incubation times used

| Incubation | Duration | IFU basis |
|---|---|---|
| Bead binding | 5 min | "Incubate... for 5 minutes" |
| Magnetic separation | 5 min | Not separately timed in the IFU ("until the liquid is clear") |
| Ethanol wash hold | 30 sec | "Incubate... for ≥30 seconds" — literal |
| Bead drying | 3 min | Not separately timed ("sufficiently for all ethanol to evaporate") |
| Elution | 2 min | "Incubate... for 2 minutes to allow the sample library to elute" |
| Re-magnet clarify | 2 min | Matches elution's own hold; not separately timed |

Thermal-step timing is real (fragmentation 10 min/37°C, ERAT 30 min/65°C, ligation 15 min/20°C,
amplification per Chapter 4 Table) but purely cosmetic in the visualizer — `run_protocol()`
completes instantly and the frontend plays a fixed 5-second shimmer regardless of the real
duration passed in. The one exception is the ODTC block pre-cool ahead of fragmentation
(`tc.set_block_temperature([4.0])`, Chapter 3 Step 1 item 4a) — a real, silent primitive call with
no visualizer animation of its own, issued before the plate ever lands on the block.

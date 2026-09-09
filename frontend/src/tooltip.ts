// Hover tooltips: raycasts against every hoverable mesh (scene-builder.ts's
// hoverables) and renders whichever resource the pointer is currently over
// into a floating DOM tooltip.

import * as THREE from "three";
import { resourceIndex, hoverables } from "./scene-builder";

// One tooltip line. `textContent`, never `innerHTML` -- `text` here is a
// resource name / catalog model / protocol summary that ultimately comes
// from PyLabRobot serialization (a protocol script, a custom-labware JSON
// file, a CSV-derived id), i.e. attacker-influenceable string data, and
// this node is injected straight into the page.
function tipLine(className: string, text: string): HTMLDivElement {
  const el = document.createElement("div");
  el.className = className;
  el.textContent = text;
  return el;
}

// Called once from main.ts, after the renderer/camera exist.
export function initTooltip(
  camera: THREE.Camera,
  renderer: THREE.WebGLRenderer,
  tooltipEl: HTMLElement
): void {
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();

  renderer.domElement.addEventListener("pointermove", (event: PointerEvent) => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(hoverables, false);
    if (hits.length > 0) {
      const { resourceName, resourceType, category, model } = hits[0].object.userData as {
        resourceName: string;
        resourceType?: string;
        category?: string;
        model?: string | null;
      };
      tooltipEl.style.display = "block";
      tooltipEl.style.left = `${event.clientX + 14}px`;
      tooltipEl.style.top = `${event.clientY + 14}px`;

      tooltipEl.replaceChildren();
      tooltipEl.appendChild(tipLine("name", resourceName));
      tooltipEl.appendChild(
        tipLine("type", `${resourceType ?? ""}${category ? " · " + category : ""}`)
      );
      // Catalog identifier (e.g. "cor_96_wellplate_360uL_Fb",
      // "TIP_CAR_480_A00") -- `model` is a real PyLabRobot Resource field
      // (the name of the factory function/constant that built this specific
      // instance), already present in serialize() output with no scene.py
      // changes needed. `resourceType` above is the much coarser class name
      // ("Plate", "TipCarrier"); this is the specific catalog part number a
      // protocol author would actually recognize.
      if (model) tooltipEl.appendChild(tipLine("model", model));
      // Volume line for any liquid container -- well, trough, or tube -- and
      // only once we actually know a value (entry.volume starts null until
      // the first "state" -- see scene-builder.ts's resourceIndex.set()
      // comment -- so an unstarted protocol just omits the line rather than
      // claiming 0uL).
      if (category === "well" || category === "trough" || category === "tube") {
        const entry = resourceIndex.get(resourceName);
        if (entry && entry.volume != null) {
          // 1 decimal place on both sides -- a resource's real max_volume
          // (e.g. a tube carrier insert's declared capacity) can come out of
          // PyLabRobot as a long float (e.g. 203.52938905975373), not just
          // the live volume, so both need rounding here.
          const max = entry.maxVolume != null ? ` / ${entry.maxVolume.toFixed(1)}` : "";
          tooltipEl.appendChild(tipLine("volume", `${entry.volume.toFixed(1)}${max} µL`));
        }
      }
      // Last-run PCR profile, e.g. "95.0C 0:30, 55.0C 0:30, 72.0C 1:00 (x30)"
      // -- see thermocycler_backend.py's summarize_protocol(). Omitted (not
      // "no protocol yet") until run_protocol() has actually broadcast one.
      if (category === "thermocycler") {
        const entry = resourceIndex.get(resourceName);
        if (entry && entry.protocolSummary) {
          tooltipEl.appendChild(tipLine("volume", entry.protocolSummary));
        }
      }
    } else {
      tooltipEl.style.display = "none";
    }
  });
}

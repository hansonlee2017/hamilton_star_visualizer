// Coordinate mapping: PyLabRobot is (x right, y "back", z up), in
// millimeters. Three.js is conventionally (x right, y up, z toward
// viewer). We map PLR z (height) -> Three y, and PLR y -> Three -z,
// keeping x as-is.

import * as THREE from "three";

export function mapPoint(x, y, z) {
  return new THREE.Vector3(x, z, -y);
}

/* 3D point-cloud viewer. Survey frame is ENU (x east, y north, z up); three.js is y-up,
   so a survey point (x, y, z) is drawn at (x, z, -y). */
import * as THREE from "three";
import { OrbitControls } from "./vendor/three/addons/OrbitControls.js";

const SEV = { high: 0xe5483a, medium: 0xf08a24, low: 0xe3c330 };
const ASSET = 0x7fa6c9;

export function createViewer(el, opts) {
  try {
    return createGlViewer(el, opts);
  } catch (e) {
    console.warn("3D viewer unavailable", e);
    const msg = document.createElement("div");
    msg.className = "viewer-empty";
    msg.textContent = "The 3D view needs WebGL, which this browser has turned off. Map, inventory, plans and verification still work.";
    el.appendChild(msg);
    const noop = () => {};
    return { load: async () => {}, clear: noop, setFindings: noop, highlight: noop, focus: noop, resetCamera: noop,
             setColorMode: noop, setTagging: noop, setActive: noop, unavailable: true };
  }
}

function createGlViewer(el, { onSelect, onTag }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x101413, 1);
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 5000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.screenSpacePanning = true;
  controls.maxPolarAngle = Math.PI * 0.495;

  let points = null;
  let base = null; // { pos, rgb, z }
  let boxes = new THREE.Group();
  let traj = null;
  scene.add(boxes);
  let colorMode = "rgb";
  let tagging = false;
  let active = false;
  let raf = 0;
  let bounds = null;
  const hl = new Set();

  const toThree = (x, y, z) => new THREE.Vector3(x, z, -y);

  function resize() {
    const w = el.clientWidth || 1, h = el.clientHeight || 1;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(el);

  function loop() {
    raf = 0;
    if (!active) return;
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  }

  function applyColors() {
    if (!points || !base) return;
    const n = base.z.length;
    const col = points.geometry.getAttribute("color");
    const arr = col.array;
    if (colorMode === "detector") {
      // points inside the pothole detector's boxes in magenta; everything else as faint grey photo
      for (let i = 0; i < n; i++) {
        if (base.lab && base.lab[i]) { arr[i * 3] = 1.0; arr[i * 3 + 1] = 0.18; arr[i * 3 + 2] = 0.7; continue; }
        const r = base.rgb[i * 3], g = base.rgb[i * 3 + 1], b = base.rgb[i * 3 + 2];
        const l = (0.3 * r + 0.59 * g + 0.11 * b) / 255;
        arr[i * 3] = arr[i * 3 + 1] = arr[i * 3 + 2] = 0.1 + 0.45 * l;
      }
    } else if (colorMode === "rgb") {
      for (let i = 0; i < n * 3; i++) arr[i] = base.rgb[i] / 255;
    } else {
      // height ramp from ground (dark blue-grey) to high (warm white), mono = luminance only
      const lo = -0.15, hi = 9;
      for (let i = 0; i < n; i++) {
        const t = Math.min(1, Math.max(0, (base.z[i] - lo) / (hi - lo)));
        if (colorMode === "height") {
          const g = Math.pow(t, 0.55);
          arr[i * 3] = 0.16 + 0.84 * g;
          arr[i * 3 + 1] = 0.2 + 0.68 * g;
          arr[i * 3 + 2] = 0.3 + 0.45 * g;
        } else {
          const r = base.rgb[i * 3], gg = base.rgb[i * 3 + 1], b = base.rgb[i * 3 + 2];
          const l = (0.3 * r + 0.59 * gg + 0.11 * b) / 255;
          arr[i * 3] = arr[i * 3 + 1] = arr[i * 3 + 2] = 0.12 + 0.88 * l;
        }
      }
    }
    col.needsUpdate = true;
  }

  function clearBoxes() {
    for (const c of boxes.children) { c.geometry.dispose(); c.material.dispose(); }
    boxes.clear();
  }

  const api = {
    async load(buffer, count, trajectory, hasLabels = false) {
      if (points) { scene.remove(points); points.geometry.dispose(); points.material.dispose(); points = null; }
      if (traj) { scene.remove(traj); traj.geometry.dispose(); traj = null; }
      const xyz = new Float32Array(buffer, 0, count * 3);
      const rgb = new Uint8Array(buffer, count * 12, count * 3);
      const pos = new Float32Array(count * 3);
      const z = new Float32Array(count);
      let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
      for (let i = 0; i < count; i++) {
        const x = xyz[i * 3], y = xyz[i * 3 + 1], zz = xyz[i * 3 + 2];
        pos[i * 3] = x; pos[i * 3 + 1] = zz; pos[i * 3 + 2] = -y;
        z[i] = zz;
        if (x < minx) minx = x; if (x > maxx) maxx = x; if (y < miny) miny = y; if (y > maxy) maxy = y;
      }
      const lab = hasLabels && buffer.byteLength >= count * 16 ? new Uint8Array(buffer, count * 15, count) : null;
      base = { rgb, z, lab };
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
      // point size follows the scene: ~5 cm on a 200 m street, ~1 cm on a room-sized clip
      const span = Math.max(maxx - minx, maxy - miny, 1);
      const mat = new THREE.PointsMaterial({ size: Math.min(0.055, Math.max(0.008, span / 4000)), vertexColors: true, sizeAttenuation: true });
      points = new THREE.Points(geo, mat);
      scene.add(points);
      applyColors();
      if (trajectory && trajectory.length > 1) {
        const g = new THREE.BufferGeometry().setFromPoints(trajectory.map((p) => toThree(p[0], p[1], p[2])));
        traj = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0x6ea0e0, transparent: true, opacity: 0.6 }));
        scene.add(traj);
      }
      bounds = { minx, miny, maxx, maxy };
      api.resetCamera();
    },
    clear() {
      if (points) { scene.remove(points); points.geometry.dispose(); points.material.dispose(); points = null; }
      if (traj) { scene.remove(traj); traj = null; }
      clearBoxes();
      base = null;
    },
    setFindings(findings, catalog) {
      clearBoxes();
      for (const f of findings) {
        if (f.status === "dismissed") continue;
        const [x0, y0, z0, x1, y1, z1] = f.bbox;
        const pad = 0.08;
        const sx = x1 - x0 + 2 * pad, sy = y1 - y0 + 2 * pad, sz = Math.max(0.08, z1 - z0 + 2 * pad);
        const kind = catalog[f.type].kind;
        const color = kind === "asset" ? ASSET : SEV[f.severity] || 0xe9d36a;
        const geo = new THREE.EdgesGeometry(new THREE.BoxGeometry(sx, sz, sy));
        const done = ["verified", "fixed"].includes(f.status);
        const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: done ? 0.3 : hl.size && !hl.has(f.id) ? 0.25 : 0.95 });
        const box = new THREE.LineSegments(geo, mat);
        box.position.copy(toThree((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2));
        box.userData.id = f.id;
        boxes.add(box);
      }
    },
    highlight(ids) {
      hl.clear();
      for (const i of ids) hl.add(i);
      for (const b of boxes.children) b.material.opacity = !hl.size || hl.has(b.userData.id) ? 0.95 : 0.25;
    },
    focus(f) {
      const c = toThree(f.x, f.y, f.z);
      const span = Math.max(3, Math.hypot(f.bbox[3] - f.bbox[0], f.bbox[4] - f.bbox[1]) * 3);
      controls.target.copy(c);
      camera.position.copy(c.clone().add(new THREE.Vector3(span * 0.7, span * 0.8, span * 0.9)));
      controls.update();
    },
    resetCamera() {
      if (!bounds) return;
      const cx = (bounds.minx + bounds.maxx) / 2, cy = (bounds.miny + bounds.maxy) / 2;
      const span = Math.max(bounds.maxx - bounds.minx, bounds.maxy - bounds.miny);
      controls.target.copy(toThree(cx, cy, 0));
      camera.position.copy(toThree(cx - span * 0.15, cy - span * 0.55, span * 0.45));
      camera.near = 0.05; camera.far = span * 10 + 500; camera.updateProjectionMatrix();
      controls.update();
    },
    setColorMode(m) { colorMode = m; applyColors(); },
    hasDetectorLabels: () => !!base?.lab,
    setTagging(on) { tagging = on; el.classList.toggle("tagging", on); },
    setActive(on) {
      active = on;
      if (on) { resize(); if (!raf) raf = requestAnimationFrame(loop); }
    },
  };

  // picking: a click (not a drag) selects a box, or in tag mode picks a point
  const ray = new THREE.Raycaster();
  let down = null;
  renderer.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const r = renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    if (tagging && points) {
      const dist = camera.position.distanceTo(controls.target);
      ray.params.Points.threshold = Math.max(0.05, dist * 0.004);
      const hit = ray.intersectObject(points, false)[0];
      if (hit) {
        const p = points.geometry.getAttribute("position");
        const i = hit.index;
        onTag({ x: p.getX(i), y: -p.getZ(i), z: p.getY(i) }, e);
      }
      return;
    }
    ray.params.Line.threshold = 0.12;
    const hit = ray.intersectObjects(boxes.children, false)[0];
    if (hit) onSelect(hit.object.userData.id);
  });

  return api;
}

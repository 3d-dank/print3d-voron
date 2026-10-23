"""A page to turn the part around in: jobs/<slug>/view.html.

One self-contained file, so it opens from disk in a browser or in an agent's
preview pane (Hermes desktop's `open_preview`). The STLs travel inside it as
base64; three.js comes from a CDN.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from print3d.filaments import colour_hex
from print3d.handoff import _parts

THREE = "https://cdn.jsdelivr.net/npm/three@0.160.0"


def _stl(job_dir: Path, part: dict[str, Any], single: bool) -> Path | None:
    if single:
        stl = job_dir / "mesh" / f"{job_dir.name}.stl"
    else:
        stl = job_dir / "mesh" / "assembly" / f"{part['name']}.stl"
    return stl if stl.is_file() else None


def build_viewer(job_dir: Path, report: dict[str, Any]) -> Path | None:
    """Write view.html for the job's mesh, every part where it sits assembled. None without meshes."""
    parts = _parts(report, job_dir.name)
    single = not report.get("parts")
    items = []
    for part in parts:
        stl = _stl(job_dir, part, single)
        if stl is None:
            return None
        items.append({
            "name": part["name"],
            "group": part["object"],
            "color": part["color"],
            "hex": colour_hex(part["color"]),
            "stl": base64.b64encode(stl.read_bytes()).decode("ascii"),
        })
    metrics = report.get("slice_metrics") or {}
    data = {
        "title": report["brief"]["prompt"],
        "status": report.get("status"),
        "minutes": metrics.get("estimated_minutes"),
        "grams": metrics.get("filament_g"),
        "parts": items,
    }
    payload = json.dumps(data).replace("</", "<\\/")
    out = job_dir / "view.html"
    out.write_text(PAGE.replace("__THREE__", THREE).replace("__DATA__", payload), encoding="utf-8")
    return out


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>print3d viewer</title>
<style>
:root { --bg: #f4f4f2; --panel: rgba(255,255,255,.88); --ink: #1d1d1b; --sub: #6b6b66; --line: #d9d9d4; --grid: #c9c9c3; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #18181a; --panel: rgba(32,32,35,.88); --ink: #ececea; --sub: #9a9a96; --line: #3a3a3e; --grid: #3a3a3e; }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--ink);
  font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; overflow: hidden; }
canvas { display: block; }
#panel { position: absolute; top: 12px; left: 12px; max-width: min(320px, calc(100% - 24px));
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px;
  backdrop-filter: blur(8px); }
h1 { font-size: 14px; margin: 0 0 4px; font-weight: 600; }
.sub { color: var(--sub); }
.parts { margin: 10px 0 0; padding: 0; list-style: none; }
.parts label { display: flex; align-items: center; gap: 8px; padding: 2px 0; cursor: pointer; }
.swatch { width: 12px; height: 12px; border-radius: 3px; border: 1px solid var(--line); flex: none; }
.row { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
input[type=range] { flex: 1; min-width: 100px; }
button { font: inherit; color: var(--ink); background: transparent; border: 1px solid var(--line);
  border-radius: 6px; padding: 3px 9px; cursor: pointer; }
button[aria-pressed=true] { background: var(--line); }
#hint { position: absolute; bottom: 10px; left: 0; right: 0; text-align: center; color: var(--sub); pointer-events: none; }
#error { position: absolute; inset: 0; display: none; align-items: center; justify-content: center; padding: 24px; text-align: center; }
</style>
<script type="importmap">
{ "imports": { "three": "__THREE__/build/three.module.js", "three/addons/": "__THREE__/examples/jsm/" } }
</script>
</head>
<body>
<div id="panel">
  <h1 id="title"></h1>
  <div class="sub" id="stats"></div>
  <ul class="parts" id="parts"></ul>
  <div class="row" id="explode-row" hidden>
    <span>Explode</span><input type="range" id="explode" min="0" max="1.5" step="0.01" value="0">
  </div>
  <div class="row">
    <button id="reset">Reset view</button>
    <button id="wire" aria-pressed="false">Wireframe</button>
    <button id="grid-btn" aria-pressed="true">Grid</button>
  </div>
</div>
<div id="hint">Drag to rotate · scroll to zoom · right-drag to pan</div>
<div id="error">Could not load three.js from the CDN. The viewer needs an internet connection the first time.</div>
<script type="application/json" id="data">__DATA__</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const DATA = JSON.parse(document.getElementById('data').textContent);
const fmt = (n, d = 1) => Number(n).toFixed(d);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
document.body.prepend(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000);
camera.up.set(0, 0, 1);  // Blender and the bed are Z-up
scene.add(camera);
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a80, 1.6));
const key = new THREE.DirectionalLight(0xffffff, 1.8);
key.position.set(1, 1, 2);
camera.add(key);  // the light turns with the view, so no face goes black

// Every part where it sits assembled; the whole is centred and stood on the bed.
const loader = new STLLoader();
const meshes = DATA.parts.map(part => {
  const bytes = Uint8Array.from(atob(part.stl), c => c.charCodeAt(0));
  const geometry = loader.parse(bytes.buffer);
  const material = new THREE.MeshStandardMaterial({ color: part.hex, roughness: 0.55, metalness: 0.05 });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData = part;
  scene.add(mesh);
  return mesh;
});
const box = new THREE.Box3();
meshes.forEach(m => box.expandByObject(m));
const shift = new THREE.Vector3(-(box.min.x + box.max.x) / 2, -(box.min.y + box.max.y) / 2, -box.min.z);
meshes.forEach(m => { m.geometry.translate(shift.x, shift.y, shift.z); m.geometry.computeBoundingBox(); });
box.translate(shift);
const size = box.getSize(new THREE.Vector3());
const centre = box.getCenter(new THREE.Vector3());
const span = Math.max(size.length(), 1);

// Each fused group moves away from the middle along the line through its own centre.
const groups = {};
meshes.forEach(m => (groups[m.userData.group] ??= []).push(m));
const away = {};
for (const [name, members] of Object.entries(groups)) {
  const g = new THREE.Box3();
  members.forEach(m => g.union(m.geometry.boundingBox));
  away[name] = g.getCenter(new THREE.Vector3()).sub(centre);
}
const lowest = Math.min(...Object.values(away).map(v => v.z));
Object.values(away).forEach(v => { v.z -= lowest; });  // nothing sinks through the bed
function explode(k) {
  meshes.forEach(m => m.position.copy(away[m.userData.group]).multiplyScalar(k));
}

const cell = size.x > 150 || size.y > 150 ? 20 : 10;
const gridSize = Math.ceil(Math.max(size.x, size.y) * 1.6 / cell) * cell;
const grid = new THREE.GridHelper(gridSize, gridSize / cell,
  getComputedStyle(document.documentElement).getPropertyValue('--grid').trim(),
  getComputedStyle(document.documentElement).getPropertyValue('--grid').trim());
grid.rotation.x = Math.PI / 2;
scene.add(grid);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
function reset() {
  const dir = new THREE.Vector3(1, -1.2, 0.9).normalize();
  camera.position.copy(centre).addScaledVector(dir, span * 1.9);
  controls.target.copy(centre);
  controls.update();
}

document.getElementById('title').textContent = DATA.title;
const stats = [`${fmt(size.x)} × ${fmt(size.y)} × ${fmt(size.z)} mm`];
if (DATA.minutes != null) stats.push(`${Math.round(DATA.minutes)} min`);
if (DATA.grams != null) stats.push(`${fmt(DATA.grams)} g`);
document.getElementById('stats').textContent = stats.join(' · ');

if (meshes.length > 1) {
  const list = document.getElementById('parts');
  meshes.forEach(m => {
    const li = document.createElement('li');
    li.innerHTML = `<label><input type="checkbox" checked><span class="swatch"></span><span></span></label>`;
    li.querySelector('.swatch').style.background = m.userData.hex;
    li.querySelector('span:last-child').textContent = `${m.userData.name} (${m.userData.color})`;
    li.querySelector('input').onchange = e => { m.visible = e.target.checked; };
    list.append(li);
  });
}
if (Object.keys(groups).length > 1) {
  document.getElementById('explode-row').hidden = false;
  document.getElementById('explode').oninput = e => explode(Number(e.target.value));
}
document.getElementById('reset').onclick = reset;
const toggle = (id, apply) => {
  const btn = document.getElementById(id);
  btn.onclick = () => { const on = btn.getAttribute('aria-pressed') !== 'true'; btn.setAttribute('aria-pressed', on); apply(on); };
};
toggle('wire', on => meshes.forEach(m => { m.material.wireframe = on; }));
toggle('grid-btn', on => { grid.visible = on; });

function resize() {
  renderer.setSize(window.innerWidth, window.innerHeight);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();
reset();
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
</script>
<script>
// A module that never ran means the CDN import failed.
window.addEventListener('load', () => setTimeout(() => {
  if (!document.querySelector('canvas')) document.getElementById('error').style.display = 'flex';
}, 1500));
</script>
</body>
</html>
"""

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";

const COLORMAPS = {
  turbo: [
    [0.0, "#30123b"], [0.13, "#4145ab"], [0.27, "#4675ed"], [0.42, "#39a2fc"],
    [0.55, "#1bcfd4"], [0.68, "#24eca6"], [0.8, "#61fc6c"], [0.9, "#b5f238"],
    [1.0, "#ffe84a"]
  ],
  viridis: [
    [0.0, "#440154"], [0.2, "#414487"], [0.4, "#2a788e"], [0.6, "#22a884"],
    [0.8, "#7ad151"], [1.0, "#fde725"]
  ],
  plasma: [
    [0.0, "#0d0887"], [0.2, "#6a00a8"], [0.4, "#b12a90"], [0.6, "#e16462"],
    [0.8, "#fca636"], [1.0, "#f0f921"]
  ],
  coolwarm: [
    [0.0, "#3b4cc0"], [0.25, "#7396f5"], [0.5, "#dddddd"], [0.75, "#f49a7b"], [1.0, "#b40426"]
  ]
};

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const CMAP_CACHE = {};
function colormap(name) {
  const key = name in COLORMAPS ? name : "turbo";
  if (!CMAP_CACHE[key]) {
    CMAP_CACHE[key] = COLORMAPS[key].map(([t, hex]) => [t, hexToRgb(hex)]);
  }
  return CMAP_CACHE[key];
}

export function colorFor(name, t) {
  const stops = colormap(name);
  const v = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i][0]) {
      const [t0, c0] = stops[i - 1];
      const [t1, c1] = stops[i];
      const f = (v - t0) / Math.max(1e-9, t1 - t0);
      return [
        (c0[0] + (c1[0] - c0[0]) * f) / 255,
        (c0[1] + (c1[1] - c0[1]) * f) / 255,
        (c0[2] + (c1[2] - c0[2]) * f) / 255
      ];
    }
  }
  return stops[stops.length - 1][1].map((x) => x / 255);
}

export function rampCss(name) {
  const stops = colormap(name);
  return `linear-gradient(to top, ${stops.map(([t, c]) => `rgb(${c.join(",")}) ${(t * 100).toFixed(1)}%`).join(", ")})`;
}

const tempColor = new THREE.Color();

export class Viewer {
  constructor(canvas, viewport, labelsHost) {
    this.canvas = canvas;
    this.viewport = viewport;
    this.labelsHost = labelsHost;
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x080c12, 0.035);
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1000);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;

    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.className = "viewer-labels";
    labelsHost.appendChild(this.labelRenderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.rotateSpeed = 0.7;
    this.controls.zoomSpeed = 0.9;
    this.controls.panSpeed = 0.75;
    this.controls.minDistance = 0.02;
    this.controls.maxDistance = 500;
    this.controls.target.set(0.5, 0.5, 0.05);

    this.root = new THREE.Group();
    this.scene.add(this.root);
    this.geometryGroup = new THREE.Group();
    this.meshGroup = new THREE.Group();
    this.resultGroup = new THREE.Group();
    this.labelGroup = new THREE.Group();
    this.root.add(this.geometryGroup, this.meshGroup, this.resultGroup, this.labelGroup);

    this.ambient = new THREE.HemisphereLight(0xcfe8ff, 0x0a0f18, 1.7);
    this.scene.add(this.ambient);
    const key = new THREE.DirectionalLight(0xffffff, 2.1);
    key.position.set(3, 5, 4);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x4cc9f0, 1.2);
    rim.position.set(-4, 2, -3);
    this.scene.add(rim);
    const fill = new THREE.DirectionalLight(0xffd7a0, 0.55);
    fill.position.set(-2, -3, 3);
    this.scene.add(fill);

    this.grid = null;
    this.axes = null;
    this.bounds = [0, 1, 0, 1, 0, 1];
    this.geometryLoaded = false;
    this.mode = "geometry";
    this.meshVisible = true;
    this.resultPayload = null;
    this.resultColormap = "turbo";
    this._camAnim = null;
    this._target = new THREE.Vector3(0.5, 0.5, 0.05);
    this._dir = new THREE.Vector3(1.1, 0.8, 1.2);

    const resize = () => this.resize();
    if (window.ResizeObserver) {
      new ResizeObserver(resize).observe(viewport);
    } else {
      window.addEventListener("resize", resize);
    }
    window.addEventListener("resize", resize);
    this.resize();
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
    this.setMode("geometry");
  }

  resize() {
    const rect = this.viewport.getBoundingClientRect();
    const w = Math.max(2, rect.width);
    const h = Math.max(2, rect.height);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
    this.labelRenderer.setSize(w, h);
  }

  _disposeGroup(group) {
    while (group.children.length) {
      const child = group.children.pop();
      child.traverse?.((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose());
          else obj.material.dispose();
        }
        if (obj.isCSS2DObject && obj.element?.parentNode) obj.element.parentNode.removeChild(obj.element);
      });
      group.remove(child);
    }
  }

  _clearScene() {
    this._disposeGroup(this.geometryGroup);
    this._disposeGroup(this.meshGroup);
    this._disposeGroup(this.resultGroup);
    this._disposeGroup(this.labelGroup);
    this.resultPayload = null;
  }

  setBounds(bounds) {
    if (!bounds || bounds.length < 6) return;
    this.bounds = bounds.map(Number);
    const [x0, x1, y0, y1, z0, z1] = this.bounds;
    const size = Math.max(x1 - x0, y1 - y0, z1 - z0, 0.05);
    if (this.grid) {
      this.scene.remove(this.grid);
      this.grid.geometry.dispose();
      this.grid.material.dispose();
    }
    const divisions = 28;
    this.grid = new THREE.GridHelper(size * 2.4, divisions, 0x2a3d50, 0x1a2735);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.4;
    this.grid.position.set((x0 + x1) / 2, y0 - size * 0.02, (z0 + z1) / 2);
    this.scene.add(this.grid);
    if (this.axes) {
      this.scene.remove(this.axes);
      this.axes.geometry.dispose();
      this.axes.material.dispose();
    }
    this.axes = new THREE.AxesHelper(size * 0.24);
    this.axes.position.set(x0, y0, z0);
    this.axes.material.transparent = true;
    this.axes.material.opacity = 0.65;
    this.scene.add(this.axes);
  }

  setGeometry(preview) {
    this._clearScene();
    if (!preview) return;
    this.setBounds(preview.bounds);
    this.geometryLoaded = true;
    const [x0, x1, y0, y1, z0, z1] = preview.bounds;
    preview.parts.forEach((part) => {
      if (part.kind === "error") return;
      const geometry = new THREE.BufferGeometry();
      const verts = new Float32Array(part.vertices || []);
      geometry.setAttribute("position", new THREE.BufferAttribute(verts, 3));
      const idx = part.indices || [];
      if (part.kind === "edges") {
        geometry.setIndex(idx);
        const material = new THREE.LineBasicMaterial({
          color: new THREE.Color(part.color || "#4cc9f0"),
          transparent: true,
          opacity: part.opacity ?? 0.7,
          depthWrite: false
        });
        this.geometryGroup.add(new THREE.LineSegments(geometry, material));
      } else if (part.kind === "domain") {
        geometry.setIndex(idx);
        geometry.computeVertexNormals();
        const material = new THREE.MeshPhysicalMaterial({
          color: new THREE.Color(part.color || "#4cc9f0"),
          transparent: true,
          opacity: part.opacity ?? 0.06,
          side: THREE.DoubleSide,
          depthWrite: false,
          roughness: 0.65,
          metalness: 0.1
        });
        this.geometryGroup.add(new THREE.Mesh(geometry, material));
        const edges = new THREE.EdgesGeometry(geometry, 18);
        const lineMat = new THREE.LineBasicMaterial({
          color: new THREE.Color("#4cc9f0"),
          transparent: true,
          opacity: 0.4,
          depthWrite: false
        });
        this.geometryGroup.add(new THREE.LineSegments(edges, lineMat));
      } else if (part.kind === "mesh") {
        geometry.setIndex(idx);
        geometry.computeVertexNormals();
        const material = new THREE.MeshBasicMaterial({
          color: new THREE.Color(part.color || "#6dd3ff"),
          transparent: true,
          opacity: part.opacity ?? 0.18,
          side: THREE.DoubleSide,
          depthWrite: false
        });
        this.meshGroup.add(new THREE.Mesh(geometry, material));
        const wire = new THREE.MeshBasicMaterial({
          color: new THREE.Color("#7fe1ff"),
          wireframe: true,
          transparent: true,
          opacity: 0.2,
          depthWrite: false
        });
        this.meshGroup.add(new THREE.Mesh(geometry.clone(), wire));
      } else {
        geometry.setIndex(idx);
        geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({
          color: new THREE.Color(part.color || "#f4a261"),
          transparent: (part.opacity ?? 1) < 1,
          opacity: part.opacity ?? 1,
          roughness: 0.42,
          metalness: 0.16,
          side: THREE.DoubleSide,
          flatShading: false
        });
        const mesh = new THREE.Mesh(geometry, material);
        this.geometryGroup.add(mesh);
        const edges = new THREE.EdgesGeometry(geometry, 24);
        this.geometryGroup.add(
          new THREE.LineSegments(
            edges,
            new THREE.LineBasicMaterial({ color: 0x0a0f18, transparent: true, opacity: 0.35 })
          )
        );
      }
    });

    this.labelGroup.visible = this.mode !== "results";
    this.meshGroup.visible = this.meshVisible && this.mode !== "results";
    const markers = preview.markers || {};
    Object.entries(markers).forEach(([key, marker]) => {
      if (!marker || !marker.position) return;
      const div = document.createElement("div");
      const cls = key === "outlet" ? "outlet" : key === "obstacle" ? "solid" : key === "movingWall" ? "wall" : "";
      div.className = `scene-label ${cls}`;
      div.textContent = marker.label || key;
      const label = new CSS2DObject(div);
      label.position.set(marker.position[0], marker.position[1] + (y1 - y0) * 0.045, marker.position[2]);
      this.labelGroup.add(label);

      if (marker.direction) {
        const dir = new THREE.Vector3(...marker.direction).normalize();
        const len = Math.max(0.12, Math.min(x1 - x0, z1 - z0 + (y1 - y0)) * 0.13);
        const start = new THREE.Vector3(...marker.position);
        if (key === "outlet") start.addScaledVector(dir, -len * 0.9);
        else start.addScaledVector(dir, -len * 1.6);
        const arrow = new THREE.ArrowHelper(dir, start, len, key === "outlet" ? 0xf4a261 : 0x4cc9f0, len * 0.32, len * 0.18);
        arrow.line.material.transparent = true;
        arrow.line.material.opacity = 0.85;
        arrow.cone.material.transparent = true;
        arrow.cone.material.opacity = 0.9;
        this.geometryGroup.add(arrow);
      }
    });

    this.setMode(this.mode);
    this.fit();
  }

  setMesh(preview) {
    while (this.meshGroup.children.length) {
      const child = this.meshGroup.children.pop();
      child.traverse?.((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) obj.material.dispose();
      });
    }
    if (!preview || !preview.parts) return;
    preview.parts.forEach((part) => {
      if (!part.vertices || !part.indices) return;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(part.vertices), 3));
      geometry.setIndex(part.indices);
      if (part.kind === "edges") {
        this.meshGroup.add(
          new THREE.LineSegments(
            geometry,
            new THREE.LineBasicMaterial({
              color: new THREE.Color(part.color || "#6dd3ff"),
              transparent: true,
              opacity: part.opacity ?? 0.38,
              depthWrite: false
            })
          )
        );
        return;
      }
      geometry.computeVertexNormals();
      const mat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(part.color || "#6dd3ff"),
        transparent: true,
        opacity: part.opacity ?? 0.16,
        side: THREE.DoubleSide,
        depthWrite: false
      });
      this.meshGroup.add(new THREE.Mesh(geometry, mat));
      this.meshGroup.add(
        new THREE.Mesh(
          geometry.clone(),
          new THREE.MeshBasicMaterial({
            color: 0x7fe1ff,
            wireframe: true,
            transparent: true,
            opacity: 0.2,
            depthWrite: false
          })
        )
      );
    });
    this.meshGroup.visible = this.meshVisible && this.mode !== "results";
  }

  setMeshVisible(visible) {
    this.meshVisible = !!visible;
    this.meshGroup.visible = this.meshVisible && this.mode !== "results";
  }

  setBoundsVisible(visible) {
    this.geometryGroup.children.forEach((child) => {
      if (child.isLineSegments) child.visible = visible;
    });
  }

  setResults(payload, colormapName = this.resultColormap) {
    this._disposeGroup(this.resultGroup);
    this.resultPayload = payload;
    this.resultColormap = colormapName;
    this.mode = "results";
    this.setMode("results");
    if (!payload) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(payload.points), 3));
    geometry.setIndex(payload.indices);
    this._applyResultColors(geometry, payload);
    geometry.computeBoundingSphere();
    const material = new THREE.MeshBasicMaterial({
      vertexColors: true,
      side: THREE.DoubleSide,
      transparent: false,
      opacity: 1,
      depthWrite: true,
      toneMapped: false
    });
    const mesh = new THREE.Mesh(geometry, material);
    this.resultGroup.add(mesh);
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x061019, transparent: true, opacity: 0.18 });
    this.resultGroup.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 28), edgeMat));
    this.resultGroup.visible = true;
    this.meshGroup.visible = false;
  }

  _applyResultColors(geometry, payload) {
    const values = payload.values || [];
    const range = payload.range_focus || payload.range || [0, 1];
    const lo = Number(range[0]);
    const hi = Number(range[1]);
    const span = Math.max(1e-12, hi - lo);
    const colors = new Float32Array(values.length * 3);
    const srgbToLinear = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
    values.forEach((value, i) => {
      const rgb = colorFor(this.resultColormap, (value - lo) / span);
      colors[i * 3] = srgbToLinear(rgb[0]);
      colors[i * 3 + 1] = srgbToLinear(rgb[1]);
      colors[i * 3 + 2] = srgbToLinear(rgb[2]);
    });
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  }

  setResultColormap(name) {
    this.resultColormap = name;
    if (!this.resultPayload) return;
    const mesh = this.resultGroup.children.find((c) => c.isMesh);
    if (mesh) {
      this._applyResultColors(mesh.geometry, this.resultPayload);
      mesh.geometry.attributes.color.needsUpdate = true;
    }
  }

  clearResults() {
    this._disposeGroup(this.resultGroup);
    this.resultPayload = null;
    this.setMode("geometry");
  }

  setMode(mode) {
    this.mode = mode;
    this.resultGroup.visible = mode === "results" && !!this.resultPayload;
    this.meshGroup.visible = this.meshVisible && mode !== "results";
    this.labelGroup.visible = mode !== "results";
  }

  fit() {
    const b = this.bounds;
    const center = new THREE.Vector3((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2);
    const size = new THREE.Vector3(b[1] - b[0], b[3] - b[2], b[5] - b[4]);
    const radius = Math.max(0.05, 0.5 * Math.sqrt(size.x * size.x + size.y * size.y + size.z * size.z));
    const fov = (this.camera.fov * Math.PI) / 180;
    let dist = (radius / Math.sin(fov / 2)) * 1.08;
    if (this.camera.aspect < 1) dist /= this.camera.aspect;
    const dir = this._dir.clone().normalize();
    const position = center.clone().addScaledVector(dir, dist);
    this._animateCamera(position, center, new THREE.Vector3(0, 1, 0));
  }

  setView(name) {
    const b = this.bounds;
    const center = new THREE.Vector3((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2);
    const size = new THREE.Vector3(b[1] - b[0], b[3] - b[2], b[5] - b[4]);
    const radius = Math.max(0.05, 0.5 * Math.sqrt(size.x * size.x + size.y * size.y + size.z * size.z));
    const fov = (this.camera.fov * Math.PI) / 180;
    let dist = (radius / Math.sin(fov / 2)) * 1.1;
    if (this.camera.aspect < 1) dist /= this.camera.aspect;
    let dir;
    let up = new THREE.Vector3(0, 1, 0);
    if (name === "top") {
      dir = new THREE.Vector3(0, 1, 0.001);
      up = new THREE.Vector3(0, 0, -1);
    } else if (name === "front") {
      dir = new THREE.Vector3(0, 0, 1);
    } else if (name === "right") {
      dir = new THREE.Vector3(1, 0, 0);
    } else {
      dir = new THREE.Vector3(1.05, 0.78, 1.15);
    }
    this._dir.copy(dir);
    this._animateCamera(center.clone().addScaledVector(dir.normalize(), dist), center, up);
  }

  _animateCamera(position, target, up) {
    this._camAnim = {
      from: this.camera.position.clone(),
      to: position,
      fromTarget: this.controls.target.clone(),
      toTarget: target,
      fromUp: this.camera.up.clone(),
      toUp: up,
      t: 0
    };
  }

  screenshot() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  compassAngle() {
    const dir = new THREE.Vector3();
    this.camera.getWorldDirection(dir);
    return Math.atan2(dir.x, dir.z);
  }

  _loop() {
    requestAnimationFrame(this._loop);
    if (this._camAnim) {
      const a = this._camAnim;
      a.t = Math.min(1, a.t + 0.075);
      const e = 1 - Math.pow(1 - a.t, 3);
      this.camera.position.lerpVectors(a.from, a.to, e);
      this.controls.target.lerpVectors(a.fromTarget, a.toTarget, e);
      this.camera.up.lerpVectors(a.fromUp, a.toUp, e).normalize();
      if (a.t >= 1) this._camAnim = null;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  }
}

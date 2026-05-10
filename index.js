import * as THREE from "three";
import { OrbitControls } from "https://unpkg.com/three@0.165.0/examples/jsm/controls/OrbitControls.js";

(function () {
  const form = document.getElementById("demo-form");
  const imageInput = document.getElementById("image");
  const uploadPreview = document.getElementById("upload-preview");
  const depthPreview = document.getElementById("depth-preview");
  const annotatedPreview = document.getElementById("annotated-preview");
  const statusEl = document.getElementById("status");
  const metaEl = document.getElementById("meta");
  const viewerEl = document.getElementById("viewer");
  const submitButton = document.getElementById("submit");
  const promptInput = document.getElementById("prompt");

  let previewUrl = null;
  let pointsObject = null;
  let markerData = [];
  let markerSpheres = [];
  let cameraGroup = null;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x090b0f);

  const camera = new THREE.PerspectiveCamera(
    60,
    viewerEl.clientWidth / Math.max(viewerEl.clientHeight, 1),
    0.01,
    1000
  );
  camera.position.set(0, 0, 4);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(viewerEl.clientWidth, Math.max(viewerEl.clientHeight, 1));
  viewerEl.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.target.set(0, 0, -1);

  const grid = new THREE.GridHelper(4, 12, 0x2f3a46, 0x1a222c);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -2;
  scene.add(grid);

  const markerGroup = new THREE.Group();
  scene.add(markerGroup);

  const MARKER_COLORS = {
    chair: 0xff4444,
    table: 0x44ff44,
    door: 0x4444ff,
    person: 0xff8800,
    plant: 0x00cc44,
    monitor: 0x00ccff,
    lamp: 0xffff00,
    window: 0x88ccff,
    couch: 0xcc44cc,
    bed: 0xff6688,
    sink: 0x44cccc,
    toilet: 0xcccc44,
    tv: 0x0088ff,
    book: 0xcc8844,
    bottle: 0x44ccaa,
    cup: 0xffaa44,
    keyboard: 0xaaaaaa,
    phone: 0x88ff88,
    shelf: 0x886644,
    box: 0xff44aa,
    cabinet: 0x668844,
  };
  const TARGET_PALETTE = [
    0xff4444,
    0x44ff44,
    0x4444ff,
    0xff8800,
    0x00ccff,
    0xcc44cc,
    0xffff00,
    0x44cccc,
  ];

  const tooltip = document.createElement("div");
  tooltip.style.cssText =
    "position:fixed;padding:8px 12px;background:rgba(0,0,0,0.85);color:#fff;" +
    "border-radius:6px;font-size:12px;pointer-events:none;display:none;z-index:999;" +
    "font-family:monospace;border:1px solid rgba(255,255,255,0.2);max-width:250px;";
  document.body.appendChild(tooltip);

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function renderTargetList(targets) {
    if (!targets.length) {
      metaEl.textContent = "No targets yet.";
      return;
    }
    metaEl.innerHTML = targets
      .map((target) => {
        const color = `#${getMarkerColor(target.label, target.colorIndex).toString(16).padStart(6, "0")}`;
        const coords = `${target.position.x.toFixed(2)}, ${target.position.y.toFixed(2)}, ${target.position.z.toFixed(2)}`;
        return `
          <div class="target-item">
            <span class="target-swatch" style="background:${color}"></span>
            <span>${target.label}  (${coords})</span>
          </div>
        `;
      })
      .join("");
  }

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }

  function resize() {
    const width = viewerEl.clientWidth;
    const height = Math.max(viewerEl.clientHeight, 1);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  function resetPointCloud() {
    if (!pointsObject) {
      resetMarkers();
      return;
    }
    scene.remove(pointsObject);
    pointsObject.geometry.dispose();
    pointsObject.material.dispose();
    pointsObject = null;
    resetMarkers();
    resetCameraContext();
  }

  function getMarkerColor(label, colorIndex = 0) {
    const base = label.replace(/_\d+$/, "").replace(/ \d+$/, "");
    return MARKER_COLORS[base] || TARGET_PALETTE[colorIndex % TARGET_PALETTE.length];
  }

  function createTextSprite(text, color, subtitle) {
    const canvas = document.createElement("canvas");
    const width = 256;
    const height = subtitle ? 100 : 70;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = "rgba(0,0,0,0.8)";
    ctx.beginPath();
    ctx.roundRect(4, 4, width - 8, height - 8, 10);
    ctx.fill();

    const hex = `#${color.toString(16).padStart(6, "0")}`;
    ctx.strokeStyle = hex;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(4, 4, width - 8, height - 8, 10);
    ctx.stroke();

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 26px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text.toUpperCase(), width / 2, subtitle ? 30 : height / 2);

    if (subtitle) {
      ctx.fillStyle = "#aaaaaa";
      ctx.font = "18px sans-serif";
      ctx.fillText(subtitle, width / 2, 65);
    }

    const texture = new THREE.CanvasTexture(canvas);
    texture.minFilter = THREE.LinearFilter;
    const material = new THREE.SpriteMaterial({
      map: texture,
      depthTest: false,
      sizeAttenuation: true,
    });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(0.35, subtitle ? 0.14 : 0.1, 1);
    return sprite;
  }

  function resetMarkers() {
    markerData = [];
    markerSpheres = [];
    while (markerGroup.children.length) {
      const child = markerGroup.children[0];
      markerGroup.remove(child);
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        if (child.material.map) child.material.map.dispose();
        child.material.dispose();
      }
    }
    tooltip.style.display = "none";
  }

  function resetCameraContext() {
    if (!cameraGroup) {
      return;
    }
    while (cameraGroup.children.length) {
      const child = cameraGroup.children[0];
      cameraGroup.remove(child);
      if (child.geometry) child.geometry.dispose();
      if (child.material) child.material.dispose();
      if (child.line) {
        child.line.geometry.dispose();
        child.line.material.dispose();
      }
      if (child.cone) {
        child.cone.geometry.dispose();
        child.cone.material.dispose();
      }
    }
    scene.remove(cameraGroup);
    cameraGroup = null;
  }

  function updateCameraContext(markers) {
    resetCameraContext();
    cameraGroup = new THREE.Group();

    const frustumDepth = 0.28;
    const frustumHalfW = 0.18;
    const frustumHalfH = 0.12;
    const frustumPoints = [
      new THREE.Vector3(0, 0, 0),
      new THREE.Vector3(-frustumHalfW, frustumHalfH, -frustumDepth),
      new THREE.Vector3(frustumHalfW, frustumHalfH, -frustumDepth),
      new THREE.Vector3(frustumHalfW, -frustumHalfH, -frustumDepth),
      new THREE.Vector3(-frustumHalfW, -frustumHalfH, -frustumDepth),
    ];
    const frustumIndices = [
      [0, 1], [0, 2], [0, 3], [0, 4],
      [1, 2], [2, 3], [3, 4], [4, 1],
    ];
    for (const [a, b] of frustumIndices) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([frustumPoints[a], frustumPoints[b]]),
        new THREE.LineBasicMaterial({ color: 0x7cc7ff, transparent: true, opacity: 0.95 })
      );
      cameraGroup.add(line);
    }

    const radius = pointsObject?.geometry?.boundingSphere?.radius || 1;
    const defaultArrowLength = Math.max(0.1, radius * 0.06);
    for (const marker of markers) {
      const color = getMarkerColor(marker.label, marker.colorIndex);
      const target = new THREE.Vector3(
        marker.position.x,
        marker.position.y,
        marker.position.z
      );
      const distance = target.length();
      if (distance < 1e-8) continue;
      const arrowLength = Math.min(defaultArrowLength, distance);
      const dir = target.clone().normalize();

      const ray = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(0, 0, 0),
          target.clone(),
        ]),
        new THREE.LineDashedMaterial({
          color,
          transparent: true,
          opacity: 0.45,
          dashSize: 0.035,
          gapSize: 0.03,
        })
      );
      ray.computeLineDistances();
      cameraGroup.add(ray);

      const headLength = Math.min(0.06, arrowLength * 0.32);
      const shaftLength = Math.max(arrowLength - headLength, 0.02);
      const shaftRadius = 0.018;
      const headRadius = 0.045;
      const material = new THREE.MeshBasicMaterial({ color });

      const shaft = new THREE.Mesh(
        new THREE.CylinderGeometry(shaftRadius, shaftRadius, shaftLength, 12),
        material
      );
      shaft.position.copy(dir.clone().multiplyScalar(shaftLength * 0.5));
      shaft.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        dir
      );
      cameraGroup.add(shaft);

      const cone = new THREE.Mesh(
        new THREE.ConeGeometry(headRadius, headLength, 12),
        material.clone()
      );
      cone.position.copy(dir.clone().multiplyScalar(shaftLength + headLength * 0.5));
      cone.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        dir
      );
      cameraGroup.add(cone);
    }

    scene.add(cameraGroup);
  }

  function updateMarkers(markers) {
    resetMarkers();
    markerData = markers;

    for (const marker of markers) {
      const { x, y, z } = marker.position;
      const color = getMarkerColor(marker.label, marker.colorIndex);
      const coords = `(${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)})`;

      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(0.04),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.92 })
      );
      sphere.position.set(x, y, z);
      sphere.userData = { marker, coords };
      markerGroup.add(sphere);
      markerSpheres.push(sphere);

      const stem = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(x, y, z),
          new THREE.Vector3(x, y + 0.18, z),
        ]),
        new THREE.LineBasicMaterial({ color })
      );
      markerGroup.add(stem);

      const sprite = createTextSprite(
        marker.label,
        color,
        `${coords} ${(marker.confidence * 100).toFixed(0)}%`
      );
      sprite.position.set(x, y + 0.28, z);
      markerGroup.add(sprite);
    }
  }

  function loadPointCloud(points, colors) {
    resetPointCloud();

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(points.flat(), 3)
    );
    geometry.setAttribute(
      "color",
      new THREE.Float32BufferAttribute(colors.flat(), 3)
    );

    const material = new THREE.PointsMaterial({
      size: 0.025,
      vertexColors: true,
      sizeAttenuation: true,
    });

    pointsObject = new THREE.Points(geometry, material);
    scene.add(pointsObject);

    geometry.computeBoundingSphere();
    const sphere = geometry.boundingSphere;
    if (!sphere) {
      return;
    }

    controls.target.copy(sphere.center);
    const radius = Math.max(sphere.radius, 0.25);
    camera.position.set(
      sphere.center.x,
      sphere.center.y,
      sphere.center.z + radius * 2.4
    );
    camera.near = Math.max(radius / 500, 0.01);
    camera.far = Math.max(radius * 20, 100);
    camera.updateProjectionMatrix();
    controls.update();
  }

  imageInput.addEventListener("change", () => {
    const file = imageInput.files && imageInput.files[0];
    if (!file) {
      return;
    }
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    previewUrl = URL.createObjectURL(file);
    uploadPreview.src = previewUrl;
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = imageInput.files && imageInput.files[0];
    if (!file) {
      setStatus("Choose an image first.");
      return;
    }

    submitButton.disabled = true;
    setStatus("Uploading image and running Depth Anything 3...");
    metaEl.textContent = "Running...";

    const formData = new FormData();
    formData.append("image", file);
    const promptValue = promptInput.value.trim();
    formData.append("prompt", promptValue);

    try {
      const response = await fetch("/api/infer", {
        method: "POST",
        body: formData,
      });

      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || "Inference failed.");
      }

      depthPreview.src = `data:image/png;base64,${result.depth_preview}`;
      annotatedPreview.src = result.annotated_preview
        ? `data:image/png;base64,${result.annotated_preview}`
        : "";
      const targets = (result.targets_3d || []).map((target, index) => ({
        ...target,
        colorIndex: index,
      }));
      renderTargetList(targets);
      loadPointCloud(result.points, result.colors);
      updateMarkers(targets);
      updateCameraContext(targets);
      setStatus(
        `Rendered ${result.meta.point_count} points and ${result.meta.target_count || 0} prompt targets.`
      );
    } catch (error) {
      setStatus(String(error));
      metaEl.textContent = "No targets yet.";
      annotatedPreview.src = "";
      resetPointCloud();
    } finally {
      submitButton.disabled = false;
    }
  });

  renderer.domElement.addEventListener("mousemove", (event) => {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const hits = raycaster.intersectObjects(markerSpheres);

    if (!hits.length) {
      tooltip.style.display = "none";
      renderer.domElement.style.cursor = "default";
      return;
    }

    const { marker, coords } = hits[0].object.userData;
    tooltip.innerHTML =
      `<b>${marker.label.toUpperCase()}</b><br>` +
      `Position: ${coords}<br>` +
      `Confidence: ${(marker.confidence * 100).toFixed(0)}%<br>` +
      `Pixel: (${marker.pixel.x}, ${marker.pixel.y})`;
    tooltip.style.display = "block";
    tooltip.style.left = `${event.clientX + 14}px`;
    tooltip.style.top = `${event.clientY + 14}px`;
    renderer.domElement.style.cursor = "pointer";
  });

  window.addEventListener("resize", resize);
  resize();
  animate();
})();

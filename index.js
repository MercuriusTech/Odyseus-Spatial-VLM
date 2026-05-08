import * as THREE from "three";
import { OrbitControls } from "https://unpkg.com/three@0.165.0/examples/jsm/controls/OrbitControls.js";

(function () {
  const form = document.getElementById("demo-form");
  const imageInput = document.getElementById("image");
  const uploadPreview = document.getElementById("upload-preview");
  const depthPreview = document.getElementById("depth-preview");
  const statusEl = document.getElementById("status");
  const metaEl = document.getElementById("meta");
  const viewerEl = document.getElementById("viewer");
  const submitButton = document.getElementById("submit");

  let previewUrl = null;
  let pointsObject = null;

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

  function setStatus(text) {
    statusEl.textContent = text;
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
      return;
    }
    scene.remove(pointsObject);
    pointsObject.geometry.dispose();
    pointsObject.material.dispose();
    pointsObject = null;
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

    const focalValue = document.getElementById("focal_px").value.trim();
    const fovValue = document.getElementById("fov_deg").value.trim();
    const maxPointsValue = document.getElementById("max_points").value.trim();

    if (focalValue) {
      formData.append("focal_px", focalValue);
    }
    formData.append("fov_deg", fovValue || "60");
    formData.append("max_points", maxPointsValue || "15000");

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
      metaEl.textContent = JSON.stringify(result.meta, null, 2);
      loadPointCloud(result.points, result.colors);
      setStatus(`Rendered ${result.meta.point_count} points.`);
    } catch (error) {
      setStatus(String(error));
      metaEl.textContent = "No result.";
      resetPointCloud();
    } finally {
      submitButton.disabled = false;
    }
  });

  window.addEventListener("resize", resize);
  resize();
  animate();
})();

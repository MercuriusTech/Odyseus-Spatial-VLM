#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import requests
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
DEPTH_ANYTHING_SRC = ROOT / "Depth-Anything-3" / "src"

if str(DEPTH_ANYTHING_SRC) not in sys.path:
    sys.path.insert(0, str(DEPTH_ANYTHING_SRC))

from depth_anything_3.api import DepthAnything3  # noqa: E402

SKIP_LABELS = {"floor", "ceiling", "wall", "ground", "sky", "room", "space", "area"}
MARKER_COLORS = {
    "chair": "#ff4444",
    "table": "#44ff44",
    "door": "#4444ff",
    "person": "#ff8800",
    "plant": "#00cc44",
    "monitor": "#00ccff",
    "lamp": "#ffff00",
    "window": "#88ccff",
    "couch": "#cc44cc",
    "bed": "#ff6688",
    "sink": "#44cccc",
    "toilet": "#cccc44",
    "tv": "#0088ff",
    "book": "#cc8844",
    "bottle": "#44ccaa",
    "cup": "#ffaa44",
    "keyboard": "#aaaaaa",
    "phone": "#88ff88",
    "shelf": "#886644",
    "box": "#ff44aa",
    "cabinet": "#668844",
}
DEFAULT_FOV_DEG = 60.0
DEFAULT_MAX_POINTS = 15000


def estimate_focal_px(width: int, height: int, fov_deg: float) -> float:
    fov_rad = math.radians(fov_deg)
    if fov_rad <= 0 or fov_rad >= math.pi:
        raise ValueError("fov_deg must be between 0 and 180.")
    sensor_span = float(max(width, height))
    return 0.5 * sensor_span / math.tan(fov_rad / 2.0)


def depth_preview_base64(depth_m: np.ndarray, valid_mask: np.ndarray) -> str:
    if not np.any(valid_mask):
        raise ValueError("No valid depth values available for preview.")

    lo, hi = np.percentile(depth_m[valid_mask], [2.0, 98.0])
    if hi <= lo:
        hi = lo + 1e-6

    scaled = np.clip((depth_m - lo) / (hi - lo), 0.0, 1.0)
    preview = (scaled * 255.0).astype(np.uint8)
    preview_rgb = np.stack([preview, preview, preview], axis=-1)

    with io.BytesIO() as buffer:
        Image.fromarray(preview_rgb, mode="RGB").save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def image_base64(image: Image.Image) -> str:
    with io.BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def base_marker_label(label: str) -> str:
    return re.sub(r"[_ ]\d+$", "", label.strip().lower())


def marker_color_hex(label: str) -> str:
    return MARKER_COLORS.get(base_marker_label(label), "#ff00ff")


def normalize_vlm_url(url: str) -> str:
    cleaned = url.rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/v1/chat/completions"


def make_point_cloud(
    rgb: np.ndarray,
    depth_m: np.ndarray,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    max_points: int,
    sky_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    h, w = depth_m.shape
    yy, xx = np.indices((h, w), dtype=np.float32)

    valid = np.isfinite(depth_m) & (depth_m > 0.0)
    if sky_mask is not None:
        valid &= ~sky_mask.astype(bool)

    if not np.any(valid):
        raise ValueError("No valid depth pixels remained after filtering.")

    near, far = np.percentile(depth_m[valid], [1.0, 99.0])
    valid &= depth_m >= near
    valid &= depth_m <= far

    valid_indices = np.flatnonzero(valid.reshape(-1))
    if valid_indices.size == 0:
        raise ValueError("Point cloud filtering removed every pixel.")

    if valid_indices.size > max_points:
        pick = np.linspace(0, valid_indices.size - 1, num=max_points, dtype=np.int64)
        valid_indices = valid_indices[pick]

    flat_x = xx.reshape(-1)[valid_indices]
    flat_y = yy.reshape(-1)[valid_indices]
    flat_z = depth_m.reshape(-1)[valid_indices]

    x = (flat_x - cx) * flat_z / fx
    y = -(flat_y - cy) * flat_z / fy
    z = -flat_z

    points = np.stack([x, y, z], axis=1).astype(np.float32)
    colors = (rgb.reshape(-1, 3)[valid_indices].astype(np.float32) / 255.0).astype(np.float32)

    bounds = {
        "depth_near_m": float(near),
        "depth_far_m": float(far),
        "point_count": int(points.shape[0]),
    }
    return points, colors, bounds


def custom_prompt_template(user_prompt: str) -> str:
    return f"""You are a vision assistant that localizes user-requested targets in a single image.
Find the visible image locations that best satisfy this request:
{user_prompt}

Return ONLY valid JSON in this exact format:
{{"targets":[{{"label":"short lowercase label","x":320,"y":650,"confidence":0.9}}]}}

Coordinate rules:
- x and y must be integers in the range 0-1000
- (0,0) is the top-left of the image
- (1000,1000) is the bottom-right of the image

Content rules:
- Include only targets that are clearly relevant to the request
- Use short lowercase labels
- Maximum 8 targets
- If nothing relevant is visible, return {{"targets":[]}}
- No markdown, no prose, no code fences, only JSON"""


def parse_vlm_targets(raw: str) -> list[dict]:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    else:
        brace = cleaned.find("{")
        if brace >= 0:
            cleaned = cleaned[brace:]

    data = json.loads(cleaned)
    targets = data.get("targets", [])
    valid = []
    for obj in targets:
        if not all(k in obj for k in ("label", "x", "y")):
            continue
        label = str(obj["label"]).lower().strip()
        if not label or base_marker_label(label) in SKIP_LABELS:
            continue
        valid.append(
            {
                "label": label,
                "x": int(np.clip(int(obj["x"]), 0, 1000)),
                "y": int(np.clip(int(obj["y"]), 0, 1000)),
                "confidence": float(obj.get("confidence", 0.7)),
            }
        )
    return valid[:8]


def annotate_targets(rgb: np.ndarray, targets: list[dict]) -> str:
    image = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(image)
    w, h = image.size

    for target in targets:
        px = int(np.clip(target["x"] / 1000.0 * w, 0, w - 1))
        py = int(np.clip(target["y"] / 1000.0 * h, 0, h - 1))
        color = marker_color_hex(target["label"])
        r = max(6, min(w, h) // 60)
        draw.ellipse((px - r, py - r, px + r, py + r), outline=color, width=3)
        draw.line((px, py, px, py - (r * 3)), fill=color, width=3)
        text = f'{target["label"]} {(target["confidence"] * 100):.0f}%'
        tx = min(max(8, px + r + 6), max(8, w - 140))
        ty = max(8, py - (r * 3) - 18)
        draw.rounded_rectangle((tx - 6, ty - 4, tx + 130, ty + 18), radius=6, fill=(0, 0, 0, 190), outline=color)
        draw.text((tx, ty), text, fill="white")

    return image_base64(image)


def project_target_to_3d(
    target: dict,
    depth_map: np.ndarray,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> dict | None:
    img_h, img_w = depth_map.shape
    px = int(np.clip(target["x"] / 1000.0 * img_w, 0, img_w - 1))
    py = int(np.clip(target["y"] / 1000.0 * img_h, 0, img_h - 1))

    r = 5
    y0, y1 = max(0, py - r), min(img_h, py + r + 1)
    x0, x1 = max(0, px - r), min(img_w, px + r + 1)
    patch = depth_map[y0:y1, x0:x1]
    valid = patch[np.isfinite(patch) & (patch > 0.15) & (patch < 25.0)]
    if valid.size == 0:
        return None

    depth_m = float(np.median(valid))
    x_cam = (px - cx) * depth_m / fx
    y_cam = -(py - cy) * depth_m / fy
    z_cam = -depth_m
    return {
        "label": target["label"],
        "confidence": float(target["confidence"]),
        "pixel": {"x": int(px), "y": int(py)},
        "position": {
            "x": float(x_cam),
            "y": float(y_cam),
            "z": float(z_cam),
        },
    }


class DemoRuntime:
    def __init__(self, model_dir: str, device: str, process_res: int):
        self.model_dir = str(Path(model_dir).expanduser())
        self.device = device
        self.process_res = process_res
        self.vlm_url = normalize_vlm_url(os.environ.get("QWEN_URL", "http://127.0.0.1:8012/v1"))
        self.vlm_model = os.environ.get("VLM_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
        self._model: DepthAnything3 | None = None
        self._lock = threading.Lock()

    def _is_local_model_ref(self) -> bool:
        raw = self.model_dir
        return raw.startswith("/") or raw.startswith(".") or raw.startswith("~")

    def load_model(self) -> DepthAnything3:
        with self._lock:
            if self._model is None:
                print(f"Loading model: {self.model_dir} on {self.device}")
                model_path = Path(self.model_dir)
                if self._is_local_model_ref() and not model_path.is_dir():
                    raise FileNotFoundError(
                        "Local DA3 model path must be a directory containing Hugging Face-style "
                        f"weights; got: {model_path}"
                    )
                if model_path.is_dir():
                    self._model = DepthAnything3.from_pretrained(str(model_path)).to(self.device).eval()
                elif self._is_local_model_ref():
                    raise FileNotFoundError(f"Local model directory does not exist: {model_path}")
                else:
                    self._model = DepthAnything3.from_pretrained(self.model_dir).to(self.device).eval()
            return self._model

    def infer_image(
        self,
        image: Image.Image,
        prompt: str | None = None,
    ) -> dict:
        model = self.load_model()
        np_image = np.asarray(image.convert("RGB"))

        prediction = model.inference(
            [np_image],
            process_res=self.process_res,
            process_res_method="upper_bound_resize",
        )

        rgb = prediction.processed_images[0]
        raw_depth = prediction.depth[0].astype(np.float32)
        sky = prediction.sky[0] if prediction.sky is not None else None

        height, width = raw_depth.shape
        used_focal_px = estimate_focal_px(width, height, DEFAULT_FOV_DEG)
        metric_depth_m = raw_depth * (used_focal_px / 300.0)

        fx = used_focal_px
        fy = used_focal_px
        cx = width * 0.5
        cy = height * 0.5

        points, colors, stats = make_point_cloud(
            rgb=rgb,
            depth_m=metric_depth_m,
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            max_points=DEFAULT_MAX_POINTS,
            sky_mask=sky,
        )

        preview_mask = np.isfinite(metric_depth_m) & (metric_depth_m > 0.0)
        if sky is not None:
            preview_mask &= ~sky.astype(bool)

        targets_2d = []
        targets_3d = []
        overlay_base64 = None
        if prompt and prompt.strip():
            targets_2d = self.query_vlm_targets(Image.fromarray(rgb, mode="RGB"), prompt.strip())
            overlay_base64 = annotate_targets(rgb, targets_2d)
            for target in targets_2d:
                projected = project_target_to_3d(
                    target=target,
                    depth_map=metric_depth_m,
                    fx=fx,
                    fy=fy,
                    cx=cx,
                    cy=cy,
                )
                if projected is not None:
                    targets_3d.append(projected)

        return {
            "points": np.round(points, 4).tolist(),
            "colors": np.round(colors, 4).tolist(),
            "depth_preview": depth_preview_base64(metric_depth_m, preview_mask),
            "annotated_preview": overlay_base64,
            "targets_2d": targets_2d,
            "targets_3d": targets_3d,
            "meta": {
                "model_dir": self.model_dir,
                "device": self.device,
                "vlm_model": self.vlm_model,
                "input_size": {"width": int(image.width), "height": int(image.height)},
                "processed_size": {"width": int(width), "height": int(height)},
                "focal_px": float(used_focal_px),
                "fov_deg": float(DEFAULT_FOV_DEG),
                "is_metric_model_output": True,
                "prompt_used": prompt.strip() if prompt else None,
                "target_count": len(targets_3d),
                **stats,
            },
        }

    def query_vlm_targets(self, image: Image.Image, prompt: str) -> list[dict]:
        w, h = image.size
        max_dim = 384
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        image_b64 = image_base64(image)
        payload = {
            "model": self.vlm_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": custom_prompt_template(prompt)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 400,
            "temperature": 0,
        }
        response = requests.post(self.vlm_url, json=payload, timeout=45)
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        return parse_vlm_targets(raw)


def build_app(runtime: DemoRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.load_model()
        yield

    app = FastAPI(title="Depth Anything 3 Metric Point Cloud Demo", lifespan=lifespan)

    @app.get("/")
    async def index() -> FileResponse:
        response = FileResponse(ROOT / "index.html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    @app.get("/index.js")
    async def index_js() -> FileResponse:
        response = FileResponse(ROOT / "index.js", media_type="application/javascript")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "ok": True,
            "device": runtime.device,
            "model_dir": runtime.model_dir,
            "vlm_url": runtime.vlm_url,
            "vlm_model": runtime.vlm_model,
            "model_loaded": runtime._model is not None,
        }

    @app.post("/api/infer")
    async def infer(
        image: UploadFile = File(...),
        prompt: str | None = Form(default=None),
    ) -> dict:
        try:
            payload = await image.read()
            pil_image = Image.open(io.BytesIO(payload))
            pil_image = ImageOps.exif_transpose(pil_image).convert("RGB")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read uploaded image: {exc}") from exc

        try:
            return runtime.infer_image(
                image=pil_image,
                prompt=prompt,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Depth Anything 3 metric point-cloud demo server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model-dir", default="depth-anything/DA3METRIC-LARGE")
    parser.add_argument("--process-res", type=int, default=504)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = DemoRuntime(
        model_dir=args.model_dir,
        device=args.device,
        process_res=args.process_res,
    )
    app = build_app(runtime)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import io
import math
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
DEPTH_ANYTHING_SRC = ROOT / "Depth-Anything-3" / "src"

if str(DEPTH_ANYTHING_SRC) not in sys.path:
    sys.path.insert(0, str(DEPTH_ANYTHING_SRC))

from depth_anything_3.api import DepthAnything3  # noqa: E402


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


class DemoRuntime:
    def __init__(self, model_dir: str, device: str, process_res: int):
        self.model_dir = str(Path(model_dir).expanduser())
        self.device = device
        self.process_res = process_res
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
        focal_px: float | None,
        fov_deg: float,
        max_points: int,
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
        used_focal_px = focal_px or estimate_focal_px(width, height, fov_deg)
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
            max_points=max_points,
            sky_mask=sky,
        )

        preview_mask = np.isfinite(metric_depth_m) & (metric_depth_m > 0.0)
        if sky is not None:
            preview_mask &= ~sky.astype(bool)

        return {
            "points": np.round(points, 4).tolist(),
            "colors": np.round(colors, 4).tolist(),
            "depth_preview": depth_preview_base64(metric_depth_m, preview_mask),
            "meta": {
                "model_dir": self.model_dir,
                "device": self.device,
                "input_size": {"width": int(image.width), "height": int(image.height)},
                "processed_size": {"width": int(width), "height": int(height)},
                "focal_px": float(used_focal_px),
                "fov_deg": None if focal_px is not None else float(fov_deg),
                "is_metric_model_output": True,
                **stats,
            },
        }


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
            "model_loaded": runtime._model is not None,
        }

    @app.post("/api/infer")
    async def infer(
        image: UploadFile = File(...),
        focal_px: float | None = Form(default=None),
        fov_deg: float = Form(default=60.0),
        max_points: int = Form(default=15000),
    ) -> dict:
        if max_points < 1000 or max_points > 100000:
            raise HTTPException(status_code=400, detail="max_points must be between 1000 and 100000.")
        if focal_px is not None and focal_px <= 0:
            raise HTTPException(status_code=400, detail="focal_px must be positive.")
        if focal_px is None and not (10.0 <= fov_deg <= 140.0):
            raise HTTPException(status_code=400, detail="fov_deg must be between 10 and 140.")

        try:
            payload = await image.read()
            pil_image = Image.open(io.BytesIO(payload))
            pil_image = ImageOps.exif_transpose(pil_image).convert("RGB")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read uploaded image: {exc}") from exc

        try:
            return runtime.infer_image(
                image=pil_image,
                focal_px=focal_px,
                fov_deg=fov_deg,
                max_points=max_points,
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

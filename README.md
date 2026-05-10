# Spatial VLM Demo

I've been recently fascinated by the possibilites provided by recent advancements in monocular depth estimation models and decided to expeirment combining them with a capable VLM, so below is an example demo to get 3D outputs from a VLM that can be more useful for a physical AI agent.

Minimal demo for:
- uploading one image
- entering a custom prompt
- using a VLM to localize targets in 2D
- projecting those targets into 3D with `Depth Anything 3 Metric Large`
- visualizing the point cloud, camera frustum, markers, and direction guides in Three.js

## Setup

This repo is currently set up primarily for Linux.

If you clone this as a git repo, prefer pulling the external DA3 dependency as a submodule:

```bash
git clone --recurse-submodules https://github.com/MercuriusTech/Odyseus-Spatial-VLM.git
cd spatial-vlm
```

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

If you are packaging this repo yourself, `Depth-Anything-3/` is intended to track the upstream project as a submodule.

Set up the VLM environment:

```bash
./setup-vlm.sh
```

Set up the depth demo environment:

```bash
./setup.sh
```

## Run

Start the VLM server:

```bash
./run-vlm.sh
```

Start the depth demo:

```bash
./run.sh
```

Then open:

```text
http://localhost:8080
```

## Hosted Demo

If you just want to try it quickly, a hosted demo is available at:

[app.odyseus.xyz](https://app.odyseus.xyz)

The local repo remains the reference implementation for running and modifying the demo yourself.

## Use

1. Upload an image.
2. Enter a prompt like `select the chair near the desk and the closest door`.
3. Click `Run Demo`.
4. Inspect:
   - the 2D target overlay
   - the 3D point cloud
   - labeled 3D targets
   - the camera frustum and guide vectors

## Flow

```mermaid
flowchart LR
    A[User Prompt + Image] --> B[VLM]
    B --> C[2D Target Coordinates]
    A --> D[DA3 Metric Depth]
    C --> E[Depth Sampling]
    D --> E
    E --> F[3D Projection]
    F --> G[Three.js Viewer]
```

## Notes

- Linux is the best-supported path right now.
- PowerShell / Windows setup help is welcome. Contributions for improving `setup-vlm.ps1` or adding fuller Windows support are encouraged.

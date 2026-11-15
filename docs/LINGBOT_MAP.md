# Using LingBot-Map as the decoder

civil-scan contains no machine-learning model. The step "drive video → 3D" is a
**decoder slot**: an external process that writes a point cloud and camera poses.
LingBot-Map is the first intended decoder. You install and run it separately; this
app only calls it and converts its output.

Facts below come from Research Desk's report (`docs/research-lingbot-map-interface.md`,
code read at `Robbyant/lingbot-map` commit `b9dd1b1`, 2026-10-14; nothing was installed
or run). Re-check them when you pin a newer commit.

## What LingBot-Map gives and what the app adds

| | LingBot-Map | civil-scan adds |
|---|---|---|
| Input | Monocular RGB video or image folder (518 px wide); no intrinsics, GPS or IMU | GPS track (`gps.csv`) or camera height for scale |
| Output | Per frame: camera pose, intrinsics, z-depth, confidence (NPZ) | Back-projection to a coloured point cloud (`adapters/lingbot_map.py convert`) |
| Scale | Relative (normalised to the first 8 frames), not metric | Metric scale + map position from GPS (Sim(3) fit) or camera height |
| Up axis | OpenCV camera axes | Up estimated from the ground plane |
| Labels | None | Rule-based detection, manual tags |
| Hardware | CUDA GPU, about 13 GB VRAM in the paper (windowed mode) | Nothing extra |

## Option A: run it yourself, then import (simplest)

1. Install LingBot-Map in its own environment, following its README
   (Python 3.10, PyTorch 2.8 cu128, `pip install -e .`, FlashInfer or `--use_sdpa`).
2. Run it with saved predictions, for example:

   ```bash
   python demo_render/batch_demo.py --video_path street.mp4 --output_folder out/ \
     --model_path lingbot-map.pt --mode windowed --window_size 128 \
     --overlap_keyframes 8 --keyframe_interval 2 --save_predictions --no_render
   ```

3. Convert the per-frame NPZ files (run with civil-scan's environment):

   ```bash
   uv run python adapters/lingbot_map.py convert --pred-dir out/street --out decoded/ --fps 10
   ```

   This writes `decoded/points.ply` and `decoded/poses.json` (camera-to-world).
4. In the app: **New survey** → decoder **Import point cloud (PLY)** → upload
   `points.ply`, `poses.json` and your `gps.csv`. Without GPS, open
   *Scale and placement* and enter the camera height (e.g. 2.1 m on a vehicle roof)
   and the starting heading.

## Option B: let the app run it (decoder slot)

Edit `config/decoders.json`, entry `lingbot_map`:

```json
"enabled": true,
"command": ["{python}", "adapters/lingbot_map.py", "run",
            "--lingbot-python", "/home/you/miniconda3/envs/lingbot/bin/python",
            "--lingbot-repo",   "/home/you/lingbot-map",
            "--model",          "/home/you/lingbot-map/lingbot-map.pt",
            "--video", "{input}", "--out", "{output}",
            "--mode", "windowed", "--fps", "10"]
```

Restart the server. **New survey** now offers *LingBot-Map (external, GPU)*. Upload the
video and `gps.csv` together. Progress and errors are written to
`data/projects/<project>/surveys/<survey>/work/decoder.log`.

Flags after `--` are passed to `batch_demo.py`, e.g. `-- --offload_to_cpu --use_sdpa`.

## gps.csv

Any CSV whose header has a time column (`t`, `time`, `timestamp` or `seconds`) and
`lat` / `lon` columns:

```csv
t,lat,lon
0.0,13.819610,100.513690
0.5,13.819611,100.513735
```

Times are matched to the frame timestamps (`frame index / fps`), so start the GPS
clock at the first video frame. If times don't line up, the app falls back to
matching both tracks by distance along the drive.

## Known caveats (from the report)

- Drift: the authors report about 24 m ATE on KITTI, so GPS georeferencing matters on
  long drives. Split very long drives into several surveys.
- Depth maps are 518 px wide: about 1.4 cm per pixel at 5 m. Good for potholes,
  heaves, poles and signs; not for crack width.
- The Hugging Face card lists `lingbot-map-long.pt` (for long sequences); the GitHub
  README doesn't. Try both.
- Weights licence: the repo is Apache-2.0, but the model card has no licence tag of
  its own. Confirm with Robbyant before commercial use.

## Other decoders with the same role

The slot is generic: any command that writes `points.ply` (+ poses) into `{output}`
works. Research Desk's alternatives: MapAnything (metric, Apache-2.0 weights
variant), Depth Anything 3 (metric only with CC BY-NC weights), ViPE (near-metric).
See the report for their exact output formats.

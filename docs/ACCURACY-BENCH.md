# Pothole 3D Measurement Accuracy Benchmark

Repeatable benchmark for both 3D reconstruction and pothole measurement paths in iScale:

1. **Phone video path:** Video/photo sequence → LingBot-Map (`adapters/lingbot_lowmem.py` + `adapters/lingbot_map.py`) → `civil.align` → `civil.analysis`
2. **FORGE SLAM path:** Multi-sensor LiDAR + IMU (`civil.forge.pipeline.ForgeSlam`) → `civil.align` → `civil.analysis`, plus the shared 3D alignment + surface analysis stage directly on real metric 3D road scans.

## Targets

On real ground-truth data (without making runs slower than 2× baseline):

| Metric | Target |
|---|---|
| Depth MAE | **≤ 1.0 cm** |
| Area error | **≤ 10 %** |
| Volume error | **≤ 15 %** |
| Runtime | **≤ 2× baseline** |

## Methodology & Rules

* **Strict separation of real and synthetic data:** Synthetic numbers are always labelled `synthetic` and never mixed into real-data tables.
* **Strict Dev / Held-Out Test split:** Every iterative fix is developed and judged on **Dev** splits only. **Held-Out Test** splits are measured at baseline and once after finalizing changes.
* **Independent ground truth (never edited):**
  * `stereo_pothole_datasets`: road plane fitted via RANSAC strictly on non-pothole pixels (`label == 0`); GT depth (99th percentile on a 5 mm cell-median grid), area, and volume integrated strictly inside the human pixel mask (`label > 0`) converted mm → m.
  * `rethinking_pothole`: upside-down BQ Ciclop 3D laser scans of physical gypsum pothole molds (`gt/*.ply`, mm → m); GT depth (99.5th percentile), area, and volume integrated on a 2 mm grid.
  * Synthetic scenes: exact continuous analytical depression `d(x, y) ≥ 0` integrated on a 5 mm grid.
* **1-to-1 matching:** Predicted `type == "pothole"` findings are matched greedily by nearest XY centroid within `max(0.50 m, 0.75 × GT diameter)` (`0.25 m` on close-range patches). GT potholes emitted as `manhole_sunken` or `depression` count as misclassified (not hits). `depth_unreliable = True` findings are counted separately and never silently dropped.
* **Collar note on close-range real patches:** Single stereo frames in `stereo_pothole_datasets` cover a narrow `~1.2 m × 0.6 m` field of view, whereas `SegmentSurface.road_mask()` erodes the road border by `0.3 m` on each side (assuming a full street corridor). To test surface measurement without altering any real point, the unmodified real patch is placed inside a level intact-road collar; close-range suites (`real-stereo-*`, `real-laser-*`, `real-video-*`) also pass `pothole_min_area_m2=0.002, pothole_min_depth_m=0.015` because the authors' physical molds are 7–15 cm wide (below iScale's 22.6 cm default filter). `real-stereo-dev-default` records performance with unmodified production defaults.

## Datasets

| Suite | Type | Source & Licence | Size on disk | Dev / Held-Out Test Split | Physical Pothole Scale |
|---|---|---|---|---|---|
| `real-stereo-dev` / `real-stereo-test` | **Real Road Metric 3D GT** | Rui Fan et al., `ruirangerfan/stereo_pothole_datasets` (**MIT**) | 6.5 GB (repo) | Dev: `dataset1` (`n=22` frames); Test: `dataset3` (`n=5` frames). (`dataset2` frames are 0.7–1.5 cm shallow distress, below pothole threshold.) | 7–12 cm wide, 2.4–4.5 cm deep (`0.0035–0.0069 m²`, `0.04–0.12 L`), ~2.23 mm stereo RMSE |
| `real-laser-dev` / `real-laser-test` | **Real 3D Laser Scan GT** | Rui Fan et al., `ruirangerfan/rethinking_road_reconstruction_pothole_detection` (**MIT**) | 878 MB (repo) | Dev: `model1` (5 scans) + `model2` (4 scans) (`n=9`); Test: `model3` (`n=4`) | 7.5–9.6 cm wide, 2.4–4.3 cm deep (`0.0038–0.0063 m²`, `0.04–0.12 L`), BQ Ciclop laser scanner |
| `real-video-dev` / `real-video-test` | **Real Asphalt RGB → LingBot-Map** | RGB sequences from the two MIT repos above | (shared) | Dev: `dataset1/rgb` (22 frames) + `model2/left` (14 frames) (`n=2`); Test: `dataset3/rgb` (5 frames) + `model1/left` (8 frames) (`n=2`) | Same physical potholes above, camera height `0.47–0.55 m` |
| `synth-forge-dev` / `synth-forge-test` | **Synthetic (Full FORGE SLAM)** | Analytical corridor + simulated LiDAR/IMU in `civil/bench_potholes.py` | generated | Dev: 3 scenes (`n=12`); Test: 3 scenes (`n=12`) | Full street scale: 30–105 cm wide, 4.2–12.0 cm deep (`0.095–0.65 m²`, `2.8–58 L`), crown, grade, 1.0–1.4 cm noise, moving traffic |
| `synth-video-dev` / `synth-video-test` | **Synthetic (Rendered RGB → LingBot-Map)** | Physically ray-cast road scenes in `civil/bench_potholes.py` | generated | Dev: 1 drive (`n=3`, GPS + cam-height); Test: 1 drive (`n=3`, GPS) | Full street scale: 45–85 cm wide, 5.0–9.0 cm deep, 28 frames @ 512×384 |

## Reproduce

```sh
# Real-GT metric 3D + real-video LingBot-Map suites
uv run --extra forge civil bench-potholes --suites \
    real-stereo-dev-default real-stereo-dev real-stereo-test \
    real-laser-dev real-laser-test real-video-dev real-video-test

# Synthetic full-scale FORGE SLAM suites
uv run --extra forge civil bench-potholes --suites synth-forge-dev synth-forge-test

# Synthetic full-scale Phone Video (LingBot-Map) suites (needs >= 12 GB free GPU VRAM)
uv run --extra forge civil bench-potholes --suites synth-video-dev synth-video-dev-camh synth-video-test
```

## Baseline Results (Commit `6194d16`)

### Real-GT Data (NOT synthetic)

| Suite | Path | Split | `n` | Recall | FP | Depth MAE (cm) | Depth Max (cm) | Area Err (%) | Vol Err (%) | Time (s) | Peak VRAM (MB) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `real-stereo-dev-default` | Metric 3D → Align → Analysis (defaults) | Dev | 22 | 0.000 | 0 | — | — | — | — | 25.17 | — |
| `real-stereo-dev` | Metric 3D → Align → Analysis (close-range) | Dev | 22 | 0.000 | 2 | — | — | — | — | 24.93 | — |
| `real-stereo-test` | Metric 3D → Align → Analysis (close-range) | Held-Out Test | 5 | 0.000 | 0 | — | — | — | — | 5.75 | — |
| `real-laser-dev` | Laser GT 3D → Align → Analysis (close-range) | Dev | 9 | 1.000 | 0 | 0.85 | 0.98 | 697.3 | 683.0 | 1.65 | — |
| `real-laser-test` | Laser GT 3D → Align → Analysis (close-range) | Held-Out Test | 4 | 0.000 | 0 | — | — | — | — | 0.56 | — |
| `real-video-dev` | Real RGB → LingBot-Map → Align → Analysis | Dev | 2 | 0.500 | 1 | 1.77 | 1.77 | 334.8 | 833.3 | 27.85 | 9393 |
| `real-video-test` | Real RGB → LingBot-Map → Align → Analysis | Held-Out Test | 2 | 0.000 | 0 | — | — | — | — | 26.86 | 10313 |

### Synthetic Full-Scale Data (SYNTHETIC — separate from real data)

| Suite | Path | Split | `n` | Recall | FP | Depth MAE (cm) | Depth Max (cm) | Area Err (%) | Vol Err (%) | Time (s) | Peak VRAM (MB) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `synth-forge-dev` | Full FORGE SLAM → Align → Analysis | Dev | 12 | 1.000 | 0 | 0.36 | 1.00 | 32.58 | 27.15 | 8.47 | — |
| `synth-forge-test` | Full FORGE SLAM → Align → Analysis | Held-Out Test | 12 | 0.917 | 0 | 0.33 | 0.60 | 23.74 | 18.15 | 8.54 | — |
| `synth-video-dev` | Rendered RGB → LingBot-Map (GPS) → Analysis | Dev | 3 | 0.000 | 5 | — | — | — | — | 15.98 | 10073 |
| `synth-video-dev-camh` | Rendered RGB → LingBot-Map (cam h) → Analysis | Dev | 3 | 0.000 | 0 | — | — | — | — | 14.74 | 10373 |
| `synth-video-test` | Rendered RGB → LingBot-Map (GPS) → Analysis | Held-Out Test | 3 | 0.000 | 1 | — | — | — | — | 16.43 | 10795 |

### Diagnosed Top Baseline Error Sources

1. **Pitched-camera ground-plane rejection in `civil/align.py:118`:** `abs(n @ cam_up) < cos(30°)` rejects the true road plane whenever the camera tilts >30° downward (3/4 real video clips) or when roadside walls dominate RANSAC (`synth-video-dev`), falling back to tilted `cam_up` and tilting the road so `coverage = 0.0`.
2. **Hardcoded global height cutoff `xyz[:, 2] < 1.0` in `civil/analysis/__init__.py:141`:** drops road points whenever a sloped or tilted road rises above `z = 1.0 m` instead of filtering relative to local trajectory height.
3. **Coarse 10 cm raster (`raster_m = 0.10`) & lack of local fine measurement in `civil/analysis/detect.py`:** dilutes small real potholes (`0%` recall on `real-stereo-dev`), inflates small-pothole area/volume by ~700% (`real-laser-dev`), and truncates the 0–1 cm sloped rim of full-size potholes (`-30%` area bias, `-25%` volume bias on `synth-forge-dev`).
4. **FORGE 10 cm keyframe voxelisation (`ForgeConfig.voxel_size_m = 0.10` in `civil/forge/pipeline.py:101`) & earliest-hit tile export (`civil/forge/memory.py:267`):** discards fine road geometry before `SpatialTileMemory` and retains far grazing-angle keyframes instead of the closest-range pass per 4 cm voxel.
5. **LingBot-Map monocular depth smoothing & far-depth layering:** LingBot-Map's DPT head smooths sub-10 cm potholes over a ~20–30 cm bowl (and smooths synthetic rendered potholes to flat road at 1.35 m height).

## Final Results — Baseline (`6194d16`) vs Final (`3d-accuracy` after Iterations 1–4 + short-path fix)

### Real-GT Data (NOT synthetic)

| Suite | Split | `n` | Recall (Base → Final) | FP (Base → Final) | Depth MAE cm (Base → Final) | Depth Max cm | Area Err % (Base → Final) | Vol Err % (Base → Final) | Time s (Base → Final) | Peak VRAM (MB) |
|---|---|---:|---|---|---|---:|---|---|---|---:|
| `real-stereo-dev-default` | Dev (prod defaults) | 22 | 0.000 → 0.000 | 0 → 0 | — → — | — | — → — | — → — | 25.17 → 27.06 (1.08×) | — |
| `real-stereo-dev` | Dev (close-range) | 22 | **0.000 → 1.000** | 2 → 2 | — → **0.03** | 0.09 | — → 30.81 | — → **7.56** | 24.93 → 37.51 (1.50×) | — |
| `real-stereo-test` | **Held-Out Test** | 5 | **0.000 → 1.000** | 0 → 0 | — → **0.02** | 0.03 | — → 15.77 | — → **2.58** | 5.75 → 8.25 (1.43×) | — |
| `real-laser-dev` | Dev (close-range) | 9 | 1.000 → **1.000** | 0 → 0 | 0.85 → **0.12** | 0.15 | 697.3 → **7.62** | 683.0 → **8.50** | 1.65 → 2.62 (1.59×) | — |
| `real-laser-test` | **Held-Out Test** | 4 | **0.000 → 1.000** | 0 → 0 | — → **0.15** | 0.19 | — → 18.97 | — → **11.10** | 0.56 → 0.94 (1.68×) | — |
| `real-video-dev` | Dev (LingBot-Map) | 2 | **0.500 → 1.000** | 1 → **0** | 1.77 → **1.05** | 1.10 | 334.8 → 1220.1 | 833.3 → 1615.4 | 27.85 → 28.61 (1.03×) | 9792 |
| `real-video-test` | **Held-Out Test** (LingBot) | 2 | **0.000 → 0.500** | 0 → 0 | — → 1.50 | 1.50 | — → 5933.1 | — → 6017.7 | 26.86 → 24.03 (0.89×) | 10052 |

### Synthetic Full-Scale Data (SYNTHETIC — separate from real data)

| Suite | Split | `n` | Recall (Base → Final) | FP (Base → Final) | Depth MAE cm (Base → Final) | Depth Max cm | Area Err % (Base → Final) | Vol Err % (Base → Final) | Time s (Base → Final) | Peak VRAM (MB) |
|---|---|---:|---|---|---|---:|---|---|---|---:|
| `synth-forge-dev` | Dev (Full FORGE SLAM) | 12 | 1.000 → **1.000** | 0 → 0 | 0.36 → **0.42** | 1.03 | 32.58 → **10.79** | 27.15 → **7.57** | 8.47 → 9.57 (1.13×) | — |
| `synth-forge-test` | **Held-Out Test** (FORGE) | 12 | **0.917 → 1.000** | 0 → 0 | 0.33 → **0.35** | 0.56 | 23.74 → **16.88** | 18.15 → **6.08** | 8.54 → 9.40 (1.10×) | — |
| `synth-video-dev` | Dev (LingBot GPS) | 3 | 0.000 → 0.000 | 5 → **1** | — → — | — | — → — | — → — | 15.98 → 14.40 (0.90×) | 10572 |
| `synth-video-dev-camh` | Dev (LingBot cam h) | 3 | 0.000 → 0.000 | 0 → 2 | — → — | — | — → — | — → — | 14.74 → 15.91 (1.08×) | 8770 |
| `synth-video-test` | **Held-Out Test** (LingBot GPS) | 3 | 0.000 → 0.000 | 1 → 1 | — → — | — | — → — | — → — | 16.43 → 16.91 (1.03×) | 8470 |

## Open Limits & What Data / Hardware Would Help

1. **LingBot-Map monocular depth resolution limit (Phone Video path):** Even with exact road alignment, LingBot-Map's feed-forward DPT head (518 px input width, 14 px ViT patches) smooths narrow ~8 cm potholes into ~20–30 cm wide depressions (`+360%` to `+1500%` area error on real close-range photos, even when depth is within `~1.0–1.5 cm`) and smooths synthetic ray-cast potholes at 1.35 m dashcam height to flat road (`0%` recall). Closing the Phone Video path to `≤ 10%` area / `≤ 15%` volume will require either **multi-view stereo / SfM depth refinement (e.g. metric MVS or phone LiDAR depth maps from iPhone Pro / ARCore Depth API)** or a **metric stereo/RGB-D camera** rather than monocular LingBot-Map alone.
2. **Real-GT dataset aperture bias:** Both public MIT metric-3D pothole datasets (`stereo_pothole_datasets` and `rethinking_pothole`) contain small 7–15 cm potholes that fit a 200 mm desktop laser scanner turntable. Under iScale's production street default (`pothole_min_area_m2 = 0.04 m²`, 22.6 cm diameter), these are intentionally filtered out (`real-stereo-dev-default = 0%` recall). Validating full-size **30–120 cm** real potholes needs user field captures using the Field Recording Protocol below (or an iPhone Pro LiDAR / terrestrial laser scan of full-size road potholes).
3. **Single-frame oblique stereo occlusion (`real-stereo-*` area):** On single-view oblique stereo frames, the near rim occludes part of the cavity wall, creating NaN shadows that under-report visible area by ~16–30% against 2D human pixel masks even while depth (`0.02–0.03 cm`) and volume (`2.6–7.6%`) are highly accurate. Multi-view passes (as in FORGE SLAM) eliminate this occlusion.
4. **Sloped-road `camera_height_m` scaling without GPS:** On clips without GPS or `scene_refs`, steep road grades can bias global Z-histogram camera height; users should supply `gps.csv` or tap a reference object (`scene_refs`) on hilly roads.

---

## Field Recording Protocol (For User Own-Road Verification)

To validate iScale on your own phone and local roads with real tape-measured ground truth (especially full-size 30–120 cm potholes, since public MIT metric-3D pothole datasets only contain 7–15 cm close-range molds):

1. **Pick 3–5 dry potholes** of varied sizes (small ~30 cm, medium ~50–70 cm, large ~80–120 cm; depths ~3–12 cm). Avoid standing water on the first test (water reflects sky and triggers `depth_unreliable`), or record a wet hole separately.
2. **Place a rigid scale reference** flat on intact asphalt 0.5–1.0 m beside each pothole (a 1.00 m carpenter's ruler, high-contrast A4 sheet `210 × 297 mm`, or taped 1.00 m chalk marks). Keep it visible in the video so `scene_refs` can calibrate metric scale without GPS.
3. **Measure ground truth with a straightedge and tape measure:**
   * Lay a rigid straightedge across the intact road rim along the longest axis (`L_cm`) and perpendicular axis (`W_cm`).
   * Measure **maximum depth** (`D_max_cm`) straight down from the underside of the straightedge to the deepest firm point (to the nearest 0.5 cm).
   * For **area** (`A_m2`) and **volume** (`V_L`): measure depths on a 10 cm grid inside the rim (`A ≈ n_cells × 0.01 m²`, `V ≈ Σ depth_m × 0.01 m³ × 1000 L`) or fill a thin plastic liner with measured water/dry sand from a graduated jug (`1 L = 0.001 m³`).
4. **Record the phone video:**
   * Hold or mount the phone steady at a measured height above the road (`H_cm`, e.g. 130 cm walking or dash mount), angled ~15–25° downward so the road fills the lower 2/3 of the frame.
   * Keep **1080p @ 30 fps**, auto-exposure locked if possible, no lens/zoom switching mid-clip, and move smoothly at **walking speed (~1–1.5 m/s)** or **slow drive (~15–20 km/h)** from 6 m before to 4 m past each pothole.
   * Record a second pass with GPS logging (`gps.csv`: `t,lat,lon`) if testing vehicle-speed GPS scaling.
5. **Log each pothole** in a CSV (`id,length_cm,width_cm,depth_max_cm,area_m2,volume_l,cam_height_m,ref_size_m,notes`) and compare against iScale's findings under both camera-height scale and `scene_refs` scale.

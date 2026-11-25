# Pothole 3D Accuracy Improvement Log

Tracks every hypothesis, change, before/after Dev benchmark measurement, runtime/VRAM check, and keep/revert decision.
Held-out Test splits are NOT tuned on and are re-measured only after all iterations complete.

## Iteration 0 — Baseline (`6194d16`)

* **Real-GT Dev:**
  * `real-stereo-dev` (`n=22`): recall `0.000` (0/22, 2 FP), time `24.93 s`
  * `real-laser-dev` (`n=9`): recall `1.000` (9/9, 0 FP), depth MAE `0.85 cm` (max `0.98 cm`, bias `-0.85 cm`), area err `697.3 %`, vol err `683.0 %`, time `1.65 s`
  * `real-video-dev` (`n=2`, LingBot-Map): recall `0.500` (1/2, 1 FP), depth MAE `1.77 cm`, area err `334.8 %`, vol err `833.3 %`, time `27.85 s`, peak VRAM `9393 MB`
* **Synthetic Full-Scale Dev (SYNTHETIC):**
  * `synth-forge-dev` (`n=12`): recall `1.000` (12/12, 0 FP), depth MAE `0.36 cm` (max `1.00 cm`), area err `32.58 %` (bias `-30.09 %`), vol err `27.15 %` (bias `-24.58 %`), time `8.47 s`
  * `synth-video-dev` (`n=3`, LingBot-Map GPS): recall `0.000` (0/3, 5 FP), time `15.98 s`, peak VRAM `10073 MB`
  * `synth-video-dev-camh` (`n=3`, LingBot-Map cam h): recall `0.000` (0/3, 0 FP), time `14.74 s`, peak VRAM `10373 MB`
* **Full test suite:** `229 passed, 1 skipped` (227 pre-existing + 2 benchmark unit tests).

## Iteration 1 — Scale-Invariant Ground-Plane Alignment & Trajectory-Relative Road Filter (KEPT)

* **Hypothesis:** `civil/align.py` rejected the real road plane on cameras pitched >30° downward or in walled corridors (falling back to tilted `cam_up`) and used a fixed `0.2` voxel size before scaling (collapsing compact LingBot clouds to ~100 points). Meanwhile `civil/analysis/__init__.py` used a global `xyz[:, 2] < 1.0` cutoff that clipped sloped/uphill roads.
* **Change:**
  * `civil/align.py`: size pre-alignment voxel sampling to `min(0.2, extent/120)`, restrict ground-plane RANSAC to points below the cameras along `cam_up` with normal within 60° of `cam_up` (`up_prior`, `min_cos=0.5`), rejecting vertical walls while accepting downward-pitched phones.
  * `civil/analysis/__init__.py`: filter near-ground points relative to local trajectory height (`path_z[path_idx] + margin`) instead of global `z < 1.0`.
  * TDD tests added in `tests/test_accuracy_fixes.py` (3 new tests, verified RED before fix and GREEN after).
* **Dev Benchmark Before → After:**
  * `real-video-dev` (`n=2`, LingBot-Map on real asphalt photos): recall **`0.500 → 1.000`** (2/2), FP `1 → 1`, depth MAE **`1.77 → 0.67 cm`** (max `1.07 cm`), area err `334.8 → 887.7 %` (both holes now matched, still quantized to 10×10 cm cells), runtime `27.85 → 28.78 s` (1.03×), VRAM `9393 → 10773 MB`.
  * `synth-video-dev` (`n=3`, SYNTHETIC): recall `0.000 → 0.000`, FP **`5 → 2`**, runtime `15.98 → 16.23 s`.
  * `synth-forge-dev` (`n=12`, SYNTHETIC): recall `1.000 → 1.000`, depth MAE `0.36 → 0.36 cm`, area err `32.58 → 33.24 %`, vol err `27.15 → 28.13 %`, runtime `8.47 → 8.25 s`.
* **Decision:** **KEPT** — major real-video recall (`0.5 → 1.0`) and depth MAE (`1.77 → 0.67 cm`) win; next target is the massive area/volume error (`+697%` / `+888%` on real small potholes, `-33%` on full-scale FORGE potholes) caused by the coarse 10 cm raster and `-1 cm` rim cutoff.

## Iteration 2 — Local High-Resolution Pothole Refinement & Nyquist Sub-Grid Seeding (KEPT)

* **Hypothesis:** The coarse 10 cm raster diluted sub-12 cm real potholes into intact-road cell medians (`0%` recall on `real-stereo-dev`), inflated small-pothole areas by ~700% (`real-laser-dev`), and truncated the 0–1 cm sloped rims of full-size potholes (`-30%` area bias on `synth-forge-dev`). Measuring each detected depression on a density-adapted local fine grid referenced to an IRLS road plane fitted on the intact annular ring around the hole (plus Nyquist-matched road sub-grid seeding when `min_diam < 2 × raster_m`) should dramatically improve both recall and depth/area/volume accuracy without slowing street-scale runs.
* **Change:**
  * `civil/analysis/detect.py`: keep raw segment `(s, o, z)` on `SegmentSurface`; add `_refine_depression` (annular-ring IRLS road plane, density-adapted fine cell `fc`, single-cell spike guard, interior hole filling, noise-calibrated rim threshold `clip(max(3 mm, 1.8·σ_ring), 3 mm, 10 mm)`, unbiased p98/max cell-median peak depth while preserving p25 water-reflection guard); add `_detect_depressions_subgrid` when `min_diam < 2 × raster_m`; store `area_m2` to 4 decimals and `volume_m3` to 5 decimals.
  * TDD tests added in `tests/test_accuracy_fixes.py` (2 new tests: crowned parabolic bowl + small dense pothole, verified RED before fix and GREEN after).
* **Dev Benchmark Before (Iter 1) → After (Iter 2):**
  * `real-stereo-dev` (`n=22`): recall **`0.000 → 1.000`** (22/22, 5 FP), depth MAE **`0.066 cm`** (max `0.17 cm`), area err **`27.69 %`** (bias `-6.7 %`), vol err **`20.71 %`** (bias `+20.7 %`), time `24.93 → 35.18 s` (1.41×).
  * `real-laser-dev` (`n=9`): recall `1.000 → 1.000` (0 FP), depth MAE **`0.85 → 0.52 cm`** (max `0.66 cm`), area err **`697.3 → 51.65 %`**, vol err **`683.0 → 18.01 %`**, time `1.65 → 2.18 s` (1.32×).
  * `real-video-dev` (`n=2`, LingBot-Map): recall `1.000 → 1.000`, FP **`1 → 0`**, depth MAE `0.67 → 1.48 cm`, area err `887.7 → 1345.8 %`, time `28.78 → 27.82 s` (1.00×), VRAM `10373 MB`.
  * `synth-forge-dev` (`n=12`, SYNTHETIC): recall `1.000 → 1.000` (0 FP), depth MAE **`0.36 → 0.32 cm`** (max `1.00 → 0.58 cm`), area err **`33.24 → 16.01 %`** (bias `-30% → -5.3%`), vol err **`28.13 → 20.30 %`** (bias `-25% → -15.0%`), time `8.25 → 8.35 s` (0.99× baseline).
* **Decision:** **KEPT** — huge wins across real stereo recall (`0% → 100%`, `0.07 cm` depth MAE), real laser area/volume (`697% → 52%`, `683% → 18%`), and full-scale FORGE area/volume (`33% → 16%`, `28% → 20%`). Next: inspect per-pothole residuals to bring `real-stereo-dev`, `real-laser-dev`, and `synth-forge-dev` under the 10% area / 15% volume targets and diagnose LingBot-Map video layering.

## Iteration 3 — Depression-Density Fine Grid, Bracketed Gap Fill & Local Road-Relative Height Filter (KEPT)

* **Hypothesis:** (a) `_refine_depression` sized `fc` from the coarse 10 cm box diameter (`dia0 / 10`) and outer collar density rather than the depression's own point density, forcing 2 cm cells on sub-mm laser scans (`+52%` area err, `-0.52 cm` depth bias). (b) Unbracketed gap filling dilated steep rims outward into empty collar cells, while coarse rounding (`round(..., 5)`) added ~10% volume quantization on small holes. (c) `path_z + 0.5` in `analysis/__init__.py` let unremoved vehicle bodies into `SegmentSurface`.
* **Change:**
  * `civil/analysis/detect.py`: size `fc` from `max(rho_dep, rho_ring)` clamped to `[3 mm, surf.cell]` (grid cap `40,000` cells); bracket `_fill_interior_nans` so gaps never dilate outward; add 1-cell sloped-rim recovery above 2.5 mm texture floor (`max(0.0025, 0.55 * used_rt)`) and harmonic 4-neighbor relaxation strictly inside `filled`; reject flat edge slivers (`depth < dmin` or `depth_med < 0.25 * dmin`); round `area_m2` to 5 decimals and `volume_m3` to 6 decimals (also in `merge_split`).
  * `civil/analysis/__init__.py`: estimate local camera height above road (`cam_h_est`) from points near trajectory and filter `xyz[:, 2] < local_road_z + 0.65`.
  * TDD test added in `tests/test_accuracy_fixes.py` (dense 9 cm pothole in 2 cm collar, verified RED before fix and GREEN after).
* **Dev Benchmark Before (Iter 2) → After (Iter 3):**
  * `real-laser-dev` (`n=9`): recall `1.000`, FP `0`, depth MAE **`0.52 → 0.12 cm`** (max **`0.15 cm`**), area err **`51.65 → 7.62 %`**, vol err **`18.01 → 8.50 %`**, time `2.18 → 2.62 s` (1.59× baseline). **All three targets met on real laser GT.**
  * `real-stereo-dev` (`n=22`): recall `1.000`, FP **`5 → 2`**, depth MAE **`0.066 → 0.026 cm`** (max **`0.09 cm`**), area err `27.69 → 30.81 %`, vol err **`20.71 → 7.56 %`**, time `35.18 → 37.41 s` (1.50× baseline). **Depth and volume targets met on real stereo GT.**
  * `real-video-dev` (`n=2`, LingBot-Map): recall `1.000`, FP `0`, depth MAE **`1.48 → 1.05 cm`**, area err `1345.8 → 1220.1 %`, time `27.82 → 30.40 s` (1.09× baseline), VRAM `10754 MB`.
  * `synth-forge-dev` (`n=12`, SYNTHETIC): recall `1.000`, FP `0`, depth MAE `0.32 → 0.37 cm`, area err **`16.01 → 14.81 %`** (bias `-1.55%`), vol err `20.30 → 20.47 %`, time `8.35 → 8.36 s` (0.99× baseline).
* **Decision:** **KEPT** — huge accuracy jump on both real laser GT (depth `0.12 cm`, area `7.6%`, vol `8.5%`) and real stereo GT (depth `0.03 cm`, vol `7.6%`, FP `5 → 2`). Next: preserve 4 cm near-road resolution in FORGE SLAM keyframes (Iteration 4).

## Iteration 4 — FORGE SLAM Near-Road 4 cm Voxelisation & Closest-Range Tile Export (KEPT)

* **Hypothesis:** `ForgeSlam.add_scan` downsampled every keyframe to `10 cm` voxels before tile storage (discarding fine pothole geometry even though `export_world_cloud` exports at `4 cm`), and `SpatialTileMemory.export_world_cloud` kept the chronologically earliest observation per voxel (the far grazing-angle keyframe from 14 m away with maximum cross-keyframe LIO drift, smearing potholes along the driving axis).
* **Change:**
  * `civil/forge/pipeline.py`: add `_downsample_keyframe_points` keeping close-range road points (`r_xy <= 5.5 m`) at `4 cm` (`ROAD_VOXEL_M`), suppressing far grazing-angle road overlap inside the vehicle's driving lane, while keeping off-road structure at `voxel_size_m`.
  * `civil/forge/memory.py`: sort tile points by ascending sensor range `||points_local||` before `voxel_downsample` in `export_world_cloud` so each 4 cm voxel keeps the sharpest, closest-range pass rather than the oldest far pass.
  * TDD tests added in `tests/test_accuracy_fixes.py` (FORGE near-road pothole volume test verified RED before fix + `SpatialTileMemory` closest-range preference test).
* **Dev Benchmark Before (Iter 3) → After (Iter 4):**
  * `synth-forge-dev` (`n=12`, SYNTHETIC): recall `1.000`, FP `0`, depth MAE `0.37 → 0.42 cm` (bias `+0.09 cm`), area err **`14.81 → 10.79 %`** (bias **`-1.04 %`**; baseline was `32.58 %`), vol err **`20.47 → 7.57 %`** (baseline was `27.15 %`), time `8.36 → 9.42 s` (1.11× baseline).
* **Decision:** **KEPT** — slashes FORGE volume error nearly 3× (`20.5% → 7.6%`, half of the 15% target) and area error from `32.6%` baseline to `10.8%` at 1.11× baseline runtime. Next: diagnose LingBot-Map multi-frame depth/confidence filtering on `real-video-dev` (Iteration 5).

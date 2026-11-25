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

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

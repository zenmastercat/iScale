# LingBot-Map: interface facts for the Project_CIVIL decoder slot

Research Desk for Mr.Main. Answered 2026-11-14. All sources accessed 2026-11-14.
Code read at `Robbyant/lingbot-map` commit `b9dd1b1` (2026-10-14). Nothing was installed or run.

Labels:
- **Verified:** a primary source was read (repo code or README, the paper, or the model card).
- **Reported:** the authors' own measurement, or one source that is not independent.
- **Inference:** my own conclusion, with the claims it rests on.
- **Unknown:** I looked and found nothing.

## Answer

LingBot-Map exists. It is an open-source streaming 3D-reconstruction model from Robbyant, the embodied-AI company within Ant Group. It was released on 2026-04-15/16 under Apache-2.0 (code: `github.com/Robbyant/lingbot-map`; paper: arXiv:2604.14141; weights: Hugging Face `robbyant/lingbot-map`).

It takes only monocular RGB frames, from an image folder or a video, resized to 518 px wide. It does not take intrinsics, depth, GPS or IMU. For each frame it returns a camera pose, pinhole intrinsics, a depth map and a confidence map; the point cloud is computed from the depth. Its scale is set by the first 8 frames and is not metric, so the slot needs a separate step to add metric scale and geo-reference.

Confidence: high for what it is and its inputs and outputs, because I read the code and the paper. Medium for speed, memory and accuracy, because the authors measured those themselves.

## 1. What it is

| # | Claim | Label | Src |
|---|---|---|---|
| 1 | A feed-forward "Geometric Context Transformer". It processes video causally, one frame at a time, with a KV cache that holds anchor frames, a 64-frame pose-reference window and a trajectory memory. | Verified | [1][4] |
| 2 | The owner is Robbyant ("Robbyant Team"), "the embodied AI company within Ant Group". Sibling releases: LingBot-Depth, LingBot-VLA, LingBot-World and LingBot-VA. | Verified | [1][6] |
| 3 | The repo was created 2026-04-15, and its last commit is from 2026-10-14. It has no tagged releases, so pin a commit. | Verified | [1] |
| 4 | Paper: arXiv:2604.14141, v1 2026-04-15, v3 2026-09-08 (Chen, Gao, Zhang … Yao, Xu). The README also cites an ECCV 2026 version (pp. 293–314). I did not open the Springer page. | Verified (arXiv) / Reported (ECCV) | [4][1] |
| 5 | Announced 2026-04-16. That is the date in the press-release URL, and the Hugging Face repo was created the same day. | Verified | [5][6] |
| 6 | Licence: Apache-2.0 (`LICENSE.txt`). The README says "This project is released under the Apache License 2.0". The Hugging Face model card has no licence tag of its own. | Verified | [1][5] |
| 7 | Hugging Face files: `lingbot-map.pt` (4.63 GB, "balanced", used for the paper and benchmark); `lingbot-map-long.pt` (4.63 GB, a different hash, "better suited for long sequences and large scale scenes", listed on the model card only); `lingbot-map-stage1.pt` (4.76 GB); `skyseg_batch.onnx` (0.18 GB, sky mask). | Verified | [5][1] |

## 2. Input

| # | Claim | Label | Src |
|---|---|---|---|
| 8 | Monocular RGB only: an image folder (`.jpg`/`.png`, sorted by file name) or a video file. `model.forward()` takes only images scaled to [0, 1]. It has no input for intrinsics, depth, RGB-D, LiDAR, GPS or IMU. | Verified | [2] |
| 9 | Video is decoded with OpenCV and subsampled to `--fps` (default 10 in `demo.py`; all frames in `batch_demo.py`). `--stride` / `--image_stride` and `--first_k` are also available. No minimum or maximum frame rate is documented. | Verified / Unknown (fps limits) | [2] |
| 10 | Each frame is resized to 518 px wide. The height follows the aspect ratio, is rounded to a multiple of 14 and is centre-cropped to at most 518 px. EXIF rotation is applied. The paper's default is 518×378 in bf16. Example: 1920×1080 becomes 518×294 (my arithmetic). | Verified (rule) / Inference (example) | [2][4] |
| 11 | Camera model: pinhole, with the principal point fixed at the image centre. fx and fy come from the predicted field of view. There are no distortion terms, so fisheye footage should be undistorted first (Inference). | Verified | [2] |
| 12 | Sequence length: the model was trained on up to 320 views. Direct mode stays stable up to about 3,000 frames; above 320 frames the keyframe interval is set automatically to ceil(N/320). Beyond about 3,000 frames, use windowed ("VO") mode, which resets each window and aligns windows with Sim(3) (scale, rotation and translation). | Verified | [4][1][2] |

## 3. Output

| # | Claim | Label | Src |
|---|---|---|---|
| 13 | Output is a Python dict with batch dimension B and S frames:<br>• `pose_enc` [B,S,9]: camera position (3), rotation quaternion in XYZW order (4), and vertical and horizontal field of view in radians (2)<br>• `depth` [B,S,H,W,1]<br>• `depth_conf` [B,S,H,W], values ≥ 1<br>• `frame_type` (0 = anchor, 1 = keyframe, 2 = non-keyframe) and `is_keyframe`<br>• windowed mode only: `chunk_scales` and `chunk_transforms`, the per-window alignment | Verified | [2] |
| 14 | The released checkpoint runs with the point head off (`enable_point=False`). Point clouds come from back-projecting depth through the predicted cameras. Depth is z-depth along the optical axis. | Verified | [2][3] |
| 15 | `pose_encoding_to_extri_intri()` returns camera-to-world [R\|t] with OpenCV axes (x right, y down, z forward), so p_world = R·p_cam + t. Intrinsics are 3×3, in pixels of the 518-px model image. `demo.py` and `batch_demo.py` invert the pose and save world-to-camera 3×4 as `extrinsic`. | Verified | [2] |
| 16 | **Scale is not metric.** Training divides every ground-truth depth and camera translation by s, the mean distance of the anchor frames' points from the origin. The first n = 8 frames "establish the scale and coordinate system". All outputs are in units relative to the scene in those opening frames. | Verified | [4][2] |
| 17 | World origin: the anchor frames fix the coordinate system, but no source I read says which camera is the identity. It is most likely frame 0, as in VGGT, the model LingBot-Map builds on. | Inference (from 16 and [1] acknowledgements) | [1][4] |
| 18 | Files written:<br>• `demo.py`: none. It opens a viser viewer at `localhost:8080`.<br>• `demo_render/batch_demo.py --save_predictions`: `<out>/<scene>/frame_000000.npz …`, one file per frame with `pose_enc`, `depth`, `depth_conf`, `extrinsic` (world-to-camera 3×4), `intrinsic` (3×3) and `images`, plus `meta.npz` for arrays such as `frame_type`.<br>• `--save_glb`: `<scene>.glb`, a trimesh point cloud with camera frusta.<br>• Default output: an MP4 fly-through. | Verified (code reading, not run) | [1][2] |
| 19 | The GLB is re-oriented for viewing: aligned to the first camera, Y and Z flipped to OpenGL axes and rotated 180° about Y. It is not in the model's own world frame. | Verified | [2] |
| 20 | It produces no meshes, semantic labels or defect classes. The only segmentation is an ONNX sky mask that drops sky points. | Verified | [1][2] |

## 4. How to run

```bash
conda create -n lingbot-map python=3.10 -y && conda activate lingbot-map
pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
pip install -e .                      # in the cloned repo; torch is NOT in pyproject deps
pip install flashinfer-python         # recommended; otherwise pass --use_sdpa
pip install -e ".[vis]"               # viewer (optional)

# Interactive viewer only (writes no prediction files)
python demo.py --model_path lingbot-map.pt --video_path street.mp4 --fps 10 --mask_sky

# Writes files: per-frame NPZ (+ GLB), long drive in windowed mode, no video render
python demo_render/batch_demo.py --video_path street.mp4 --output_folder out/ \
  --model_path lingbot-map.pt --mode windowed --window_size 128 --overlap_keyframes 8 \
  --keyframe_interval 2 --save_predictions --save_glb --no_render
# (batch_demo also takes --input_folder ROOT of scene folders; the render path needs ".[vis,render]", Kaolin, ffmpeg and a CUDA-extension build)
```

| # | Claim | Label | Src |
|---|---|---|---|
| 21 | The install steps above and both commands come from the README and the argparse code. `demo.py` flags: `--image_folder` / `--video_path`, `--fps`, `--mode streaming\|windowed`, `--keyframe_interval`, `--window_size` (64), `--overlap_keyframes`, `--num_scale_frames` (8), `--camera_num_iterations` (4), `--use_sdpa`, `--compile`, `--offload_to_cpu`, `--mask_sky`. | Verified | [1][2] |
| 22 | Python API:<br>1. Build `GCTStream` from `lingbot_map.models.gct_stream` (or `gct_stream_window` for windowed mode) with `img_size=518, patch_size=14, enable_3d_rope=True, max_frame_num=1024, kv_cache_sliding_window=64, kv_cache_scale_frames=8, kv_cache_cross_frame_special=True, kv_cache_include_scale_frames=True, camera_num_iterations=4`.<br>2. Load the checkpoint with `load_state_dict(ckpt.get("model", ckpt), strict=False)`.<br>3. Load frames with `load_and_preprocess_images(paths, mode="crop", image_size=518, patch_size=14)`.<br>4. Run `inference_streaming(images, num_scale_frames=8, keyframe_interval=1, output_device=None)` or `inference_windowed(images, window_size, overlap_size, overlap_keyframes, num_scale_frames, keyframe_interval, output_device)` under `torch.autocast("cuda", dtype=torch.bfloat16)`.<br>5. Decode with `pose_encoding_to_extri_intri(pred["pose_enc"], images.shape[-2:])`. | Verified (code reading) | [2] |
| 23 | Live use: the model is causal, and the demo warm-up feeds one frame per `forward()` call with a persistent KV cache. The repo ships no live-camera or ROS entry point, and `inference_streaming` expects all frames loaded up front. Writing a live adapter is feasible. | Verified (mechanism) / Inference (adapter) | [2][1] |
| 24 | It needs an NVIDIA GPU with CUDA. FlashInfer compiles its CUDA kernels on first use, and PyTorch's built-in SDPA attention is the fallback. Without CUDA the code falls back to CPU in fp32, but CPU speed is not documented. | Verified / Unknown (CPU) | [1][2] |
| 25 | About 20 FPS on an H800 and 12 FPS on an RTX 4090 at 518×378, with a 64-frame window and 8 anchors. | Reported (authors) | [4] |
| 26 | GPU memory: 13.28 GB with the 64-frame window, against 36.06 GB with full attention (paper ablation). Options for less memory: `--offload_to_cpu`, `--num_scale_frames 2`, `--camera_num_iterations 1`. The README links a third-party RTX 4060 8 GB fork, which I did not check. | Reported (authors) | [4][1] |
| 27 | Street-scale accuracy:<br>• KITTI odometry ATE 24.12 m in the paper, after Sim(3) alignment, against DROID-SLAM 129.34, VGGT-Long 31.89 and TTT3R 171.63<br>• 24.05 m in the repo benchmark at 504×280<br>Stated limits: no loop closure, no test-time optimisation, and extra drift at each window boundary in VO mode. | Reported (authors) | [4][3] |

## 5. Alternatives with the same role (video to 3D with camera poses)

✓ = documented in the sources I read. — = not documented there, which does not prove absence.

| Feature | LingBot-Map | MapAnything | Depth Anything 3 | ViPE |
|---|---|---|---|---|
| Works from RGB frames alone | ✓ | ✓ | ✓ | ✓ |
| Accepts known camera poses as input | — | ✓ | ✓ | — |
| Accepts known intrinsics as input | — | ✓ | — | ✓ |
| Metric-scale output | — | ✓ | ✓ | ✓ |
| Metric multi-view weights under a commercial-use licence | — | ✓ | — | — |
| Long-video mode with bounded memory | ✓ | — | ✓ | ✓ |
| Command-line tool writes result files | ✓ | ✓ | ✓ | ✓ |
| Code under Apache-2.0 | ✓ | ✓ | ✓ | ✓ |

Notes on the table:
- **Depth Anything 3 (DA3):** metric output comes only from the Nested model, which is CC BY-NC 4.0 (non-commercial). `DA3METRIC-LARGE` is Apache-2.0 but estimates depth from a single image.
- **ViPE:** the code is Apache-2.0, but parts it bundles or downloads carry non-commercial terms.

**MapAnything** (Meta; arXiv 2025-09-16) [7][8]
- **Input:** an image list or folder. Each view can also take intrinsics or ray directions, `depth_z`, a camera-to-world pose (OpenCV 4×4, or quaternion + translation) and an `is_metric_scale` flag. The first view is the reference. A script also reads a COLMAP folder.
- **Output, per view:** `pts3d` (world), `pts3d_cam`, `depth_z`, `depth_along_ray`, `intrinsics`, `camera_poses` (camera-to-world 4×4, OpenCV), `cam_trans`, `cam_quats`, `conf`, `mask`, `metric_scaling_factor`. Scripts export GLB or COLMAP.
- **Scale and mode:** metric. Offline: all views are processed together, up to about 2,000 views on 140 GB in memory-efficient mode.
- **Run:**
  - `MapAnything.from_pretrained("facebook/map-anything-apache").infer(views, memory_efficient_inference=True, use_amp=True, amp_dtype="bf16")`
  - `python scripts/demo_images_only_inference.py --image_folder DIR --save_glb --output_path out.glb --apache`
- **Weights:** `facebook/map-anything` is CC-BY-NC 4.0; `facebook/map-anything-apache` is Apache-2.0, labelled "For Commercial Use".

**Depth Anything 3** (ByteDance Seed; arXiv 2025-11-13) [9][10]
- **Input:** an image list or a video (`da3 video --fps`). Camera poses can be given as an optional input (pose-conditioned depth).
- **Output:**
  - Arrays: `depth` [N,H,W], `conf`, `extrinsics` [N,3,4] ("opencv w2c or colmap format"), `intrinsics` [N,3,3].
  - Exports: glb, npz, ply, depth images and 3DGS (3D Gaussian splatting) video.
- **Scale:**
  - The Nested model's output "is already in meters".
  - `DA3METRIC-LARGE` (one image at a time): metres = focal × output / 300.
- **Long video:** `python da3_streaming.py --image_dir DIR --config ... --output_dir OUT`.
  - Processes chunks of 120 frames with 60 overlapping, with loop closure.
  - Downloads `DA3NESTED-GIANT-LARGE-1.1` by default.
  - Writes `camera_poses.txt` (one extrinsic per line; the direction is not stated), `intrinsic.txt` (fx fy cx cy) and `pcd/combined_pcd.ply`.
  - Peak GPU memory 11.5–15.9 GB on KITTI at 504×154; about 10 FPS on an A100.
- **Weights:** Nested, Giant and Large are CC BY-NC 4.0. Base, Small, Metric-Large and Mono-Large are Apache-2.0.

**ViPE** (NVIDIA; arXiv 2025-08-12) [11][12]
- **Input:** an MP4 or a frame folder (`--image-dir`). Handles pinhole, wide-angle and 360° footage. It estimates intrinsics itself; a known K is optional in MetricTrail.
- **Output:**
  - `pose/<name>.npz`: `data` is N×4×4 OpenCV camera-to-world; `inds` holds the frame ids.
  - `intrinsics/<name>.npz`: `data` is N×4 (fx, fy, cx, cy).
  - `depth/<name>.zip`: one EXR file per frame.
  - `rgb/<name>.mp4`.
  - MetricTrail also exports a `.ply` point cloud, and a script converts output to COLMAP.
- **Scale and long video:** "near-metric" depth. MetricTrail tracks "with metric scale". `pose_only_long` (added 2026-09) and MetricTrail (added 2026-11) handle long videos with bounded memory.
- **Run:** `pip install nvidia-vipe`, then `vipe infer VIDEO.mp4 -o OUT [-p default|pose_only_long|dav3|wide_angle|panorama]`, or `python run.py pipeline=metrictrail streams.base_path=...`. GPU needs: Unknown, not stated in the README or usage docs.
- **Licence:** NVIDIA's own code is Apache-2.0. Bundled Unik3D is BY-NC-SA 4.0. MetricTrail weights are planned under an NVIDIA non-commercial licence. Downloaded third-party models keep their own terms.

The paper also compares against VGGT-Long, StreamVGGT, TTT3R, DROID-SLAM and MegaSaM [4]. I did not profile them.

## 6. What this means for the slot (Inference)

- **Inputs:** ordered RGB frames, plus optional intrinsics and GNSS/IMU poses. LingBot-Map ignores the optional parts. MapAnything accepts both, and ViPE's MetricTrail accepts known intrinsics. (From 8 and §5.)
- **Outputs the adapter should standardise:**
  - a camera-to-world 4×4 pose per frame, OpenCV axes
  - K at the model's output resolution
  - z-depth and confidence at that resolution
  - the resize/crop map back to source pixels
  - a `scale_kind` field (metric or normalized)
  - the checkpoint hash

  Invert DA3's world-to-camera extrinsics, and LingBot-Map's saved `extrinsic`, back to camera-to-world. (From 13–18.)
- **Metric units:** LingBot-Map needs a scale step before defects are measured. Options: Sim(3)-align its trajectory to GNSS/RTK positions; scale its depth with a metric model such as `DA3METRIC-LARGE` (Apache-2.0); or use known road-marking sizes. Geo-referencing should come from GNSS, because drift on KITTI is about 24 m. (From 16 and 27.)
- **Resolution:** assuming a lens of about 70°, a 518-px depth map has one pixel per about 1.4 cm at 5 m and about 2.7 cm at 10 m (2·d·tan 35° / 518). Crack width therefore needs the full-resolution images. The 3D output suits locating and sizing larger defects. (From 10.)
- **Practical settings:**
  - Use the NPZ or Python outputs, not the GLB. (19)
  - Pin a commit and the checkpoint hash. (3, 7)
  - Use windowed mode for drives longer than about 3,000 frames. (12)
  - Test both `lingbot-map.pt` and `lingbot-map-long.pt`; see Conflicts.

## Conflicts

- **`--offload_to_cpu` default:** the README (commit b9dd1b1, 2026-10-14) and the flag's own help text say "on by default", but the code sets `default=False`. I weight the code, because that is what runs. [1][2]
- **Long-sequence threshold:** the README section title says windowed mode is "for long sequences, >3000 frames", and the `demo.py` docstring says ">500 frames". The paper (v3, 2026-09-08) says Direct mode is stable up to about 3,000 frames. I weight the paper and README. [1][2][4]
- **Checkpoints:**
  - The Hugging Face model card (last modified 2026-10-26) lists `lingbot-map-long` as "better suited for long sequences and large scale scenes" and uses it in its examples.
  - The GitHub README (2026-10-14) lists only `lingbot-map` and `-stage1`, and says a stronger long-sequence model is "coming soon".

  Unresolved: both `.pt` files are on Hugging Face, with different hashes. [1][5]
- **Headline numbers:**
  - Press release (2026-04-16): Oxford Spires ATE 6.42 m, ETH3D F1 98.98.
  - Paper v3 (2026-09-08): Oxford Spires ATE 5.37 m.
  - Repo benchmark, using its own pipeline: 5.374 m and ETH3D F1 86.80.

  I weight the newer paper and repo; all are the authors' own figures. [6][4][3]
- **Pose helpers:** commits on 2026-10-10 and 2026-10-14 corrected the pose-convention comments. `GCTBase._unproject_depth_to_world` still inverts the decoded pose as if it were world-to-camera. I found no call to it in the files I read (Inference: it is unused). Use `pose_encoding_to_extri_intri` (camera-to-world) instead. [2]

## What would change this answer

- Robbyant releasing a metric-scale checkpoint, or stating a separate licence for the weights.
- A test run on the user's own street footage. That would give real GPU memory, FPS and drift; I did not run one.

## Open questions

- **Exact world origin:** I checked the README, the demo and batch code, and the paper's anchor-context section; none says which camera is the identity.
- **Commercial use of the weights:** only the repo-wide Apache-2.0 statement exists, and the model card has no licence tag. If the app is commercial, confirm with Robbyant.
- **Running on CPU or on a GPU under 8 GB:** the README only links a third-party fork.
- **ViPE's GPU needs, and the pose direction in DA3-Streaming's `camera_poses.txt`:** not stated in the docs I read.

## Sources

[1] *LingBot-Map: Geometric Context Transformer for Streaming 3D Reconstruction*, README.md. Robbyant (GitHub). Repo created 2026-04-15; read at commit b9dd1b1 (2026-10-14). Accessed 2026-11-14. https://github.com/Robbyant/lingbot-map
[2] Source code in the same repo and commit: `demo.py`, `demo_render/batch_demo.py`, `lingbot_map/models/{gct_base,gct_stream,gct_stream_window}.py`, `lingbot_map/utils/{pose_enc,rotation,load_fn,geometry}.py`, `lingbot_map/vis/glb_export.py`, `benchmark/methods/lingbot_map.py`, `pyproject.toml`, `LICENSE.txt`. Accessed 2026-11-14. https://github.com/Robbyant/lingbot-map/tree/b9dd1b1de535e6d36e777fb42b8433c781bfd783
[3] `benchmark/README.md`, same repo and commit. Accessed 2026-11-14. https://github.com/Robbyant/lingbot-map/blob/b9dd1b1de535e6d36e777fb42b8433c781bfd783/benchmark/README.md
[4] Chen, L.-Z. et al. *LingBot-Map: Geometric Context Transformer for Streaming 3D Reconstruction*. arXiv:2604.14141. v1 published 2026-04-15; v3 (2026-09-08) read. Accessed 2026-11-14. https://arxiv.org/abs/2604.14141
[5] *robbyant/lingbot-map* model card and file list. Hugging Face (Robbyant). Created 2026-04-16; last modified 2026-10-26. Accessed 2026-11-14. https://huggingface.co/robbyant/lingbot-map
[6] *Ant Group's Robbyant Unveils LingBot-Map: A Streaming 3D Reconstruction Model for Real-Time Spatial Understanding*. Ant Group via Business Wire. No date shown on the page; the URL encodes 2026-04-16. Accessed 2026-11-14. https://www.businesswire.com/news/home/20260416714351/en/Ant-Groups-Robbyant-Unveils-LingBot-Map-A-Streaming-3D-Reconstruction-Model-for-Real-Time-Spatial-Understanding
[7] *MapAnything*, README.md. Meta / facebookresearch (GitHub). Latest commit 3d10cf7 (2026-08-07). Accessed 2026-11-14. https://github.com/facebookresearch/map-anything
[8] *MapAnything: Universal Feed-Forward Metric 3D Reconstruction*. arXiv:2509.13414. Published 2025-09-16, updated 2026-01-23; arXiv record only. Accessed 2026-11-14. https://arxiv.org/abs/2509.13414
[9] *Depth Anything 3*: README.md, `da3_streaming/README.md`, `da3_streaming/scripts/download_weights.sh`, `da3_streaming/configs/base_config.yaml`. ByteDance Seed (GitHub). Latest commit 3d835ec (2026-07-27). Accessed 2026-11-14. https://github.com/ByteDance-Seed/Depth-Anything-3
[10] *Depth Anything 3: Recovering the Visual Space from Any Views*. arXiv:2511.10647. Published 2025-11-13; arXiv record only. Accessed 2026-11-14. https://arxiv.org/abs/2511.10647
[11] *ViPE*: README.md, `docs/usage.md`, `docs/metrictrail.md`, `vipe/utils/io.py`. NVIDIA nv-tlabs (GitHub). Latest commit ead2e00 (2026-11-05). Accessed 2026-11-14. https://github.com/nv-tlabs/vipe
[12] *ViPE: Video Pose Engine for 3D Geometric Perception*. arXiv:2508.10934. Published 2025-08-12; arXiv record only. Accessed 2026-11-14. https://arxiv.org/abs/2508.10934

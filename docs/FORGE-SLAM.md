# FORGE SLAM: Multi-Modal LiDAR-Inertial-Visual-Thermal SLAM & Radiometric 3D Inspection for iScale

*   **Author:** zenmastercat
*   **Status:** Approved
*   **Date:** 2026-11-24

--------------------------------------------------------------------------------

## Overview

**FORGE SLAM** (`civil/forge/` and decoder plugin `forge_slam`) is a metric multi-sensor Simultaneous Localization and Mapping (SLAM) and radiometric 3D surface reconstruction pipeline built into **iScale** (`civil-scan`, Apache-2.0 license). It fuses 3D LiDAR scans, 6-axis/9-axis Inertial Measurement Unit (IMU) streams, RGB camera frames, and radiometric Long-Wave Infrared (LWIR) thermal camera frames into a gravity-aligned, loop-closed, metric 3D road reconstruction (`civil.pointcloud.Reconstruction`) with per-point physical temperatures in degrees Celsius (`temperatures_c: float32`) and keyframe-anchored 3D Gaussian Splats (`splats.npz`).

The existing monocular phone-video workflow (`pothole_video` -> `lingbot_clip` in [`docs/VIDEO_PIPELINE.md`](VIDEO_PIPELINE.md) and [`docs/SCENE_SCALE.md`](SCENE_SCALE.md)) remains untouched. FORGE SLAM registers as a new decoder (`forge_slam`) in `civil/decoders/__init__.py` so its metric output flows directly through `civil.pipeline.finish()` -> `civil.align.align()` -> `civil.analysis.analyze()` to produce metric pothole depth, area, volume, Thailand Department of Highways (DOH) materials bills (`civil/materials.py`), and an opt-in radiometric thermal evidence panel (`panel="thermal"`) in the 3D finding verification modal (`civil/check3d.py` and `static/check3d.js`).

## The Problem

iScale's current 3D reconstruction path relies on monocular drive video decoded by LingBot-Map (`civil/decoders/lingbot_clip.py`). While practical for dashcams and phones, monocular reconstruction has four fundamental limitations for engineering-grade road surveys:

1.  **Scale Ambiguity & Elevation Drift:** Without RTK-GPS, monocular 3D clips are only up-to-scale (relying on a guessed camera height or manual taps on reference objects via `civil/scene_scale.py` / `civil/measure.py`) and accumulate vertical drift over multi-hundred-meter drives.
2.  **Ghosting from Moving Traffic:** Passing cars, motorbikes, and pedestrians leave "ghost" point clouds across the road surface that can trigger false surface anomalies or obscure pavement defects.
3.  **Loop Drift on Multi-Block Surveys:** Without place recognition and pose-graph optimization, long street surveys revisiting an intersection drift apart by meters, preventing consistent baseline-vs-repair comparison (`civil/verify.py`).
4.  **Unbounded Memory & No Subsurface/Thermal Sensing:** Accumulating millions of dense 3D points in RAM exceeds workstation memory on long routes, and RGB-only cameras cannot detect thermal subsurface anomalies (delamination, moisture pockets beneath asphalt, utility steam/water leaks, or fresh patch temperature differentials).

FORGE SLAM solves these four problems by combining a 15-DOF Error-State Kalman Filter LiDAR-Inertial Odometry (ESKF LIO) front end, ground-protected multi-keyframe dynamic object removal, Scan-Context + Generalized ICP (`small_gicp`) loop closure with GTSAM (`gtsam.ISAM2`) factor-graph optimization, a bounded-RAM spatial tile manager (`RAM <-> SSD` hot-swap), and calibrated RGB + radiometric thermal (°C) point-cloud registration and 3D Gaussian Splatting.

## Goals

*   **G1 — Metric ESKF LIO Front End (< 1.5% trajectory drift before loop closure):** Implement a 15-DOF Error-State Kalman Filter (`civil/forge/eskf_lio.py`) fusing IMU strapdown integration (100–400 Hz) with motion-deskewed 3D LiDAR point-to-plane measurement updates (10–20 Hz), outputting gravity-aligned metric poses and covariance health telemetry.
*   **G2 — Ground-Protected Dynamic Object Removal (>= 85% dynamic ghost removal, < 2% static road loss):** Filter moving vehicles and pedestrians across keyframes (`civil/forge/dynamic_filter.py`) while protecting negative-relief road depressions (2–15 cm potholes) from grazing-angle ray erosion, retaining an explicit boolean `dynamic_mask` (`(N,) bool`) for audit.
*   **G3 — High-Precision Loop Closure & GTSAM Factor-Graph Optimization (0 false-positive loop closures [100% precision] across evaluated benchmark sequences, >= 40% ATE reduction on loop sequences):** Combine Scan-Context polar BEV descriptors (`civil/forge/loop_closure.py`) and `small_gicp` multi-threaded G-ICP verification with GTSAM `ISAM2` / `NonlinearFactorGraph` (`civil/forge/pose_graph.py`) using robust Cauchy/Huber noise models.
*   **G4 — Bounded-RAM Spatial Tile Memory (`RAM <-> SSD` LRU Hot-Swap):** Maintain active map tiles in a spatial grid/octree (`civil/forge/memory.py`) with configurable `max_ram_bytes`, evicting cold tiles to `work_dir/forge_tiles/*.npz` in immutable keyframe-local coordinates so loop closures require zero SSD rewrite I/O.
*   **G5 — Radiometric Thermal (°C) + RGB Registration & 3D Gaussian Splatting:** Project calibrated RGB and radiometric LWIR thermal frames (using FLIR Planck-law `Raw2Celsius` or linear Kelvin/Celsius calibration with z-buffer occlusion testing) onto map points (`temperatures_c: float32` in °C) and optimize keyframe-anchored RGB+Thermal 3D Gaussian Splats (`civil/forge/gsplat.py`) within a strict VRAM budget (`free_gpu_gb()` check) that never starves `iscale-worker` or Ollama on the shared 16 GB RTX 5080.
*   **G6 — Backward-Compatible iScale Pipeline & UI Integration:** Output a backward-compatible `Reconstruction` (`meta["metric"] = True`, `temperatures_c`) that runs through `civil/pipeline.py` and `civil/analysis/` to produce pothole depth/area/volume/cost findings and renders an Inferno-colormapped `panel="thermal"` in `civil/check3d.py` + `static/check3d.js`.

## Non-Goals

*   **NG1:** Replacing or altering the existing phone-video decoder (`pothole_video` -> `lingbot_clip`), reference-object measurement (`civil/measure.py`), or scene-scale calibration (`civil/scene_scale.py`).
*   **NG2:** Real-time hardware UDP socket drivers for live physical LiDAR/thermal sensors; FORGE SLAM processes recorded dataset folders and ROS1/ROS2 bag files (`.bag`, `.mcap`, `.db3`).
*   **NG3:** Adding GPL-licensed dependencies (such as `evo`, GPL-3.0) to the Apache-2.0 `iScale` repository.
*   **NG4:** Requiring `gtsam`, `small_gicp`, `rosbags`, or `torch` to be installed for core `civil serve` startup or non-FORGE surveys.

## Open Questions

All architectural questions have been resolved via user specification and EGM Goldfish review:

*   *Resolved — License Compatibility of Third-Party Libraries:* `gtsam==4.3.0` (BSD-2/3-Clause), `small-gicp==1.0.1` (MIT), `rosbags==0.11.10` (Apache-2.0), `scipy==1.18.1` (BSD-3-Clause), and `torch` (BSD-3-Clause) are all permissive and compatible with iScale's Apache-2.0 license. `evo` (GPL-3.0) is excluded and replaced by an Apache-2.0 trajectory evaluator in `civil/forge/eval.py` reusing `civil/align.py::umeyama`.
*   *Resolved — Coexistence on the Shared 16 GB RTX 5080:* `civil/forge/gsplat.py` reuses `free_gpu_gb()` from `civil/decoders/lingbot_clip.py`, enforces a configurable `min_free_gpu_gb` (default `4.0 GB`) and `max_gaussians` cap (`250,000`), and falls back cleanly to CPU/NumPy execution if the GPU is occupied by `iscale-worker` or Ollama.

## Critical User Journeys (CUJs)

### CUJ 1: Pre-Flight Inspection & CLI Execution on a Multi-Sensor Sequence

*   **Given**: An engineer has a multi-sensor road sequence directory or ROS bag (`input_dir`) containing LiDAR scans, IMU measurements, RGB frames, radiometric thermal frames, and `calibration.json` (or M2DGR/KAIST MS2 format files).
*   **When**: The engineer runs `civil forge check <input_dir>` followed by `civil forge run <input_dir> --out <work_dir>` (or `--project <pid> --name "Thermal LiDAR Survey"`).
*   **Then**:
    1. `civil forge check` validates stream presence, timestamp overlap, extrinsic matrices (`T_lidar_imu`, `T_lidar_rgb`, `T_lidar_thermal`), and thermal radiometric metadata, printing a JSON diagnostic summary and exiting with code `0` (or `1` on missing/invalid calibration).
    2. `civil forge run` executes the 6-stage FORGE SLAM pipeline, writes `recon.npz` (with `points`, `colors`, `poses`, `times`, `temperatures_c`, and `meta["forge_slam"]`), `dynamic_mask.npz`, `splats.npz`, and `forge_diagnostics.json`, and (when `--project <pid>` is passed) registers and analyzes the survey inside iScale.

### CUJ 2: Viewing Metric Pothole Findings & Radiometric Thermal Evidence in the 3D Check Modal

*   **Given**: A completed `forge_slam` survey in iScale where `civil.analysis.analyze()` has detected a road surface defect (e.g., a 6.5 cm deep pothole with a localized thermal delta).
*   **When**: An engineer clicks **3D check** on the finding in the web UI (`static/check3d.js`), calling `GET /api/projects/{pid}/surveys/{sid}/findings/{fid}/check`.
*   **Then**:
    1. The response JSON includes `has_thermal: true`, `thermal_stats` (`{"min_c": float, "max_c": float, "mean_c": float, "road_ambient_c": float, "delta_c": float}`), and `images.thermal` alongside `images.top`, `images.height`, and `images.section`.
    2. Clicking the **Thermal (°C)** view renders the 480x514 Inferno-colormapped radiometric temperature map (`panel="thermal"`) with a degrees Celsius colour bar and finding outline, while surveys without thermal data (`demo`, `lingbot_clip`, `ply_import`) continue displaying the standard 3 panels without a thermal toggle.

### CUJ 3: Quantitative Benchmark Evaluation on Public Datasets (`civil forge eval`)

*   **Given**: Public dataset sequences in `~/Projects/iScale-datasets/` (`m2dgr/` with 100 Hz RTK/Leica ground truth and Velodyne VLP-32C / Handsfree IMU / PLUG 617 thermal calibration, plus `kaist_ms2/` road RGB + FLIR A65C radiometric thermal data).
*   **When**: The engineer runs `civil forge eval --datasets-dir ~/Projects/iScale-datasets --out docs/FORGE-RESULTS.md`.
*   **Then**: The evaluator runs FORGE SLAM across the benchmark sequences (comparing LIO-only vs. LIO + Loop Closure + GTSAM iSAM2, with and without dynamic filtering, and under forced RAM->SSD tile evictions), computes ATE/RPE, loop-closure precision/recall, ghosting reduction, RAM ceiling, frame latency, held-out splat PSNR/SSIM, and thermal registration RMSE (°C), and writes `docs/FORGE-RESULTS.md` and diagnostic figures in `docs/figures/`.

## Technical Plan (Architecture)

### 1. System Data Flow

```mermaid
flowchart TD
  subgraph Input["Multi-Sensor Input (Folder / ROS1 .bag / ROS2 .mcap .db3)"]
    LIDAR["3D LiDAR Scans<br/>(t, xyz, intensity, per-point dt)"]
    IMU["6/9-Axis IMU<br/>(t, gyro rad/s, accel m/s²)"]
    RGB["RGB Camera Frames<br/>(t, HxWx3 uint8, K_rgb, D_rgb)"]
    THERM["Radiometric Thermal Frames<br/>(t, HxW raw16 or float32 °C, K_thr, Planck R,B,F,O)"]
    CALIB["Extrinsics & Time Offsets<br/>(T_lidar_imu, T_lidar_rgb, T_lidar_thermal, dt_offset)"]
  end

  subgraph FORGE["civil/forge/ — 6-Stage FORGE SLAM Pipeline"]
    S1["1. ESKF LIO Front End (civil/forge/eskf_lio.py)<br/>15-DOF Nominal + Error-State KF · IMU Deskew · Point-to-Plane / Voxel G-ICP Update"]
    S2["2. Keyframe & Ground-Protected Dynamic Filter (civil/forge/dynamic_filter.py)<br/>Elevation Split (h > +0.15m Ray-Casting vs. [-0.40m, +0.15m] Pavement Band) · Audit Mask"]
    S3["3. Place Recognition & Loop Closure (civil/forge/loop_closure.py)<br/>Scan-Context (20x60 Polar BEV) · Ring-Key KD-Tree · small_gicp Verification & Chi² Gate"]
    S4["4. Factor-Graph Optimization (civil/forge/pose_graph.py)<br/>GTSAM iSAM2 (Pose3, Odometry, Cauchy/Huber Loop Factors, GPS Priors)"]
    S5["5. Spatial Tile Memory (civil/forge/memory.py)<br/>2D/3D Tile Grid · Keyframe-Local Storage · LRU RAM <-> SSD Hot-Swap (work_dir/forge_tiles/)"]
    S6["6. RGB + Radiometric Thermal & 3DGS (civil/forge/thermal_reg.py & gsplat.py)<br/>Planck Raw2Celsius · Z-Buffer Occlusion Culling · Keyframe-Anchored RGB+Thermal 3DGS"]
  end

  subgraph iScale["iScale Core Pipeline (civil/)"]
    REC["Reconstruction (civil/pointcloud.py)<br/>points (N,3) · colors (N,3) · temperatures_c (N,) °C · poses (K,4,4) · meta['metric']=True"]
    ALIGN["civil/align.py<br/>Preserves Gravity-Aligned Z & Metric Scale · Project-Origin ENU Placement"]
    ANALYZE["civil/analysis/<br/>25m Road Segments · Pothole Depth/Area/Volume · DOH Materials Bill"]
    CHECK3D["civil/check3d.py & static/check3d.js<br/>Top RGB · RdYlBu Height · Cross-Section · Inferno Thermal (°C) Panel"]
  end

  LIDAR & IMU & CALIB --> S1
  S1 -->|Deskewed Scan & T_w_b| S2
  S2 -->|Static Keyframe & dynamic_mask| S3
  S2 -->|Static Keyframe| S5
  S3 -->|Verified LoopConstraint| S4
  S1 -->|Odometry Factor| S4
  S4 -->|Updated Keyframe Poses {k: T_w_k}| S5
  S5 & RGB & THERM & CALIB --> S6
  S6 --> REC --> ALIGN --> ANALYZE --> CHECK3D
```

### 2. Coordinate Frames, State Representation & Time Synchronization

*   **Coordinate Frames:**
    *   $\mathcal{F}_W$: Local metric gravity-aligned world frame ($+X$ East/forward, $+Y$ North/left, $+Z$ parallel to gravity up $\mathbf{g} = [0, 0, -9.80665]^T\text{ m/s}^2$). Final placement into the iScale project's `(origin_lat, origin_lon)` ENU frame and ground-zeroing is delegated to `civil/align.py::align()`.
    *   $\mathcal{F}_B$ ($\mathcal{F}_{\text{IMU}}$): IMU body frame.
    *   $\mathcal{F}_L$: LiDAR sensor frame, related to body by calibrated extrinsic $\mathbf{T}_{BL} = (\mathbf{R}_{BL}, \mathbf{p}_{BL}) \in \text{SE}(3)$.
    *   $\mathcal{F}_C, \mathcal{F}_T$: RGB and Thermal optical frames (OpenCV convention: $+X$ right, $+Y$ down, $+Z$ forward), related to LiDAR by $\mathbf{T}_{CL}, \mathbf{T}_{TL} \in \text{SE}(3)$.
*   **15-DOF ESKF State (`eskf_lio.py`):**
    *   **Nominal State** $\mathbf{x} = (\mathbf{R}, \mathbf{p}, \mathbf{v}, \mathbf{b}_g, \mathbf{b}_a) \in \text{SO}(3) \times \mathbb{R}^{12}$: orientation $\mathbf{R}_{WB}$, position $\mathbf{p}_{WB}\text{ (m)}$, velocity $\mathbf{v}_W\text{ (m/s)}$, gyroscope bias $\mathbf{b}_g\text{ (rad/s)}$, accelerometer bias $\mathbf{b}_a\text{ (m/s}^2)$.
    *   **Error State** $\delta\mathbf{x} = [\delta\boldsymbol{\theta}^T, \delta\mathbf{p}^T, \delta\mathbf{v}^T, \delta\mathbf{b}_g^T, \delta\mathbf{b}_a^T]^T \in \mathbb{R}^{15}$ with covariance $\mathbf{P} \in \mathbb{R}^{15\times 15}$.
    *   **Time Synchronization & Deskewing:** Every sensor timestamp is shifted by its calibrated offset $t_{\text{corr}} = t_{\text{raw}} + \Delta t_{\text{calib}}$. Within each LiDAR sweep $[t_0, t_1]$, high-rate IMU strapdown integration produces intermediate states $\{\mathbf{T}_{WB}(t_j)\}$, transforming every point $\mathbf{p}_i$ measured at relative timestamp $\tau_i \in [t_0, t_1]$ into the sweep-end frame $\mathcal{F}_L(t_1)$:
        $$\mathbf{p}_i(t_1) = \mathbf{T}_{BL}^{-1}\,\mathbf{T}_{WB}(t_1)^{-1}\,\mathbf{T}_{WB}(\tau_i)\,\mathbf{T}_{BL}\,\mathbf{p}_i(\tau_i)$$
    *   **Measurement Update:** Deskewed scan points are registered against the local active voxel submap using point-to-plane residuals $r_i = \mathbf{n}_i^T (\mathbf{R}_{WB}\mathbf{p}_i^B + \mathbf{p}_{WB} - \mathbf{q}_i)$ (accelerated via `small_gicp` multi-threaded C++ correspondence/registration and `scipy.spatial.cKDTree` plane normals) with Joseph-form covariance update $\mathbf{P} \leftarrow (\mathbf{I} - \mathbf{K}\mathbf{H})\mathbf{P}(\mathbf{I} - \mathbf{K}\mathbf{H})^T + \mathbf{K}\mathbf{R}\mathbf{K}^T$ to guarantee symmetry and positive-definiteness.

### 3. Ground-Protected Temporal Dynamic Object Removal (`dynamic_filter.py`)

*   **Keyframe Gating:** A new keyframe $k$ is created when translation from the previous keyframe exceeds $\Delta d_{\text{kf}} = 1.0\text{ m}$ or rotation exceeds $\Delta \theta_{\text{kf}} = 10^\circ$.
*   **Elevation-Split Visibility & Lower-Envelope Filter:**
    1. Fit the local road plane $z_{\text{road}}(x, y)$ within a $12.0\text{ m}$ horizontal radius of the keyframe pose by reusing `civil/align.py::ransac_plane` on points below sensor elevation, verifying that the plane normal is within $15^\circ$ of gravity $+Z$ (falling back to the keyframe's gravity-leveled floor $z_k - h_{\text{sensor}}$ if vertical curb walls dominate).
    2. **Above-Road Band ($h = z - z_{\text{road}} > +0.15\text{ m}$):** Construct a spherical range image $(\phi, \theta)$ of resolution $(N_{\text{az}} \times N_{\text{el}}) = (180 \times 32)$ across a sliding window of $W = 7$ keyframes. A point at range $r_A$ in keyframe $A$ is flagged as dynamic (`dynamic_mask[i] = True`) if at least $M_{\text{free}} = 2$ other keyframes in the window observe a return along the same angular bin at range $r_B > r_A + 0.30\text{ m}$ (free-space violation: the ray passed *through* the volume occupied by $\mathbf{p}_i$) OR if the point's 20 cm 3D voxel is occupied in only 1 keyframe while at least 2 keyframes' sensor frustums traverse that voxel.
    3. **Pavement Protection Band ($h \in [-0.40\text{ m}, +0.15\text{ m}]$):**
       - **Negative-relief and flush pavement points ($h \in [-0.40\text{ m}, +0.02\text{ m}]$):** Potholes and road surface points are protected from spherical free-space ray-casting and are flagged as dynamic only if they lie inside the 2D horizontal $(x, y)$ contact-patch footprint (expanded by 15 cm) of an identified above-ground dynamic cluster AND exceed the multi-keyframe 25th-percentile local surface elevation in that $10\text{ cm} \times 10\text{ cm}$ cell by $> +0.04\text{ m}$.
       - **Positive pavement-band protrusions ($h \in (+0.02\text{ m}, +0.15\text{ m}]$):** Flagged as dynamic if they lie inside the 2D horizontal $(x, y)$ footprint of an above-ground dynamic cluster (removing vehicle tires and pedestrian feet) OR if their elevation $z$ exceeds the multi-keyframe 25th-percentile local surface elevation in the same $10\text{ cm} \times 10\text{ cm}$ cell by $> +0.08\text{ m}$.

### 4. Keyframe Place Recognition & GTSAM Factor-Graph Optimization (`loop_closure.py` & `pose_graph.py`)

*   **Scan-Context Descriptor (`loop_closure.py`):**
    *   Each keyframe point cloud (within radius $R_{\max} = 40\text{ m}$, leveled by applying the keyframe's estimated roll and pitch $(\phi_k, \theta_k)$ from $\mathbf{R}_{WB}$ while keeping keyframe origin and yaw $= 0$) is partitioned into $N_r = 20$ radial rings and $N_s = 60$ azimuthal sectors. Each cell stores the maximum height $z_{\max} + h_{\text{sensor}}$.
    *   The $N_r$-dimensional ring key (mean occupancy per ring) is indexed in a `scipy.spatial.cKDTree` over historical keyframes separated by at least $\Delta t_{\text{min}} = 25\text{ s}$ and cumulative path distance $\ge 15\text{ m}$.
    *   Top-$K = 5$ ring-key candidates are scored by column-shifted cosine distance $d_{\text{sc}}(I_q, I_c) \in [0, 1]$, providing both the similarity score and initial yaw alignment $\Delta \psi_0$.
*   **Geometric Verification & False-Positive Guard:**
    *   Candidates with $d_{\text{sc}} \le \tau_{\text{sc}}$ (default `0.35`) are aligned using `small_gicp.align` (G-ICP with initial guess from $\Delta \psi_0$).
    *   A loop candidate is **ACCEPTED** only if all four gates pass:
        1. `converged == True`
        2. `inlier_ratio >= 0.45` (fraction of source points with correspondence error $< 0.5\text{ m}$)
        3. `rmse <= 0.35 m`
        4. Step displacement consistency check ($\|\Delta \mathbf{p}_{\text{gicp}}\| \le 0.35 \cdot d_{\text{path}}$).
    *   Every candidate evaluation (accepted or rejected with exact rejection code) is appended to `loop_closure_audit`.
*   **GTSAM iSAM2 Pose Graph (`pose_graph.py`):**
    *   Uses `gtsam.ISAM2` (with `ISAM2Params` relinearize threshold `0.05`, relinearize skip `1`) and `gtsam.NonlinearFactorGraph`.
    *   Keyframe poses $X_k = \text{Pose3}(\mathbf{R}_k, \mathbf{p}_k)$ are constrained by:
        - Initial prior `PriorFactorPose3` on $X_0$ (`diagonal([1e-4]*6)`).
        - Sequential ESKF LIO odometry factors `BetweenFactorPose3(X_{k-1}, X_k, T_{k-1,k}, odom_noise)`.
        - Verified loop-closure factors `BetweenFactorPose3(X_i, X_j, T_{i,j}^{\text{gicp}}, robust_cauchy_noise)` wrapped in `gtsam.noiseModel.Robust.Create(gtsam.noiseModel.mEstimator.Cauchy.Create(1.0), base_noise)`.
        - Optional GPS position priors (`Pose3` translation prior when RTK/GPS track is present).

### 5. Spatial Tile Memory with LRU `RAM <-> SSD` Hot-Swap (`memory.py`)

*   `SpatialTileMemory` partitions the horizontal plane into square spatial tiles of side $L_{\text{tile}} = 20.0\text{ m}$ indexed by integer grid coordinates $(i_x, i_y) = (\lfloor x / L_{\text{tile}} \rfloor, \lfloor y / L_{\text{tile}} \rfloor)$ (with a 3D octree/voxel subdivision inside each tile).
*   **Keyframe-Local Coordinate Invariant:** Inside each tile, point chunks are stored as `(keyframe_id, points_local_f32, colors_u8, temps_c_f32)` in the immutable local frame $\mathcal{F}_k$ of the originating keyframe $k$, while `SpatialTileMemory` maintains the active pose dictionary `{k: T_w_k}` in RAM.
*   **Synchronous LRU Hot-Swap & Per-Tile Export Downsampling:**
    *   `SpatialTileMemory` tracks exact resident byte count `active_ram_bytes` against `max_ram_bytes` (default `512 MB` in production, configurable down to `64 KB` in unit/evaluation tests to force deterministic SSD evictions).
    *   When inserting points or paging in a tile causes `active_ram_bytes > max_ram_bytes`, the least-recently-used tile is serialized atomically to `work_dir / "forge_tiles" / f"tile_{ix}_{iy}.npz"` and evicted from RAM (`evictions_to_ssd_total += 1`).
    *   When a tile on SSD is queried or updated, it is transparently reloaded into RAM (`reloads_from_ssd_total += 1`).
    *   When `update_poses({k: T_w_k_new})` is called after GTSAM loop closure, only the in-RAM pose dictionary `{k: T_w_k}` is updated—**zero SSD tiles are read or rewritten during loop closure**.
    *   During `export_world_cloud()`, each tile is transformed to world coordinates and voxel-downsampled via `civil/pointcloud.py::voxel_downsample` *per tile* before concatenation so peak export RAM never exceeds the 2.0 GB budget.

### 6. Radiometric Thermal (°C) + RGB Registration & 3D Gaussian Splatting (`thermal_reg.py` & `gsplat.py`)

*   **Radiometric Calibration (`thermal_reg.py`):**
    *   Supports three radiometric thermal input encodings:
        1. **FLIR Planck Raw 14/16-bit flux** (`encoding="flir_raw"`): Converts raw sensor counts $S$ to degrees Celsius using the Planck calibration law (matching KAIST MS² FLIR A65C parameters $R = 380747, B = 1428, F = 1.0, O = -88.539$, configurable per camera):
           $$T_{^\circ\text{C}}(S) = \frac{B}{\ln\!\left(\frac{R}{\max(S - O, 1.0)} + F\right)} - 273.15$$
        2. **Centikelvin / Decikelvin 16-bit integer** (`encoding="centikelvin"`, e.g. `uint16` where $T_{^\circ\text{C}} = S \times 0.01 - 273.15$).
        3. **Direct float32 Celsius** (`encoding="celsius_f32"`).
    *   **Non-Radiometric 8-Bit Rejection:** If a thermal image is 8-bit (`uint8`) without explicit linear scale/offset calibration (`temp_min_c`, `temp_max_c`) in `calibration.json`, `thermal_reg.py` raises a `ValueError` specifying the missing calibration keys (`temp_min_c`, `temp_max_c`).
    *   **Time-Synchronized Z-Buffered Projection:** For each keyframe $k$ at timestamp $t_k$, the nearest thermal frame $t_T$ within $|\Delta t| \le 0.05\text{ s}$ is pose-interpolated via $\text{SE}(3)$ geodesic interpolation between adjacent ESKF/GTSAM poses. Map points in the camera frustum are projected via distorted pinhole intrinsics $(\mathbf{K}_T, \mathbf{D}_T)$, filtered by a per-pixel depth z-buffer (margin $\delta z = 0.15\text{ m}$ so foreground obstacles never project their temperature onto background road asphalt), and fused across views via inverse-distance weighted averaging into `temperatures_c: (N,) float32`.
*   **Keyframe-Anchored RGB + Thermal 3D Gaussian Splatting (`gsplat.py`):**
    *   Initializes 3D Gaussians $\mathcal{G}_i = (\boldsymbol{\mu}_i \in \mathbb{R}^3, \mathbf{s}_i \in \mathbb{R}^3, \mathbf{q}_i \in \mathbb{H}, \alpha_i \in (0,1), \mathbf{c}_i \in [0,1]^3, T_i \in \mathbb{R})$ directly from the downsampled static keyframe surface cloud, with scales initialized from local $k$-NN spacing and temperature $T_i$ initialized as an **unactivated view-independent `float32` scalar in °C**.
    *   Before allocating GPU tensors, checks `free_gpu_gb() >= min_free_gpu_gb` (default `4.0 GB`) and caps active Gaussians to `max_gaussians` (default `250,000`). Optimizes Gaussian colors $\mathbf{c}_i$, temperatures $T_i$, opacities $\alpha_i$, and scales $\mathbf{s}_i$ against keyframe RGB and radiometric thermal frames using a differentiable tile/splat rasterizer (PyTorch GPU when VRAM is available, vectorized NumPy/CPU fallback otherwise), and evaluates held-out view PSNR, SSIM, and thermal RMSE (°C).

### 7. Hardware & Compute Budget (Intel Core Ultra 9 285K, 30 GB RAM, RTX 5080 16 GB VRAM)

| Resource | System Capacity | Resident Consumers | FORGE SLAM Hard Ceiling | Enforcement Mechanism |
|---|---|---|---|---|
| **GPU VRAM** | 16.0 GB (RTX 5080) | Display (~1.2 GB), Ollama / `iscale-worker` (0–12 GB) | **<= 3.5 GB** (requires `>= 4.0 GB` free VRAM to start GPU 3DGS) | `free_gpu_gb()` check before GPU allocation; `max_gaussians <= 250,000`; automatic CPU fallback if GPU is busy |
| **System RAM** | 30.0 GB | Linux OS, FastAPI server, worker (~4–6 GB) | **<= 2.0 GB** for `SpatialTileMemory` + **<= 10M points** in exported `Reconstruction` | `SpatialTileMemory(max_ram_bytes=...)` LRU eviction to SSD + per-tile `voxel_downsample` before export concatenation |
| **CPU Threads** | 24 cores (8 P-cores `0–7`, 16 E-cores `8–23`) | Uvicorn HTTP event loop, ejabberd | **<= 8 threads** (`num_threads=8` in `small_gicp`) | Vectorized NumPy/SciPy + `small_gicp` 8-thread cap so Uvicorn stays responsive |
| **SSD Scratch** | Local NVMe (`work_dir/forge_tiles/`) | Survey `work/` directory | **<= 4.0 GB** per survey | Scoped context manager inside `work_dir / "forge_tiles"`, cleaned up with survey lifecycle |

## Alternatives Considered

### Alternative A: Importing `evo` (`evo==1.38.1`) for Trajectory Evaluation
*   **Pros**: Widely used CLI/library for SLAM trajectory ATE and RPE computation.
*   **Cons**: Licensed under **GPL-3.0**, which is incompatible with iScale's **Apache-2.0** license (`LICENSE`).
*   **Reason for Rejection**: Rejected by author: no GPL code may enter the Apache-2.0 repository. Instead, `civil/forge/eval.py` reuses `civil/align.py::umeyama` to compute exact $\text{SE}(3)$ ATE and $\Delta t$/$\Delta d$ RPE metrics directly in Apache-2.0 NumPy/SciPy code, verified by unit tests against analytical ground truth.

### Alternative B: Storing Spatial Tiles in World Coordinates on SSD
*   **Pros**: Points read from SSD are already in world coordinates without a $4\times 4$ matrix multiply.
*   **Cons**: Every GTSAM loop-closure update modifies hundreds of historical keyframe poses, forcing all evicted SSD tiles to be read back into RAM, transformed, and rewritten to SSD (severe disk thrashing).
*   **Reason for Rejection**: Rejected by author: storing point chunks inside each tile tagged by `keyframe_id` in immutable keyframe-local coordinates reduces loop-closure SSD I/O to zero while adding only a fast vectorized matrix multiply on tile load/export.

### Alternative C: Uniform Spherical Range-Image Ray-Casting Across All Elevations
*   **Pros**: Single ray-casting rule for the entire $360^\circ$ LiDAR scan.
*   **Cons**: At 3–15° grazing incidence on road surfaces, rays striking the recessed floor of a 3–10 cm pothole travel 15–60 cm farther than rays striking the near rim in other keyframes, causing free-space carving to erase the pothole rim or floor.
*   **Reason for Rejection**: Rejected by author: segmenting the cloud relative to the local road plane (`h > +0.15 m` for spherical ray-casting vs. `[-0.40 m, +0.15 m]` pavement protection band with footprint shadow + positive-spike filtering) removes vehicles and pedestrians while preserving >= 98% of negative-relief road defect points.

### Alternative D: Top-Level Eager Imports of `gtsam`, `small_gicp`, and `torch` in `civil/`
*   **Pros**: Slightly fewer lines of import code.
*   **Cons**: Breaks `civil serve` and `pytest` on lightweight web hosts (such as the CasaOS server) that offload 3D processing via `CIVIL_3D=remote` (`civil/worker.py`).
*   **Reason for Rejection**: Rejected by author: lazy imports inside `civil/forge/` and optional dependency declaration in `pyproject.toml` keep the core web server lightweight and backward-compatible.

--------------------------------------------------------------------------------

## Non-Functional Requirements

### Risks & Mitigations

1.  **ESKF Divergence & LiDAR Corridor Degeneracy:**
    *   *Risk:* In featureless corridors or during rapid angular saturation, point-to-plane ICP hessian eigenvalues along the forward axis can drop near zero or covariance $\lambda_{\max}(\mathbf{P}_{\text{pos}})$ can grow unbounded.
    *   *Mitigation:* `eskf_lio.py` monitors the point-to-plane normal matrix eigenvalues and $\lambda_{\max}(\mathbf{P}_{\text{pos}})$ at every scan. Degenerate directions ($\lambda < 10.0$) are projected out of the Kalman update; if $\lambda_{\max}(\mathbf{P}_{\text{pos}}) > 25.0\text{ m}^2$ or `np.isnan(P).any()`, `divergence_detected` is set in `forge_diagnostics.json`, covariance is reset to a bounded diagonal prior, and velocity updates are damped so a single corrupted scan cannot explode the trajectory.
2.  **Steep Road Grades & High Curb Walls in Dynamic Filtering:**
    *   *Risk:* A naive global plane fit on a hilly street or narrow alley dominated by vertical walls can misidentify the road plane $z_{\text{road}}(x, y)$.
    *   *Mitigation:* `dynamic_filter.py` restricts `ransac_plane` to points within $12.0\text{ m}$ horizontally and below sensor height, and requires the fitted normal to lie within $15^\circ$ of gravity $+Z$ ($\cos\theta \ge \cos 15^\circ$); if the tilt check fails, it falls back to the gravity-aligned local floor plane at $z_k - h_{\text{sensor}}$.
3.  **Peak RAM During Multi-Tile Export:**
    *   *Risk:* Reloading dozens of evicted SSD tiles simultaneously during `export_world_cloud()` could spike RAM above the 2.0 GB budget.
    *   *Mitigation:* `SpatialTileMemory.export_world_cloud()` iterates one tile at a time, transforming chunks to world coordinates and applying `voxel_downsample` per tile before appending to the output buffer.

### Security, Observability & Rollback Compatibility

*   **Security & Input Validation:**
    *   All file paths inside dataset directories or configuration JSONs are validated against directory traversal (`Path.resolve().is_relative_to(input_dir.resolve())`).
    *   `Reconstruction.save()` and `load()` use `np.load(..., allow_pickle=False)` exclusively; all `forge_tiles/*.npz` files also enforce `allow_pickle=False`.
    *   Survey parameters passed to `POST /api/projects/{pid}/surveys` under `params["forge"]` are validated against `ForgeConfig` fields (`HTTPException(400)` on invalid types or unknown keys).
*   **Observability & Diagnostics (`forge_diagnostics.json`):**
    *   Every FORGE SLAM run writes `work_dir / "forge_diagnostics.json"` containing `timing_ms` (p50, p95, p99, total per stage), `eskf` (covariance trace, max eigenvalue, bias norms, `divergence_detected`), `dynamic_filter` (`input_points`, `removed_dynamic_points`, `removal_ratio`, `protected_road_points`), `loop_closure` (`candidates_evaluated`, `accepted_count`, `rejected_by_reason`, `audit_log`), `pose_graph` (`initial_error`, `final_error`, `error_reduction_pct`, `num_poses`, `num_factors`), `memory` (`max_ram_bytes`, `peak_ram_bytes`, `active_ram_tiles`, `ssd_evictions_total`, `ssd_reloads_total`, `hits_total`, `misses_total`), `thermal` (`registered_points`, `temp_min_c`, `temp_max_c`, `temp_mean_c`, `reprojection_rmse_c`), and `gsplat` (`backend`, `num_gaussians`, `heldout_psnr_db`, `heldout_ssim`, `thermal_mae_c`).
*   **Rollout & Rollback Compatibility:**
    *   `temperatures_c` is an optional array key in `recon.npz`. Because `Reconstruction.load()` in older commits reads only known keys from `np.load()`, `recon.npz` files written by FORGE SLAM remain loadable even if the server is rolled back.

### Additional Resources

*   [`README.md`](../README.md) — iScale architecture, API reference, and deployment overview.
*   [`docs/VIDEO_PIPELINE.md`](VIDEO_PIPELINE.md) — Existing phone-video -> LingBot-Map 3D clip pipeline.
*   [`docs/SCENE_SCALE.md`](SCENE_SCALE.md) — Scene-object scale calibration specification.
*   **Public Datasets & Licenses (`~/Projects/iScale-datasets/`):**
    1.  **M2DGR (`SJTU-ViSYS/M2DGR`):** **MIT License**. Velodyne VLP-32C 3D LiDAR (10 Hz), Handsfree A9 9-axis IMU (150 Hz), RealSense D435i RGB (`640x480`), PLUG 617 Thermal-Infrared (`640x512`, 25 Hz), and 100 Hz RTK-GNSS / Leica ground-truth trajectories (`gate_01`, `gate_02`, `gate_03`, `street_03`, `street_04`, `rotation_01`, `door_02`). Citation: *J. Yin et al., "M2DGR: A Multi-Sensor and Multi-Scenario SLAM Dataset for Ground Robots," IEEE RA-L, vol. 7, no. 2, pp. 2266–2273, 2022.*
    2.  **KAIST Multi-Spectral Driving (`UkcheolShin/MS2-MultiSpectralStereoDataset` & `Mini-KAIST-Multispectral`):** **MIT License / CC BY-NC-SA 3.0** (research/evaluation use). Outdoor road driving RGB + FLIR A65C radiometric thermal (`Raw2Celsius` Planck parameters $R=380747, B=1428, F=1, O=-88.539$) + stereo LiDAR + IMU calibration. Citation: *U. Shin, J. Park, and I. S. Kweon, "Deep Depth Estimation from Thermal Image," IEEE/CVF CVPR, 2023.*
*   **Libraries & Licenses:**
    *   `gtsam==4.3.0`: **BSD License** (Georgia Tech Borg Lab — Factor-graph optimization & `ISAM2`).
    *   `small-gicp==1.0.1`: **MIT License** (K. Koide, AIST — Multi-threaded C++ G-ICP & voxelmap registration).
    *   `rosbags==0.11.10`: **Apache-2.0 License** (Ternaris — Pure-Python ROS1 `.bag` and ROS2 `.mcap`/`.db3` reader).
    *   `scipy==1.18.1` & `numpy==2.3.5`: **BSD-3-Clause License** (KD-trees, spatial rotations, sparse linear algebra).
    *   `torch==2.14.1+cu130`: **BSD-3-Clause License** (Optional GPU acceleration for 3D Gaussian Splatting).

### Future Improvements

*   **Tightly-Coupled Radiometric Photometric Factors in ESKF:** Add direct thermal-gradient photometric residuals into the ESKF measurement update for LiDAR-degraded smoke/fog tunnels.
*   **WebGL Gaussian Splat Viewer Tab:** Stream compressed `.splat` buffers to an optional WebGL 3DGS shader in `static/app.js` alongside the existing point-cloud canvas.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

### Target Files to Create/Modify

#### 1. `pyproject.toml` (Modify)
*   **Type / Scope**: Build & Dependency Configuration
*   **Proposed Changes**: Add an optional dependency group `[project.optional-dependencies] forge = ["gtsam>=4.2", "small-gicp>=1.0", "rosbags>=0.11", "scipy>=1.14"]` while keeping `[project] dependencies` unchanged so core `civil serve` remains lightweight.

#### 2. `civil/pointcloud.py` (Modify)
*   **Type / Scope**: Core Data Model (`Reconstruction`)
*   **Proposed Changes**:
    *   Add optional field `temperatures_c: np.ndarray | None = None` (`(N,) float32` in degrees Celsius) to `Reconstruction`.
    *   In `Reconstruction.__post_init__()`, validate and convert non-None `temperatures_c` via `np.ascontiguousarray(self.temperatures_c, dtype=np.float32)` and enforce `self.temperatures_c.ndim == 1 and len(self.temperatures_c) == len(self.points)` (raising `ValueError("temperatures_c length must match points")` otherwise).
    *   In `Reconstruction.save()`, add `"temperatures_c"` to the optional arrays saved in `np.savez_compressed`: `for name in ("colors", "poses", "times", "labels", "gps", "temperatures_c"):`.
    *   In `Reconstruction.load()`, load `temperatures_c=z["temperatures_c"] if "temperatures_c" in z else None`.
    *   Keep `read_ply(path)`'s 3-tuple return signature `(xyz, rgb, label)` unchanged.

#### 3. `civil/forge/__init__.py` (Create)
*   **Type / Scope**: Python Package Entry Point
*   **Proposed Changes**: Export public data types and pipeline entry points (`ForgeConfig`, `ForgeResult`, `run_forge_slam`, `preflight_check`) with lazy imports for optional native dependencies.

#### 4. `civil/forge/types.py` (Create)
*   **Type / Scope**: Pure-NumPy Data Contracts & Configuration
*   **Proposed Changes**:
    *   Define dataclasses:
        - `ImuSample(t: float, gyro: np.ndarray, accel: np.ndarray)`
        - `LidarScan(t: float, points: np.ndarray, intensities: np.ndarray | None = None, point_times: np.ndarray | None = None)`
        - `CameraFrame(t: float, image: np.ndarray, intrinsics: np.ndarray, distortion: np.ndarray, T_lidar_cam: np.ndarray, modality: str = "rgb", thermal_encoding: str = "celsius_f32", planck_params: dict | None = None)`
        - `SensorCalibration(T_lidar_imu: np.ndarray, T_lidar_rgb: np.ndarray | None = None, T_lidar_thermal: np.ndarray | None = None, K_rgb: np.ndarray | None = None, D_rgb: np.ndarray | None = None, K_thermal: np.ndarray | None = None, D_thermal: np.ndarray | None = None, time_offset_imu_s: float = 0.0, time_offset_rgb_s: float = 0.0, time_offset_thermal_s: float = 0.0, thermal_encoding: str = "flir_raw", planck_params: dict = field(default_factory=lambda: {"R": 380747.0, "B": 1428.0, "F": 1.0, "O": -88.539}))`
        - `Keyframe(id: int, t: float, pose_w_b: np.ndarray, points_local: np.ndarray, raw_points_local: np.ndarray, dynamic_mask: np.ndarray, colors: np.ndarray | None = None, temperatures_c: np.ndarray | None = None, descriptor_sc: np.ndarray | None = None, ring_key: np.ndarray | None = None)`
        - `LoopConstraint(from_id: int, to_id: int, T_from_to: np.ndarray, rmse: float, inlier_ratio: float, sc_distance: float)`
        - `ForgeConfig(keyframe_dist_m: float = 1.0, keyframe_angle_deg: float = 10.0, voxel_size_m: float = 0.10, max_ram_bytes: int = 512 * 1024 * 1024, tile_size_m: float = 20.0, enable_dynamic_filter: bool = True, enable_loop_closure: bool = True, enable_thermal: bool = True, enable_gsplat: bool = True, min_free_gpu_gb: float = 4.0, max_gaussians: int = 250_000, num_threads: int = 8)`
        - `ForgeResult(reconstruction: Reconstruction, keyframes: list[Keyframe], loop_constraints: list[LoopConstraint], dynamic_mask: np.ndarray, diagnostics: dict)` with method `to_reconstruction(self) -> Reconstruction` returning `self.reconstruction`.

#### 5. `civil/forge/eskf_lio.py` (Create)
*   **Type / Scope**: 15-DOF Error-State Kalman Filter LiDAR-Inertial Odometry Front End
*   **Proposed Changes**:
    *   Implement `ESKFLIO`:
        - `predict_imu(t: float, gyro: np.ndarray, accel: np.ndarray)`: 15-DOF nominal state strapdown propagation ($\mathbf{R}, \mathbf{p}, \mathbf{v}, \mathbf{b}_g, \mathbf{b}_a$) using exact $\text{SO}(3)$ Rodrigues exponential map $\exp([\boldsymbol{\omega}\Delta t]_\times)$ and $15\times 15$ error-state covariance propagation $\mathbf{P} \leftarrow \mathbf{F}\mathbf{P}\mathbf{F}^T + \mathbf{Q}\Delta t$.
        - `deskew_scan(scan: LidarScan) -> np.ndarray`: Interpolates buffered IMU states across the scan interval $[t_0, t_1]$ to transform per-point returns into the scan-end frame.
        - `update_lidar(scan: LidarScan) -> tuple[np.ndarray, np.ndarray, dict]`: Registers deskewed scan against the local voxel submap (using `small_gicp` / point-to-plane residuals $r_i = \mathbf{n}_i^T(\mathbf{R}\mathbf{p}_i + \mathbf{p} - \mathbf{q}_i)$ with Huber weighting), projects out degenerate directions ($\lambda < 10.0$), applies the 15-DOF Kalman measurement update $\delta\mathbf{x} = \mathbf{K}\mathbf{z}$ and Joseph-form covariance update, injects $\delta\mathbf{x}$ into the nominal state with attitude reset, and returns `(pose_w_b, deskewed_points_body, telemetry_dict)`.

#### 6. `civil/forge/dynamic_filter.py` (Create)
*   **Type / Scope**: Keyframe Selection & Ground-Protected Temporal Dynamic Object Removal
*   **Proposed Changes**:
    *   Implement `TemporalDynamicFilter`:
        - `should_create_keyframe(pose_w_b: np.ndarray) -> bool`: Checks translation $\ge \Delta d_{\text{kf}}$ or rotation angle $\ge \Delta \theta_{\text{kf}}$.
        - `filter_keyframe_window(keyframes: list[Keyframe], target_idx: int) -> tuple[np.ndarray, np.ndarray, dict]`:
          1. Reuses `civil/align.py::ransac_plane` within a $12.0\text{ m}$ horizontal radius to fit local road elevation $z_{\text{road}}(x, y)$ around keyframe `target_idx`, checking that the normal is within $15^\circ$ of gravity $+Z$.
          2. For points above the pavement band ($h > +0.15\text{ m}$), projects points from overlapping keyframes in the window into spherical range images $(180 \times 32)$ and 3D occupancy voxels to detect free-space violations ($r_{\text{other}} > r_{\text{pt}} + 0.30\text{ m}$) and transient single-frame clusters.
          3. For points in the pavement protection band ($h \in [-0.40\text{ m}, +0.15\text{ m}]$), preserves negative-relief and flush road points ($h \in [-0.40\text{ m}, +0.02\text{ m}]$, protecting 2–15 cm potholes unless they lie inside a dynamic cluster's 2D footprint AND exceed the 25th-percentile local ground floor by $> +0.04\text{ m}$) and masks positive protrusions ($h \in (+0.02\text{ m}, +0.15\text{ m}]$) lying inside an above-ground dynamic cluster's 2D footprint or protruding $> +0.08\text{ m}$ above the multi-keyframe 25th-percentile local ground floor.
          4. Returns `(static_points_local, dynamic_mask_bool, stats_dict)`.

#### 7. `civil/forge/loop_closure.py` (Create)
*   **Type / Scope**: Scan-Context Place Recognition & `small_gicp` Geometric Verification
*   **Proposed Changes**:
    *   Implement `make_scan_context(points_local: np.ndarray, n_rings: int = 20, n_sectors: int = 60, max_radius_m: float = 40.0) -> tuple[np.ndarray, np.ndarray]`: Computes the $(N_r, N_s)$ polar max-height matrix and $N_r$-vector ring key.
    *   Implement `scan_context_distance(sc_a: np.ndarray, sc_b: np.ndarray) -> tuple[float, int]`: Vectorized column-wise cosine distance across all $N_s$ circular sector shifts, returning `(min_distance, best_shift_sector)`.
    *   Implement `LoopClosureDetector`: Indexes keyframe ring keys in a `scipy.spatial.cKDTree`, enforces temporal cooldown ($\Delta t \ge 25.0\text{ s}$, path distance $\ge 15.0\text{ m}$), retrieves top-$K=5$ candidates, verifies geometric alignment via `small_gicp.align` (G-ICP, 8 threads) with fallback to vectorized point-to-plane ICP, applies the 4 acceptance gates (`converged`, `inlier_ratio >= 0.45`, `rmse <= 0.35`, displacement ratio gate), and logs every candidate decision (`ACCEPTED` or `REJECTED_*`) in `audit_log`.

#### 8. `civil/forge/pose_graph.py` (Create)
*   **Type / Scope**: GTSAM iSAM2 Factor-Graph Pose Optimization
*   **Proposed Changes**:
    *   Implement `PoseGraphOptimizer`:
        - Wraps `gtsam.ISAM2` and `gtsam.NonlinearFactorGraph` (with a sparse Gauss-Newton SE(3) fallback if `gtsam` is unavailable).
        - `add_keyframe(kf_id: int, pose_w_b: np.ndarray, is_first: bool = False)`
        - `add_odometry_factor(from_id: int, to_id: int, T_rel: np.ndarray, cov_diag: np.ndarray | None = None)`
        - `add_loop_factor(constraint: LoopConstraint) -> bool`: Wraps loop factor in a Cauchy robust M-estimator (`gtsam.noiseModel.mEstimator.Cauchy.Create(1.0)`) and checks graph error sanity before committing.
        - `add_gps_prior(kf_id: int, xyz_enu: np.ndarray, sigma_m: float = 0.25)`
        - `optimize() -> tuple[dict[int, np.ndarray], dict]`: Runs `isam2.update()`, returning `{kf_id: T_w_b_4x4}` and telemetry (`error_before`, `error_after`, `num_poses`, `num_factors`).

#### 9. `civil/forge/memory.py` (Create)
*   **Type / Scope**: Spatial Tile/Octree Memory with LRU `RAM <-> SSD` Hot-Swap
*   **Proposed Changes**:
    *   Implement `SpatialTileMemory` (context manager):
        - Partitions space into 2D tiles `(ix, iy)` of size `tile_size_m = 20.0` with an internal octree/voxel index.
        - Stores point chunks inside each tile tagged by `keyframe_id` in **immutable keyframe-local coordinates** $\mathcal{F}_k$.
        - Tracks `active_ram_bytes` against `max_ram_bytes`; when exceeded, atomically writes the LRU tile to `work_dir / "forge_tiles" / f"tile_{ix}_{iy}.npz"` (`allow_pickle=False`) and drops its arrays from RAM (`evictions_to_ssd_total += 1`).
        - Transparently reloads evicted tiles from SSD on query or insertion (`reloads_from_ssd_total += 1`).
        - `update_poses(poses_w_b: dict[int, np.ndarray])`: Updates the in-RAM pose map `{kf_id: T_w_b}` in $O(K)$ time with zero SSD I/O.
        - `export_world_cloud(voxel_size_m: float | None = 0.05, max_points: int = 10_000_000) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]`: Streams tiles one by one, transforms each chunk $p_w = T_{w,k} p_k$, applies per-tile `voxel_downsample` from `civil/pointcloud.py`, and returns `(points_w, colors, temperatures_c)`.

#### 10. `civil/forge/thermal_reg.py` (Create)
*   **Type / Scope**: Radiometric Thermal (°C) & RGB Point Cloud Registration
*   **Proposed Changes**:
    *   Implement `raw_to_celsius(raw: np.ndarray, encoding: str = "flir_raw", planck_params: dict | None = None, linear_range: tuple[float, float] | None = None) -> np.ndarray`: Converts FLIR 14/16-bit raw counts via Planck law ($R, B, F, O$), centikelvin `uint16`, or float32 °C into `float32` °C; rejects uncalibrated 8-bit images with a `ValueError` specifying the missing calibration keys (`temp_min_c`, `temp_max_c`).
    *   Implement `register_rgb_and_thermal(points_w: np.ndarray, keyframes: list[Keyframe], rgb_frames: list[CameraFrame], thermal_frames: list[CameraFrame]) -> tuple[np.ndarray, np.ndarray, dict]`: Performs time-offset pose interpolation, distorted pinhole projection, per-pixel z-buffer occlusion culling ($\delta z = 0.15\text{ m}$), and inverse-distance weighted multi-view fusion to assign `(N, 3) uint8` RGB and `(N,) float32` degrees Celsius (`temperatures_c`) to the 3D map points.

#### 11. `civil/forge/gsplat.py` (Create)
*   **Type / Scope**: Keyframe-Anchored RGB + Radiometric Thermal 3D Gaussian Splatting
*   **Proposed Changes**:
    *   Implement `GaussianSplatModel` and `train_and_eval_gsplat(points_w, colors_rgb, temperatures_c, camera_frames, min_free_gpu_gb=4.0, max_gaussians=250_000, iters=60)`:
        - Checks `free_gpu_gb()` from `civil/decoders/lingbot_clip.py` before touching CUDA; uses PyTorch CUDA on RTX 5080 when `free_gpu_gb() >= min_free_gpu_gb` and falls back to vectorized NumPy/PyTorch CPU otherwise.
        - Initializes 3D Gaussians from the LiDAR surface cloud with anisotropic 3D scales from local neighborhood spacing, RGB appearance, and unactivated view-independent `float32` temperature $T_i$ (°C).
        - Holds out every 5th camera view for validation, optimizes Gaussian parameters on training views, evaluates held-out RGB **PSNR (dB)**, **SSIM**, and **Thermal RMSE / MAE (°C)**, and saves `splats.npz` to `work_dir`.

#### 12. `civil/forge/io.py` (Create)
*   **Type / Scope**: Multi-Sensor Folder & Rosbag Ingestion + Pre-Flight Validator
*   **Proposed Changes**:
    *   Reuses `read_ply`, `read_poses`, `read_gps_csv`, `quat_to_rot`, and `latlon_to_enu` from `civil/pointcloud.py`.
    *   Supports both nested dataset directories (`lidar/`, `rgb/`, `thermal/`, `imu.csv`, `calibration.json` / `calibration_results.txt`), flat uploaded files in `survey_dir / "input"` (as written by `civil/api.py::create_survey`), and ROS1 `.bag` / ROS2 `.mcap` / `.db3` containers via `rosbags.highlevel.AnyReader`.
    *   Implements `preflight_check(input_path: Path) -> dict` returning `{"ok": bool, "errors": list[str], "streams": dict, "calibration": dict, "radiometric_thermal": bool}`.

#### 13. `civil/forge/pipeline.py` (Create)
*   **Type / Scope**: End-to-End FORGE SLAM Orchestrator
*   **Proposed Changes**:
    *   Implements `run_forge_slam(input_dir: Path, work_dir: Path, config: ForgeConfig | None = None, gps: np.ndarray | None = None) -> ForgeResult`: Orchestrates Stages 1–6, writes `forge_diagnostics.json`, `dynamic_mask.npz`, and `splats.npz` to `work_dir`, and populates `ForgeResult.reconstruction` with `meta={"metric": True, "up_axis": "z", "decoder": "forge_slam", "forge_slam": summary}` so `civil/align.py` preserves gravity alignment and metric scale while performing final project-origin ENU placement.

#### 14. `civil/forge/eval.py` (Create)
*   **Type / Scope**: Apache-2.0 Trajectory, Loop-Closure, Dynamic-Removal, Memory, Splat & Thermal Benchmark Evaluator
*   **Proposed Changes**:
    *   Reuses `civil/align.py::umeyama(src, dst, with_scale=False)` to compute exact $\text{SE}(3)$ ATE (RMSE, mean, median, std, max) and $\Delta t$/$\Delta d$ RPE (translation m and rotation deg).
    *   Computes loop-closure precision/recall, dynamic ghosting reduction ratio, RAM ceiling under forced SSD evictions, per-stage latency histograms, held-out splat PSNR/SSIM, and thermal registration RMSE (°C).
    *   Generates benchmark comparison plots (`docs/figures/forge_trajectory_loop.png`, `docs/figures/forge_dynamic_removal.png`, `docs/figures/forge_memory_thermal_splat.png`) and writes `docs/FORGE-RESULTS.md`.

#### 15. `civil/decoders/forge_slam.py` (Create)
*   **Type / Scope**: iScale Decoder Plugin Implementation
*   **Proposed Changes**:
    *   Create `ForgeSlamDecoder(Decoder)` with `name = "forge_slam"`, `label = "FORGE SLAM (LiDAR + IMU + RGB + Thermal)"`, `accepts = ("ply", "poses", "gps", "images", "other")`.
    *   `available()` checks dependency availability lazily via `importlib.util.find_spec`.
    *   `decode(input_dir, work_dir, params)` parses `ForgeConfig` from `params.get("forge")`, runs `preflight_check` and `run_forge_slam`, and returns `result.to_reconstruction()`.

#### 16. `civil/decoders/__init__.py` (Modify)
*   **Type / Scope**: Decoder Registry
*   **Proposed Changes**: Import `ForgeSlamDecoder` from `.forge_slam` and add `ForgeSlamDecoder()` to the tuple in `registry()`.

#### 17. `civil/api.py` (Modify)
*   **Type / Scope**: REST API Survey Creation Parameter Validation
*   **Proposed Changes**:
    *   In `create_survey` (`civil/api.py`), add `"forge"` to `allowed`. When `"forge"` is present in `prm`, verify `isinstance(prm["forge"], dict)` and validate that all keys belong to `ForgeConfig.__dataclass_fields__` with matching primitive types (`bool`, `int`, `float`), raising `HTTPException(400, ...)` on invalid keys or types.

#### 18. `civil/worker.py` (Modify)
*   **Type / Scope**: Remote GPU Worker Task Queue
*   **Proposed Changes**: Add `"forge_slam"` to `REMOTE_DECODERS = {"lingbot_clip", "forge_slam"}` so `CIVIL_3D=remote` servers can delegate FORGE SLAM jobs to GPU workers.

#### 19. `civil/scene_scale_api.py` (Modify)
*   **Type / Scope**: Scale Summary Metadata Inference
*   **Proposed Changes**: In `scale_summary(sv)`, update `sv.get("decoder") in ("demo", "forge_slam")` so `forge_slam` surveys default to `"metric"` scale method when `sv.get("scale")` is inferred.

#### 20. `civil/check3d.py` (Modify)
*   **Type / Scope**: 3D Finding Verification Backend (Radiometric Thermal Panel)
*   **Proposed Changes**:
    *   Preserve `RENDER_VERSION = 3` and `PANELS = ("top", "height", "section")`; define `ALL_PANELS = ("top", "height", "section", "thermal")`.
    *   In `_evidence(rec, f)`, slice `temp = rec.temperatures_c[idx].astype(np.float64)` when `rec.temperatures_c is not None`, apply the `if road.sum() >= 50:` filter to `temp = temp[road]`, and compute `thermal_stats = {"min_c": round(float(temp.min()), 2), "max_c": round(float(temp.max()), 2), "mean_c": round(float(temp.mean()), 2), "road_ambient_c": round(ambient_c, 2), "delta_c": round(delta_c, 2)}`.
    *   Add an Inferno-style thermal LUT (`THERMAL_LUT`, dark purple -> red -> orange -> bright yellow) and render `panel == "thermal"` with a `°C` colour scale bar (`f"{tmin:.1f} C"` to `f"{tmax:.1f} C"`).
    *   In `get_check()`, include `"has_thermal": ev["temp"] is not None`, `"thermal_stats": ev["thermal_stats"]`, and include `"thermal"` in `images` **only** when `ev["temp"] is not None`.
    *   In `get_check_png()`, validate `if panel not in ALL_PANELS: raise HTTPException(400, "panel must be top, height, section or thermal")`; if `panel == "thermal"` and `_recon(pid, sid).temperatures_c is None`, raise `HTTPException(404, "this survey has no thermal data")` before checking the image cache.

#### 21. `static/check3d.js` (Modify)
*   **Type / Scope**: 3D Finding Verification Frontend Modal
*   **Proposed Changes**: When `c.images.thermal` is present in the `get_check()` payload, render a 4th panel figure **"Thermal (°C) — radiometric surface temperature"** (displaying `c.thermal_stats.road_ambient_c` and `c.thermal_stats.delta_c` in the caption) inside `.check3d-grid`; when `c.images.thermal` is absent, render the existing 3-panel grid unchanged.

#### 22. `civil/cli.py` (Modify)
*   **Type / Scope**: Command-Line Interface (`civil forge`)
*   **Proposed Changes**:
    *   Add subparser `forge` with actions `check`, `run`, and `eval`:
        - `civil forge check INPUT`: Runs `preflight_check(Path(INPUT))`, prints JSON report to `stdout`, exits `0` if `ok` else `SystemExit(1)`.
        - `civil forge run INPUT [--out DIR] [--project PID] [--name NAME]`: Runs `run_forge_slam`; if `--project PID` is given, creates a `"forge_slam"` survey in project `PID` and calls `pipeline.finish(...)`; prints JSON summary to `stdout`.
        - `civil forge eval [--datasets-dir DIR] [--out FILE]`: Runs the multi-sequence public dataset evaluation suite and writes `docs/FORGE-RESULTS.md` and figures.

#### 23. `tests/test_forge_eskf.py` (Create)
*   **Type / Scope**: Unit Tests for Stage 1 (ESKF LIO)
*   **Proposed Changes**: Tests 15-DOF ESKF IMU strapdown propagation, scan deskewing under constant angular velocity, point-to-plane Kalman measurement updates, Joseph-form covariance positive-definiteness, and corridor degeneracy protection.

#### 24. `tests/test_forge_dynamic.py` (Create)
*   **Type / Scope**: Unit Tests for Stage 2 (Dynamic Object Removal)
*   **Proposed Changes**: Tests keyframe gating, removal of a moving vehicle box across keyframes (>85% removal), preservation of a 5 cm deep synthetic road pothole (<1% loss under 8° grazing LiDAR rays), and audit `dynamic_mask` generation.

#### 25. `tests/test_forge_loop_posegraph.py` (Create)
*   **Type / Scope**: Unit Tests for Stages 3 & 4 (Scan-Context, `small_gicp`, GTSAM iSAM2)
*   **Proposed Changes**: Tests Scan-Context rotational shift invariance, ring-key KD-tree retrieval, `small_gicp` loop verification and false-positive rejection gates, and GTSAM `ISAM2` loop-closure ATE reduction (>50% drift reduction on a closed loop).

#### 26. `tests/test_forge_memory.py` (Create)
*   **Type / Scope**: Unit Tests for Stage 5 (Spatial Tile Memory Hot-Swap)
*   **Proposed Changes**: Tests `SpatialTileMemory` with a 64 KB RAM cap forcing deterministic `RAM -> SSD` evictions and `SSD -> RAM` reloads, verifying zero-I/O loop-closure pose updates and exact point round-trip fidelity.

#### 27. `tests/test_forge_thermal_gsplat.py` & `tests/test_forge_integration.py` & `docs/FORGE-RESULTS.md` & `docs/figures/forge_*.png` (Create)
*   **Type / Scope**: Unit/Integration Tests for Stages 6 & 7 and Evaluation Artifacts
*   **Proposed Changes**:
    *   `tests/test_forge_thermal_gsplat.py`: Tests FLIR Planck-law `Raw2Celsius` accuracy against KAIST MS² reference temperatures, z-buffer occlusion culling, 8-bit uncalibrated thermal rejection, and RGB+Thermal 3D Gaussian Splatting training + held-out PSNR/SSIM/thermal MAE evaluation.
    *   `tests/test_forge_integration.py`: Tests `ForgeSlamDecoder`, `civil forge check|run`, `Reconstruction` `temperatures_c` persistence in `recon.npz`, full `pipeline.run_survey` producing pothole findings from a FORGE SLAM sequence, and `check3d` `panel="thermal"` HTTP 200 PNG rendering (plus HTTP 404 on non-thermal surveys).
    *   `docs/FORGE-RESULTS.md` and `docs/figures/forge_*.png`: Quantitative evaluation report and diagnostic figures generated by `civil forge eval`.

### Verification Plan

All verification commands are executed from the repository root:

*   **Dependencies**: `uv sync --extra dev --extra forge` (installs gtsam, small-gicp and rosbags).
*   **Unit & Integration Tests**: `uv run --extra dev --extra forge pytest -q` (all existing 148 tests + all new `tests/test_forge_*.py` tests must pass with 0 failures).
*   **Public Dataset Evaluation**: `uv run --extra forge civil forge eval --datasets-dir <datasets-dir> --out docs/FORGE-RESULTS.md`
*   **Knowledge Graph Update**: Run `graphify update` on the repository root.

--------------------------------------------------------------------------------

<!-- Provenance: Indicates initial structural drafting via EGM. -->

*Drafted with EGM*

# Fixing a 3D clip's scale with scene objects

LingBot-Map rebuilds a clip only up to an unknown scale. With a `gps.csv` the GPS track fixes it.
Without GPS, `civil/align.py` guesses it from an assumed camera height (1.4 m), which can be far
off: a real 9 s phone clip came out 4.7 m long, and pothole depth, area and cost are then guesses.
Objects of known size seen in the clip's frames fix the scale instead.

Code: `civil/scene_scale.py` (maths), `civil/scene_scale_api.py` (routes, rescale and re-analysis),
`static/scene_scale.js` (the sheet), catalog `config/scene_refs.json`.

## Flow

1. A finished clip has a **Fix scale with scene objects** button (Video view, clip row; 3D view toolbar).
   Its tag says how it is scaled now ("Scale: camera height guess", "Scale: 3 scene references ±4%").
2. Pick a frame with the slider, choose an object (road markings, vehicles, street furniture, or a
   custom distance measured with a tape), tap its two ends (drag to adjust, magnifier on press,
   zoom for small objects). The two ends may be on different frames.
3. Every reference shows the scale it implies; the combination shows the factor, ±, p10–p90 range,
   the clip length before and after, and flags outliers.
4. **Apply** rescales the clip (points and camera poses, about the first camera's foot point, so the
   clip stays where it is on the map and the ground stays at z = 0) and re-runs the full analysis
   (depressions, depth, area, segments, condition). Findings are matched to the old ones by position,
   so ids, status, reviews, work orders, photos and photo measurements stay. Cost (DOH bill of
   materials, baht), the job card, the Repairs plan and the exports read the new numbers. A finding
   whose size comes from the 3D is marked "Scaled by: Kerb height ×3, ±34%" (drawer, job card,
   inventory tag, CSV `size_from`); with the camera-height guess it says "Scale: camera height guess,
   not measured".
5. **Undo last scale fix** restores the previous scale, notes and references (a history is kept, so
   several fixes can be undone in turn). The references are also kept in the survey's params, so
   **Try again** (rebuilding the clip) applies them before the camera-height guess.

API (project URLs are checked against the user's company; writes need a staff account):

```
GET  /api/scene_scale/refs                              catalog (+ custom distance), tap tolerance
GET  /api/projects/{pid}/surveys/{sid}/scale            current scale, ±, references, can_undo, clip length
POST /api/projects/{pid}/surveys/{sid}/scale/preview    {refs:[{ref_id, known_m?, tol_m?, points:[{frame,x,y}×2]}]}
POST /api/projects/{pid}/surveys/{sid}/scale/apply      rescale + re-analyse (409 if someone changed the scale meanwhile)
POST /api/projects/{pid}/surveys/{sid}/scale/undo
```

## Method

For each tap: stored frame pixel → LingBot model-image pixel (the frame geometry) → camera ray (the
saved per-frame intrinsics and camera-to-world pose) → the point cloud within a narrow cone around
the ray (1.5 to 12 model pixels). Floaters in front are skipped: the hit is in the nearest *dense*
layer, centred in that layer (monocular depth makes a road a few centimetres thick), from a plane fit
when it is clear, else the layer's median depth. The two 3D points give a length `d3` in model units
and the reference's scale `s = known / d3`. For heights (kerb, cone, tyre, plate height: `vertical`
in the catalog) only the vertical part of the two points counts, because near a small upright face
the two rays often meet the cloud at slightly different depths.

## Error model

Per reference, in log space (relative errors):

- **measurement** `rel_meas`: Monte Carlo, every tap moved uniformly by up to ±3 px of the stored
  frame and the hit moved along the ray by its fit's standard error; the 10–90 % spread / 2.563 is
  one sigma.
- **object size** `rel_ref`: the catalog tolerance (or the ± typed for a custom distance; 1 % if none)
  taken as one sigma. Objects without a tolerance in the source get ±10 %.
- `rel_sigma = sqrt(rel_meas² + rel_ref²)`, never below 0.2 %.

Several references: a weighted median gives a robust centre; a reference more than 3 σ from it
(compared against the others' mean, with their shared errors removed) is flagged as an outlier and
left out, but only when a majority of at least two others agree; otherwise a warning says the
references disagree. The rest are combined by generalised least squares in log space: for different
objects that is the **inverse-variance weighted mean**; references to the **same** standard object
share its size error (three taps on kerbs of one assumed height do not make the height better known),
so that part of the covariance is common and cannot be averaged away. If the references scatter more
than their errors allow (χ²/dof > 1, Birge ratio), the independent part of the errors is scaled up
by χ²/dof. The ± shown is one sigma; the range is p10–p90 of the resulting log-normal.

What the ± does **not** include:

- a wrong object size (a kerb that is not the catalog's height; a lane narrower than standard) beyond
  the catalog tolerance — check on site, or use a tape measurement as a custom distance;
- systematic depth bias of the monocular 3D on small or far features (a 15 cm kerb face 7 m away is
  smeared over several centimetres); choose frames where the object is close;
- errors of the 3D model itself between parts of the clip (the scale is one factor for the clip).

## Catalog

`config/scene_refs.json` (20 Nov 2026) holds 16 Thai objects picked from the Research Desk's
sourced catalog (`Project_CIVIL/research/scene-scale-references.json`, 170 rows): lane width (road
type unknown, and DRR local roads), zebra stripe and stripe pitch, rural and urban dash and dash
cycle, edge line, concrete joint spacing, BMA kerb stone length and height, motorcycle and pickup
wheels, and the car plate width and height. Each entry keeps its source URLs and dates, and its
`source_note` says Verified or Inference (derived from Verified rows). Rows with no stated
tolerance (DOH lane width, DOH kerb height, manhole cover, cone height: a minimum only) are left
out, so every size has a known ±. Best first: lane width, zebra pitch, motorcycle wheel, pickup
wheel, rural dash cycle. The tolerances are design values; as-built roads can vary more, and the
tap-error figures in the research are from a model, not yet checked on real clips. The earlier
provisional list is kept as `config/scene_refs.provisional-2026-11-20.json`. A size without a
source URL is still always treated as provisional, whatever the file says.

## Real-clip check (20 Nov 2026, Bangladesh 9 s phone clip, local RTX 5080)

No lane markings and no object of certain size are visible; the raised kerb with painted stripes is
the only catalog object. Three kerb-height taps (frames 1, 11, 21) gave ×0.498, ×0.518, ×0.461 each
±34 % (the provisional 15 ± 5 cm height dominates); combined ×0.482 ±34 % (p10–p90 0.31–0.74),
clip length 4.68 m → 2.26 m. The three taps agree within 6 %, so the 3D is consistent, but the result
is not plausible: it implies a camera 0.7 m above the road moving at 0.27 m/s, while the clip looks
like a hand-held phone at walking pace. More likely the kerb is about 30 cm tall (which is what the
camera-height scale measured), i.e. the provisional 15 cm does not fit this street. The pothole is
detector-only in the 3D at either scale (dip 2.7 cm vs road noise ±7.1 cm before; 1.4 vs ±3.6 cm
after), so no depth, area or cost could be measured from this clip. The cost path is verified on the
synthetic clip in `tests/test_scene_scale_api.py`.

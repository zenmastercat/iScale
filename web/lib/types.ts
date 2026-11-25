/*
 * Types for the iScale API, written from real responses of the demo project
 * (POST /api/demo, then every GET below). `?` means the key is absent on some records.
 * Do not add fields here that you have not seen in a response. Ask the lead.
 */

export type Severity = "high" | "medium" | "low";

/** Finding status as stored by the backend (civil/api.py FINDING_STATES). */
export type FindingStatus = "open" | "planned" | "fixed" | "verified" | "not_fixed" | "dismissed";

/** Per-finding verification result (civil/verify.py). */
export type VerifyStatus = "verified" | "not_fixed" | "not_covered";

export type WorkOrderStatus = "open" | "scheduled" | "completed" | "verified" | "partially_verified" | "cancelled";

export type SurveyStatus = "queued" | "running" | "done" | "error";

/** Condition band names from civil/analysis/condition.py, plus "no data". */
export type Rating = "good" | "satisfactory" | "fair" | "poor" | "very poor" | "failed" | "no data";

// --- auth ----------------------------------------------------------------------------
export interface User {
  username: string;
  display_name: string;
  role: "admin" | "engineer" | string;
  company_id: string;
  company: string;
  account: "company" | "individual" | string;
  host_admin: boolean;
  device_bound: boolean;
  disabled: boolean;
}

export interface AuthState {
  setup_needed: boolean;
  user: User | null;
  signup: { company: boolean; individual: boolean };
}

export interface Challenge {
  nonce: string;
  /** true when this username has no device key yet: this device may claim it */
  claim: boolean;
  message: string;
}

// --- meta ----------------------------------------------------------------------------
export interface CatalogItem {
  code: string;
  label: string;
  category: string;
  kind: "defect" | "asset";
  detection: ("decoder" | "geometry" | "manual")[];
  action: string;
  unit: "each" | "m" | "m2";
  synonyms: string[];
}

export interface Decoder {
  name: string;
  label: string;
  description: string;
  accepts: string[];
  available: boolean;
  unavailable_reason: string;
  internal: boolean;
}

export interface Meta {
  catalog: CatalogItem[];
  severities: Severity[];
  decoders: Decoder[];
  currency: string;
  default_origin: [number, number];
}

// --- projects & surveys ----------------------------------------------------------------
export interface SurveyStats {
  points: number;
  findings: number;
  segments: number;
  length_m: number;
  analysis_s: number;
}

export interface Survey {
  id: string;
  project_id: string;
  name: string;
  decoder: string;
  params: Record<string, unknown>;
  status: SurveyStatus;
  /** current pipeline stage while running, "" otherwise */
  stage: string;
  error: string | null;
  /** unix seconds */
  created: number;
  notes?: string[];
  stats?: SurveyStats;
}

/** GET /api/projects (list items) */
export interface ProjectSummary {
  id: string;
  name: string;
  origin_lat: number;
  origin_lon: number;
  created: number;
  /** survey ids */
  surveys: string[];
  /** survey id of the baseline drive, if set */
  baseline?: string;
  company_id: string;
}

/** GET /api/projects/{pid} */
export interface Project extends ProjectSummary {
  survey_list: Survey[];
}

// --- analysis ----------------------------------------------------------------------------
export interface SegmentMetrics {
  road_left_m: number;
  road_right_m: number;
  road_width_m: number;
  coverage: number;
  surface_std_mm: number;
}

export interface Segment {
  /** "S001" ... */
  id: string;
  index: number;
  /** chainage start/end in metres */
  s0: number;
  s1: number;
  length_m: number;
  metrics: SegmentMetrics;
  /** 0-100 condition index; null when the segment has no data */
  condition: number | null;
  rating: Rating;
  /** band colour from the backend, same as CONDITION_BANDS */
  color: string;
  defect_count: number;
  area_m2: number;
  /** [lon, lat] pairs */
  coords: [number, number][];
  /** present once traffic was fetched (POST .../traffic) */
  traffic?: Record<string, unknown>;
}

export interface FindingMetrics {
  area_m2?: number;
  depth_max_m?: number;
  depth_median_m?: number;
  volume_m3?: number;
  diameter_m?: number;
  circularity?: number;
  flat_share?: number;
  bowl?: number;
  step_m?: number;
  direction?: "raised" | string;
  texture_std_mm?: number;
  height_max_m?: number;
  height_m?: number;
  trunk_width_m?: number;
  top_span_m?: number;
  plate_points?: number;
  canopy_m?: number;
}

/** Short materials-only cost (jobcard.cost_summary). Currency here is the materials currency (THB). */
export interface MaterialsCost {
  materials_cost: number;
  method: "small_patch" | "layered_patch" | "full_depth" | string;
  symbol: string;
  currency: string;
  missing_prices: boolean;
}

export interface FindingHistoryEntry {
  t: number;
  event: string;
  by?: string;
  workorder?: string;
  fields?: string[];
}

export interface Finding {
  /** "FEF0-0001" (detected) or "M-0001" (manual) */
  id: string;
  /** catalog code, e.g. "pothole", "manhole_sunken", "sign_stop" */
  type: string;
  /** null for assets */
  severity: Severity | null;
  source: "geometry" | "decoder" | "manual" | string;
  x: number;
  y: number;
  z: number;
  bbox: number[];
  metrics: FindingMetrics;
  /** human sentence of what was measured, e.g. "depression 7.8 cm deep, 0.87 m across, 31.1 L missing material" */
  evidence: string;
  segment_id: string | null;
  lat: number;
  lon: number;
  status: FindingStatus;
  history?: FindingHistoryEntry[];
  /** an engineer's judgement of the 3D check (POST .../review); `by` is the user id in the stored analysis */
  review?: { verdict: "correct" | "wrong" | "unsure"; note?: string; at: number; by?: string; by_name?: string };
  note?: string;
  /** imported camera run: a detector crop is served at GET /api/projects/{pid}/surveys/{sid}/findings/{id}/photo */
  photo?: boolean;
  /** weak detector track (few hits): check it first */
  needs_review?: boolean;
  /** detector confidence 0..1 */
  confidence?: number;
  detector?: {
    track_id: string; frames: string; hits: number; max_conf: number; alerted: boolean; min_dist_y_m: number;
    est_cost_thb: number; est_material_kg: number; est_volume_m3: number; crop: string;
  };
  workorder_id?: string;
  verification?: { status: VerifyStatus; evidence: string; after_survey: string };
  /** added by GET .../analysis; null when not costed (assets, some defect types) */
  cost: MaterialsCost | null;
}

export interface AnalysisParams {
  road_half_width_m: number;
  segment_length_m: number;
  raster_m: number;
  pothole_min_depth_m: number;
  pothole_min_area_m2: number;
  pothole_max_depth_m: number;
  roughness_std_m: number;
  roughness_min_area_m2: number;
  heave_min_height_m: number;
  trip_hazard_step_m: number;
  sidewalk_band_m: number[];
  object_min_height_m: number;
}

/** GET /api/projects/{pid}/surveys/{sid}/analysis. (The API strips `path` and segment `line`.) */
export interface Analysis {
  segments: Segment[];
  findings: Finding[];
  params: AnalysisParams;
  seconds: number;
  survey_id: string;
}

// --- planning ------------------------------------------------------------------------------
export interface PlanItem {
  finding_id: string;
  type: string;
  label: string;
  severity: Severity;
  segment_id: string;
  action: string;
  action_label: string;
  unit: "each" | "m2" | string;
  quantity: number;
  rate: number;
  /** in Plan.currency (THB, config/unit_costs.json) */
  cost: number;
  priority: number;
  traffic_factor: number;
  road: string | null;
  lat: number;
  lon: number;
  maps_url: string;
}

export interface PlanByAction {
  action: string;
  label: string;
  unit: string;
  quantity: number;
  cost: number;
  count: number;
}

/** GET .../plan?mode=spot[&budget=] */
export interface SpotPlan {
  mode: "spot";
  currency: string;
  budget: number | null;
  /** what fits in the budget (all repairable open defects when no budget) */
  items: PlanItem[];
  /** over budget */
  deferred: PlanItem[];
  by_action: PlanByAction[];
  mobilization: number;
  total: number;
  note: string;
}

export interface SegmentPlanItem {
  segment_id: string;
  condition: number;
  rating: Rating;
  treatment: "preventive" | "resurface" | string;
  label: string;
  area_m2: number;
  rate: number;
  cost: number;
  urgency: number;
  traffic_factor: number;
  road: string | null;
}

/** GET .../plan?mode=segment[&budget=] */
export interface SegmentPlan {
  mode: "segment";
  currency: string;
  budget: number | null;
  items: SegmentPlanItem[];
  deferred: SegmentPlanItem[];
  total: number;
  note: string;
}

export type Plan = SpotPlan | SegmentPlan;

/** GET /api/priority item ("Fix first" list) */
export interface PriorityItem {
  kind: "finding" | "pin";
  /** finding id (or pin id) */
  id: string;
  label: string;
  severity: Severity;
  priority: number;
  traffic_factor: number;
  road: string | null;
  /** absent on pins */
  segment_id?: string;
  lat: number;
  lon: number;
  maps_url: string;
  /** repair cost in the plan currency (THB); absent on pins */
  cost?: number;
  /** action label, e.g. "Patch pothole"; absent on pins */
  action?: string;
  materials: MaterialsCost | null;
  rank: number;
  // --- pins only (kind === "pin"), from civil/priority.py pin_item ---
  road_name?: string | null;
  reporter?: string;
  /** number of colleagues who confirmed the pin */
  confirmations?: number;
  note?: string;
  /** unix seconds */
  created?: number;
}

export interface Priority {
  items: PriorityItem[];
  formula: string;
}

// --- work orders & verification -----------------------------------------------------------
export interface WorkOrder {
  /** "WO-0001" */
  id: string;
  title: string;
  survey_id: string;
  status: WorkOrderStatus;
  created: number;
  items: PlanItem[];
  total: number;
  currency: string;
  verification: { verified: number; total: number; after_survey: string } | null;
}

export interface VerificationResult {
  finding_id: string;
  type: string;
  severity: Severity;
  status: VerifyStatus;
  evidence: string;
  /** id of the matching finding in the after survey, if any */
  after_match: string | null;
  surface_delta_m: number;
  before_metrics: FindingMetrics;
  after_metrics: FindingMetrics | null;
  lat: number;
  lon: number;
  x: number;
  y: number;
}

/** POST /api/projects/{pid}/verify, GET /api/projects/{pid}/verification (null until run) */
export interface Verification {
  created: number;
  results: VerificationResult[];
  counts: { verified: number; not_fixed: number; not_covered: number };
  before: string;
  after: string;
  workorder_id: string | null;
}

// --- job card ------------------------------------------------------------------------------
export interface JobCardTile {
  key: string;
  label: string;
  value: number;
  unit: string;
}

export interface BillLine {
  key: string;
  code: string;
  label: string;
  label_th: string;
  qty: number;
  unit: string;
  unit_price: number;
  amount: number;
  detail: string;
  source: string;
}

/** GET /api/projects/{pid}/surveys/{sid}/findings/{fid}/card */
export interface JobCard {
  kind: "finding" | "pin";
  id: string;
  type: string;
  label: string;
  severity: Severity | null;
  status: FindingStatus;
  location: {
    lat: number;
    lon: number;
    address: { road: string; line1: string; line2: string; full: string; source: string } | null;
    road_name: string | null;
    nav_url: string;
    maps_url: string;
    /** best drive frame, or null when the survey has no frames (demo) */
    photo: { url: string; frame: number; distance_m: number; boxes: unknown; note: string } | null;
    reported: number;
    survey: string;
    tiles: JobCardTile[];
    evidence: string;
    reporter?: string;
  };
  cost: {
    available: boolean;
    currency: string;
    symbol: string;
    method: string;
    method_label: string;
    depth_m: number;
    area_m2: number;
    cut_area_m2: number;
    cut_w_m: number;
    cut_l_m: number;
    cut_edge_m: number;
    asphalt_depth_m: number;
    base_depth_m: number;
    layers: number;
    mix_kg: number;
    bags: number;
    tack_l: number;
    prime_l: number;
    base_m3: number;
    lines: BillLine[];
    subtotal: number;
    materials_cost: number;
    missing_prices: string[];
    tools: string[];
    excludes: string;
  };
  timing: {
    window: string;
    days: string;
    level: string;
    reason: string;
    road_class: string;
    road: string | null;
    road_name: string | null;
    factor: number | null;
    basis: string;
  };
  plan: {
    urgency: string;
    urgency_code: string;
    warning: string;
    method: string;
    steps: string[];
    materials: string[];
    mass_kg: number;
  };
}

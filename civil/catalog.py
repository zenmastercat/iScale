"""Catalog of inspectable issue and asset types.

Each entry says what the thing is, how it can be found without a learned model
("geometry" = a rule in civil.analysis.detect, "manual" = tagged by a person in the
3D viewer, "decoder" = labels supplied by an external decoder), how it is repaired,
and in which unit the repair is priced.  Unit costs live in config/unit_costs.json.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class IssueType:
    code: str
    label: str
    category: str  # pavement | sidewalk | signage | lighting | utilities | drainage | markings | vegetation | structures | accessibility
    kind: str  # "defect" (needs repair) or "asset" (inventory item)
    detection: tuple[str, ...]  # geometry | manual | decoder
    action: str  # repair action code, priced in unit_costs.json
    unit: str  # m2 | m | each
    synonyms: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["detection"] = list(self.detection)
        d["synonyms"] = list(self.synonyms)
        return d


G, M, D = "geometry", "manual", "decoder"

_TYPES: list[IssueType] = [
    # --- pavement defects -------------------------------------------------
    IssueType("pothole", "Pothole", "pavement", "defect", (G, M, D), "patch_pothole", "m2", ("potholes", "hole", "holes")),
    IssueType("depression", "Depression / settlement", "pavement", "defect", (G, M, D), "patch_level", "m2", ("settlement", "dip", "sag")),
    IssueType("heave", "Heave / bump", "pavement", "defect", (G, M, D), "grind_patch", "m2", ("bump", "bumps", "upheaval")),
    IssueType("rutting", "Rutting", "pavement", "defect", (M, D), "mill_inlay", "m2", ("rut", "ruts", "wheel path")),
    IssueType("surface_roughness", "Rough surface (possible cracking/ravelling)", "pavement", "defect", (G, M, D), "surface_seal", "m2", ("rough", "roughness", "ravel", "ravelling")),
    IssueType("alligator_cracking", "Alligator (fatigue) cracking", "pavement", "defect", (M, D), "full_depth_patch", "m2", ("alligator", "fatigue crack", "crocodile")),
    IssueType("longitudinal_crack", "Longitudinal crack", "pavement", "defect", (M, D), "crack_seal", "m", ("longitudinal",)),
    IssueType("transverse_crack", "Transverse crack", "pavement", "defect", (M, D), "crack_seal", "m", ("transverse",)),
    IssueType("block_cracking", "Block cracking", "pavement", "defect", (M, D), "surface_seal", "m2", ("block crack",)),
    IssueType("edge_cracking", "Edge cracking", "pavement", "defect", (M, D), "crack_seal", "m", ("edge crack",)),
    IssueType("patch_failure", "Failed patch", "pavement", "defect", (M, D), "patch_pothole", "m2", ("failed patch", "patching")),
    IssueType("raveling", "Raveling", "pavement", "defect", (M, D), "surface_seal", "m2", ("raveling",)),
    IssueType("bleeding", "Bleeding", "pavement", "defect", (M, D), "surface_seal", "m2", ()),
    IssueType("shoving", "Shoving / corrugation", "pavement", "defect", (M, D), "mill_inlay", "m2", ("corrugation", "shoving")),
    IssueType("joint_spall", "Concrete joint spall", "pavement", "defect", (M, D), "spall_repair", "m", ("spall", "spalling")),
    IssueType("faulting", "Concrete slab faulting", "pavement", "defect", (M, D), "grind_patch", "m", ("faulting",)),
    IssueType("utility_cut", "Utility cut patch", "pavement", "defect", (M, D), "patch_level", "m2", ("utility cut", "trench")),
    # --- sidewalks & accessibility -----------------------------------------
    IssueType("sidewalk_trip_hazard", "Sidewalk trip hazard (vertical step)", "sidewalk", "defect", (G, M, D), "sidewalk_grind", "each", ("trip hazard", "trip hazards", "uneven sidewalk", "sidewalk step")),
    IssueType("sidewalk_crack", "Sidewalk crack", "sidewalk", "defect", (M, D), "crack_seal", "m", ("sidewalk crack",)),
    IssueType("sidewalk_missing", "Missing sidewalk segment", "sidewalk", "defect", (M, D), "sidewalk_replace", "m2", ("missing sidewalk", "sidewalk gap")),
    IssueType("sidewalk_obstruction", "Sidewalk obstruction", "sidewalk", "defect", (M, D), "obstruction_removal", "each", ("obstruction", "blocked sidewalk")),
    IssueType("curb_ramp_missing", "Missing curb ramp", "accessibility", "defect", (M, D), "curb_ramp_install", "each", ("missing ramp", "no ramp")),
    IssueType("curb_ramp", "Curb ramp", "accessibility", "asset", (M, D), "inspect", "each", ("curb ramp", "ramps", "ada ramp")),
    IssueType("detectable_warning_missing", "Missing detectable warning surface", "accessibility", "defect", (M, D), "warning_pad_install", "each", ("tactile", "truncated domes")),
    IssueType("curb_damage", "Damaged curb", "sidewalk", "defect", (M, D), "curb_repair", "m", ("broken curb", "curb")),
    # --- signage ------------------------------------------------------------
    IssueType("sign_stop", "Stop sign", "signage", "asset", (G, M, D), "inspect", "each", ("stop sign", "stop signs", "stop")),
    IssueType("sign_warning", "Warning sign", "signage", "asset", (G, M, D), "inspect", "each", ("warning sign", "warning signs", "yellow sign")),
    IssueType("sign_regulatory", "Regulatory sign", "signage", "asset", (G, M, D), "inspect", "each", ("regulatory sign", "speed limit", "no parking")),
    IssueType("sign_guide", "Guide / street-name sign", "signage", "asset", (G, M, D), "inspect", "each", ("street sign", "street name", "guide sign", "green sign")),
    IssueType("sign_other", "Sign (type not resolved)", "signage", "asset", (G, M, D), "inspect", "each", ("sign", "signs")),
    IssueType("sign_damaged", "Damaged / faded sign", "signage", "defect", (M, D), "sign_replace", "each", ("faded sign", "damaged sign", "bent sign")),
    IssueType("sign_obstructed", "Obstructed sign", "signage", "defect", (M, D), "vegetation_trim", "each", ("hidden sign", "obstructed sign")),
    IssueType("sign_leaning", "Leaning sign post", "signage", "defect", (M, D), "sign_reset", "each", ("leaning sign", "tilted sign")),
    # --- lighting & poles ---------------------------------------------------
    IssueType("streetlight", "Streetlight", "lighting", "asset", (G, M, D), "inspect", "each", ("streetlight", "streetlights", "street light", "lamp", "light pole")),
    IssueType("streetlight_out", "Streetlight out / damaged", "lighting", "defect", (M, D), "luminaire_replace", "each", ("light out", "broken light")),
    IssueType("utility_pole", "Utility pole", "utilities", "asset", (G, M, D), "inspect", "each", ("utility pole", "utility poles", "power pole", "pole", "poles")),
    IssueType("pole_leaning", "Leaning pole", "utilities", "defect", (M, D), "pole_reset", "each", ("leaning pole",)),
    IssueType("traffic_signal", "Traffic signal", "signage", "asset", (M, D), "inspect", "each", ("traffic light", "signal", "signals")),
    # --- utilities & drainage -----------------------------------------------
    IssueType("manhole", "Manhole / utility cover", "utilities", "asset", (G, M, D), "inspect", "each", ("manhole", "manholes", "utility cover", "cover")),
    IssueType("manhole_sunken", "Sunken / raised manhole cover", "utilities", "defect", (G, M, D), "manhole_adjust", "each", ("sunken manhole", "sunken cover", "raised manhole")),
    IssueType("fire_hydrant", "Fire hydrant / short post", "utilities", "asset", (G, M, D), "inspect", "each", ("hydrant", "hydrants", "bollard", "bollards", "post")),
    IssueType("storm_drain", "Storm drain inlet", "drainage", "asset", (M, D), "inspect", "each", ("drain", "drains", "inlet", "catch basin")),
    IssueType("storm_drain_blocked", "Blocked storm drain", "drainage", "defect", (M, D), "drain_clean", "each", ("blocked drain", "clogged drain")),
    IssueType("ponding", "Standing water / ponding", "drainage", "defect", (M, D), "patch_level", "m2", ("ponding", "puddle", "standing water")),
    # --- markings -------------------------------------------------------------
    IssueType("marking_faded", "Faded lane marking", "markings", "defect", (M, D), "restripe", "m", ("faded marking", "faded lines", "lane line")),
    IssueType("crosswalk", "Crosswalk", "markings", "asset", (M, D), "inspect", "each", ("crosswalk", "crosswalks", "zebra")),
    IssueType("crosswalk_faded", "Faded crosswalk", "markings", "defect", (M, D), "restripe", "m2", ("faded crosswalk",)),
    IssueType("stop_bar_faded", "Faded stop bar", "markings", "defect", (M, D), "restripe", "m", ("stop line", "stop bar")),
    # --- vegetation & structures ---------------------------------------------
    IssueType("tree", "Tree", "vegetation", "asset", (G, M, D), "inspect", "each", ("tree", "trees")),
    IssueType("vegetation_overhang", "Vegetation overhang / clearance", "vegetation", "defect", (M, D), "vegetation_trim", "each", ("overhang", "branches", "low branch")),
    IssueType("root_damage", "Tree root damage", "vegetation", "defect", (M, D), "sidewalk_replace", "m2", ("roots", "root")),
    IssueType("guardrail", "Guardrail", "structures", "asset", (M, D), "inspect", "m", ("guardrail", "barrier")),
    IssueType("guardrail_damaged", "Damaged guardrail", "structures", "defect", (M, D), "guardrail_repair", "m", ("damaged guardrail",)),
    IssueType("bus_shelter", "Bus shelter", "structures", "asset", (M, D), "inspect", "each", ("bus stop", "shelter")),
    IssueType("bench", "Bench", "structures", "asset", (M, D), "inspect", "each", ("bench", "benches")),
    IssueType("graffiti", "Graffiti", "structures", "defect", (M, D), "graffiti_removal", "each", ("graffiti", "tag")),
    IssueType("debris", "Debris / dumping", "structures", "defect", (M, D), "debris_removal", "each", ("debris", "trash", "dumping")),
]

CATALOG: dict[str, IssueType] = {t.code: t for t in _TYPES}

SEVERITIES = ("low", "medium", "high")

# Weight of each severity in condition deducts and repair priority.
SEVERITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.5}


def get(code: str) -> IssueType:
    if code not in CATALOG:
        raise KeyError(f"unknown issue type: {code}")
    return CATALOG[code]


def match_type(text: str) -> list[str]:
    """Return catalog codes whose label, code or synonym appears in free text.

    Longer phrases win: "stop signs" maps to sign_stop, not to the generic "sign".
    """
    t = " " + text.lower().replace("-", " ") + " "
    hits: list[tuple[int, str]] = []
    for it in _TYPES:
        phrases = {it.code.replace("_", " "), it.label.lower(), *it.synonyms}
        best = max((len(p) for p in phrases if f" {p} " in t or f" {p}s " in t), default=0)
        if best:
            hits.append((best, it.code))
    if not hits:
        return []
    hits.sort(reverse=True)
    top = hits[0][0]
    # keep every match as long as the longest one, plus any that is not a sub-phrase of it
    return [c for n, c in hits if n == top]


def as_list() -> list[dict]:
    return [t.to_dict() for t in _TYPES]

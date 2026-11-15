"""Build Civil-Scan-Logic-and-Figures.docx in the project folder.

Run:  uv run --with python-docx python docs/build/make_docx.py
(figures first: uv run python docs/build/figures.py)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
FIG = Path(__file__).with_name("fig")
SHOT = ROOT / "docs" / "screenshots"
OUT = ROOT / "Civil-Scan-Logic-and-Figures.docx"
sys.path.insert(0, str(ROOT))
from civil import jobcard, materials  # noqa: E402  (the document is built from the app's own code)

MAT = materials.defaults()
TIMING = jobcard.timing_rules()["classes"]
MR = json.loads((Path(__file__).with_name("fig") / "materials_rangoon.json").read_text())
SYM = MAT["symbol"]
INK, INK2, ACTION = RGBColor(0x1D, 0x26, 0x22), RGBColor(0x5E, 0x6A, 0x64), RGBColor(0x1E, 0x4F, 0x8F)

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
for side in ("left_margin", "right_margin"):
    setattr(sec, side, Cm(2.2))
sec.top_margin, sec.bottom_margin = Cm(2.0), Cm(2.0)

st = doc.styles["Normal"]
st.font.name, st.font.size, st.font.color.rgb = "Calibri", Pt(10.5), INK
st.paragraph_format.space_after = Pt(5)
st.paragraph_format.line_spacing = 1.15
for name, size in (("Heading 1", 16), ("Heading 2", 12.5), ("Heading 3", 11)):
    h = doc.styles[name]
    h.font.name, h.font.size, h.font.color.rgb, h.font.bold = "Calibri", Pt(size), INK if name != "Heading 1" else ACTION, True

fig_no = 0
tab_no = 0


def p(text: str = "", bold_lead: str | None = None, style: str | None = None, size: float | None = None, color=None, italic=False):
    para = doc.add_paragraph(style=style)
    if bold_lead:
        r = para.add_run(bold_lead)
        r.bold = True
    r = para.add_run(text)
    r.italic = italic
    if size:
        r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    return para


def bullets(items):
    for it in items:
        if isinstance(it, tuple):
            p(it[1], bold_lead=it[0] + " ", style="List Bullet")
        else:
            p(it, style="List Bullet")


def numbered(items):
    for it in items:
        p(it, style="List Number")


def formula(text: str):
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Cm(0.8)
    r = para.add_run(text)
    r.font.name = "Consolas"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    r.font.size = Pt(9.5)
    r.font.color.rgb = ACTION
    return para


def figure(path: Path, caption: str, width_cm: float = 16.4):
    global fig_no
    fig_no += 1
    doc.add_picture(str(path), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    c = p(caption, bold_lead=f"Figure {fig_no}. ", size=9, color=INK2)
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return fig_no


def shade(cell, hex_fill: str):
    tcPr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def table(head, rows, widths_cm, caption: str | None = None):
    global tab_no
    if caption:
        tab_no += 1
        p(caption, bold_lead=f"Table {tab_no}. ", size=9, color=INK2)
    t = doc.add_table(rows=1, cols=len(head))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(head):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size = True, Pt(9)
        shade(c, "E8EEF6")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(9)
    for row in t.rows:
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


# ------------------------------------------------------------------------------------------- title
t = doc.add_paragraph()
r = t.add_run("Civil Scan")
r.bold, r.font.size, r.font.color.rgb = True, Pt(28), ACTION
t2 = doc.add_paragraph()
r = t2.add_run("How it works: the logic and the figures behind the project")
r.font.size, r.font.color.rgb = Pt(15), INK
p("Project folder: /home/lucas/Documents/Projects/civil-scan   ·   Version of 15 November 2026, with field test, pothole map, Civil Helper, materials cost, the pothole job card and self sign-up", size=9, color=INK2)
p("Every formula and constant in this document is taken from the code as it stands (module names are given so each "
  "figure can be checked). Figures marked \"example\" use made-up inputs to show the shape of the logic; they are not field results.",
  size=9.5, color=INK2, italic=True)

# ------------------------------------------------------------------------------------------- 1 pitch
doc.add_heading("1. The pitch", level=1)
p("Find every pothole. Fix the right one first.", size=13, color=ACTION).runs[0].bold = True
p("Civil Scan is road inspection for city engineering teams. A crew drives a street with a camera; the app finds the "
  "potholes, measures them in 3D, scores every 25 m of road, ranks what to fix first by how dangerous it is and how busy "
  "the road is, and proves afterwards that each repair held. Engineers share one pothole map, talk in encrypted chats, "
  "and ask Civil Helper, an assistant that answers from the organisation's own manuals.")
bullets([
    ("Video in, measured potholes out.", "A pothole detector (Roboflow) scans the drive video; only the 20 seconds around each "
     "find are rebuilt in 3D by LingBot-Map on the local GPU, so depth and size are measured instead of guessed."),
    ("A condition score for every 25 m.", "Streets are coloured from good to failed, with repair plans, costs, work orders "
     "and a budget limit."),
    ("Proof that the fix happened.", "Drive the street again; each repair comes back as verified, still present, or not covered."),
    ("Fix first where traffic is heaviest.", "Priority = severity x safety x traffic, using the road's class from "
     "OpenStreetMap and live Google congestion when the admin adds a key."),
    ("Know what each repair needs.", "Every pothole shows the cost of its materials (no labour): bags of cold mix, tack coat "
     "and base rock, worked out from its measured size and depth. Tap it for the full job card: photo, address, a navigation "
     "button, the bill of materials, the best time to work and the repair steps, laid out for a phone or iPad on site."),
    ("One shared pothole map.", "Anyone pins a pothole once and every engineer on the server sees it; each colleague who "
     "confirms it pushes it up the list."),
    ("Crew chat that stays private.", "1:1 and group chats with the Signal Protocol (the protocol WhatsApp uses). Messages "
     "live on the devices; the server only relays ciphertext and deletes it on delivery."),
    ("Civil Helper answers from your manuals.", "Ask a civil-engineering question; Civil Helper answers from the company's own "
     "documents and names its sources. It runs on a local Qwen model, or any provider the admin connects."),
    ("Sign in with a username.", "No password to forget or leak: the username is bound to the person's device by a "
     "cryptographic key. Usernames and names are stored encrypted."),
    ("Sign up as a company or on your own.", "Start a company and invite your team with a join code, join one with its "
     "code, or work alone with an individual account that can grow into a company later."),
    ("Your server, your data.", "The admin chooses who can reach it: the internet (default), the office network, or "
     "this computer only."),
])

# ------------------------------------------------------------------------------------------- 2 overview
doc.add_heading("2. System overview", level=1)
p("Civil Scan is one Python web server (FastAPI) with a browser front end. It does not contain a trained model of its "
  "own: detection and 3D reconstruction are external, swappable components, and everything after them is explicit, "
  "inspectable rules and formulas.")
figure(FIG / "f1_architecture.png", "Components and where data lives. Light blue: runs in the user's browser; white: the company server; right: optional outside services.")
table(["Part", "What it does", "Code"], [
    ["Accounts", "Username + device-key sign-in, self sign-up (company, join code, individual), admins, sessions", "civil/auth.py, civil/vault.py, static/session.js"],
    ["Survey pipeline", "Detect -> windows -> LingBot -> align -> rules -> condition -> plans", "civil/video/*, civil/align.py, civil/analysis/*"],
    ["Fix-first ranking", "Severity x safety x traffic for survey defects and shared pins", "civil/priority.py, civil/traffic.py"],
    ["Shared pins", "Pothole pins seen by everyone on the server, confirmations, optional size", "civil/pins.py"],
    ["Materials and job card", "Materials-only bill of materials, repair window, steps; the four-part pothole card", "civil/materials.py, civil/jobcard.py, static/jobcard.js"],
    ["Chat relay", "Signal-Protocol ciphertext relay, groups", "civil/messaging.py, civil/groups.py, static/chat.js"],
    ["Civil Helper", "Document library, hybrid search, LLM provider settings", "civil/helper.py"],
    ["Front end", "Map, 3D, repairs, verification, video, messages, settings", "static/*.js"],
], [3.0, 8.4, 5.2], "Main parts and their code.")

# ------------------------------------------------------------------------------------------- 3 video
doc.add_heading("3. From drive video to measured potholes", level=1)
doc.add_heading("3.1 Detection and the ±10 s window", level=2)
p("The detector is Roboflow's hosted model pothole-all-conditions-n6tqz/1. The app samples the video at 3 frames per "
  "second and keeps detections with confidence of at least 0.45. To avoid chasing a single false positive, a detection "
  "becomes an event only when at least 2 hits fall within 1 s of each other. Each event opens a clip:")
formula("clip = [ t_first_hit - 10 s ,  t_last_hit + 10 s ]   clamped to [0, video length];  overlapping clips merge")
p("Only the clips go to LingBot-Map. A 2-minute drive with three potholes therefore costs three ~20 s reconstructions "
  "instead of one 120 s reconstruction, which is what makes a 16 GB GPU enough (Figure 2).")
figure(FIG / "f2_windows.png", "Detection hits become events, and events become clips for 3D (example data; logic from civil/video/windows.py and config/video.json).")
doc.add_heading("3.2 3D reconstruction with LingBot-Map", level=2)
p("LingBot-Map (Robbyant, arXiv:2604.14141, Apache-2.0) turns ordinary RGB video into camera poses and per-frame depth. "
  "Its output is not in metres: scale is normalised to the first frames. On this computer it runs on the RTX 5080 with a "
  "low-memory wrapper (bfloat16 backbone, depth in chunks of 2 frames, 5 frames per second, smaller attention cache); a "
  "20 s clip of 109 frames took 22 s in the test run.")
doc.add_heading("3.3 Scale and position (civil/align.py)", level=2)
numbered([
    "Up axis: taken from the decoder's metadata, otherwise estimated from the dominant plane (the road).",
    "Scale: from a GPS track when the survey has one (similarity fit), otherwise from the known camera height above the "
    "road (default 1.4 m): scale = camera height / reconstructed height of the camera above the fitted road plane.",
    "Map position: Umeyama similarity fit of the camera path to the GPS track on the horizontal plane; without GPS, the "
    "start point and heading entered for the survey.",
])
doc.add_heading("3.4 Perspective transform: a size from the 2D frame", level=2)
p("Following the four-point OpenCV method, four points on the road in the camera frame are matched to the corners of a "
  "real rectangle on the road (default 3.5 m lane width x 12 m length, near edge 4 m ahead). The 3 x 3 homography H maps "
  "any road pixel to metres on the road plane:")
formula("[u, v, w]^T = H · [x, y, 1]^T ,   road position (m) = (u / w, v / w)")
formula("H = cv2.getPerspectiveTransform(src_4_points, dst_rectangle_m);  top view = cv2.warpPerspective(frame, H, size)")
p("The detector's box is mapped through H to give a first width, length and area estimate and a top-down evidence image. "
  "The defaults are uncalibrated guesses, so the app hides these sizes until the camera is calibrated once with "
  "`civil calibrate`. The 3D measurement remains the main one; this is the quick cross-check.")
figure(FIG / "f3_perspective.png", "Perspective transform: the trapezoid in the frame becomes a 3.5 m x 12 m rectangle seen from above (example box; civil/video/perspective.py).")
doc.add_heading("3.5 Joining 2D and 3D", level=2)
p("Each detector box is carried through LingBot's depth into the 3D survey. Where the geometry rules also find a dip at "
  "that spot, the two become one pothole with measured depth and size; the evidence string records both sources.")

# ------------------------------------------------------------------------------------------- 4 rules
doc.add_heading("4. Geometry rules and severity", level=1)
p("Defects are found by explicit rules on a 10 cm raster of the road surface (civil/analysis/detect.py): the road "
  "surface is fitted robustly, and cells far below or above it are grouped into candidate defects. Every finding stores "
  "the measurements that triggered it, so a reviewer can see why it was flagged. Pothole severity uses depth d and "
  "diameter D:")
table(["Severity", "Rule"], [
    ["High", "d >= 5 cm and D >= 0.45 m"],
    ["Medium", "d >= 5 cm or D >= 0.45 m"],
    ["Low", "otherwise (minimum: d >= 2.5 cm and area >= 0.04 m²)"],
], [3.0, 13.6], "Pothole severity thresholds (configurable in config/analysis.json).")
p("Geometry cannot tell every defect type apart (for example crack types, or a manhole cover sitting flush with the road); "
  "those are tagged by hand in the 3D view or supplied as labels by an external decoder.")
doc.add_heading("4.1 Following the road when the reconstruction bends", level=2)
p("A video reconstruction is not perfectly rigid: over a short hand-held clip the road can appear to bend up and down by "
  "tens of centimetres. One quadratic surface per 25 m segment cannot follow that bend, so the bend itself turns into fake "
  "deep potholes and fake heaves. For video clips the surface is therefore fitted in windows of 8 m along the walk "
  "(half-overlapping, each a robust Tukey-biweight quadratic) and blended with triangular weights; potholes, which are "
  "short, stay outliers. The setting is surface_window_m in config/video.json (0 = one fit per segment). It was added "
  "after the field test in section 12, and an automated test checks it on a synthetic ±25 cm bend with a 6 cm pothole.")
formula("surface(s) = Σ_k w_k(s) · quad_k(s, offset) / Σ_k w_k(s),   w_k(s) = max(0, 1 - |s - c_k| / 4 m)")

# ------------------------------------------------------------------------------------------- 5 condition
doc.add_heading("5. Condition index for each 25 m segment", level=1)
p("The road is cut into 25 m segments along the drive. Each open defect subtracts deduct points that grow with severity "
  "and with the share of the segment it covers; deducts are combined largest first with diminishing weight:")
formula("deduct = base[severity] x type_factor x (1 + log10(1 + density%)),   base = {low 4, medium 10, high 20}")
formula("density% = 100 x defect area / (segment length x road width)")
formula("index = max(0, 100 - Σ_i deduct_i x 0.7^i)     (deducts sorted from largest)")
figure(FIG / "f4_condition.png", "Left: one pothole's deduct by severity and size. Right: a 25 m x 7 m segment's index as potholes accumulate (computed with civil/analysis/condition.py).")
table(["Index", "Rating"], [["85-100", "good"], ["70-85", "satisfactory"], ["55-70", "fair"], ["40-55", "poor"], ["25-40", "very poor"], ["0-25", "failed"]],
      [4.0, 6.0], "Rating bands.")
p("This is a simplified deduct-value model in the spirit of a pavement condition index, not a certified ASTM D6433 PCI. "
  "The tables should be tuned to the agency's own data before the scores are used for budgeting.", italic=True)

# ------------------------------------------------------------------------------------------- 6 plans
doc.add_heading("6. Repair plans and cost", level=1)
p("Each defect type maps to a repair action with a unit and a rate (config/unit_costs.json). For area repairs the "
  "quantity is the defect area plus a 30 % saw-cut margin:")
formula("quantity = area x 1.3 ;   cost = Σ quantity x rate + mobilisation")
p("With a budget, repairs are taken in priority order until the budget is used; the rest are listed as deferred. Whole-"
  "segment treatments (resurfacing, overlay) are planned from the condition index. The rates shipped with the app are "
  "placeholders and must be replaced with real contract rates.")

doc.add_heading("6.1 Materials-only cost for each pothole", level=2)
p("The rates above are all-in placeholders. Crews asked a narrower question: what material does this hole need, and what "
  "does that material cost? civil/materials.py answers it for potholes and depressions from the measured size and depth, "
  "with no labour, equipment hire, transport, overheads or VAT. The method follows the Department of Highways (DOH) Road "
  "Maintenance Manual (2006), sections 2.5-2.6: cut a rectangle with vertical edges at least 30 cm into sound pavement on "
  "every side, down to the bottom of the damage; clean it; tack coat the floor and sides (or prime coat a new base); place "
  "the mix slightly high in layers of at most 5 cm; compact. The manual uses deep patching when the damage reaches the base "
  "but gives no depth for that, so the app's thresholds below are its own settings:")
table(["Method", "When", "What goes in"], [
    [materials.METHODS["small_patch"], f"d ≤ {MAT['max_layer_m'] * 100:.0f} cm", "cold mix in one layer; tack coat on floor and sides"],
    [materials.METHODS["layered_patch"], f"{MAT['max_layer_m'] * 100:.0f} cm < d ≤ {MAT['base_threshold_m'] * 100:.0f} cm",
     f"cold mix in layers of at most {MAT['max_layer_m'] * 100:.0f} cm, each compacted; tack coat on floor and sides"],
    [materials.METHODS["full_depth"], f"d > {MAT['base_threshold_m'] * 100:.0f} cm",
     f"crushed-rock base up to {MAT['surface_layer_m'] * 100:.0f} cm below the surface, prime coat on it, then "
     f"{MAT['surface_layer_m'] * 100:.0f} cm of cold mix in two layers; tack coat on the cut sides"],
], [5.4, 3.6, 7.6], "Repair method by depth (thresholds in config/materials.json).")
cm, tc, pc, bs = (MAT["materials"][k] for k in ("cold_mix", "tack_coat", "prime_coat", "base"))
e = MAT["cut_edge_m"]
formula(f"cut W' x L' = (W + {2 * e:.2f} m) x (L + {2 * e:.2f} m),   W x L = measured area     (DOH: 30 cm past the damage)")
formula(f"cold mix (kg) = W'L' x asphalt depth x {cm['density_kg_m3']:,} kg/m³ x (1 + {cm['compaction_allowance']})")
formula(f"bags = ceil(cold mix / {cm['bag_kg']:g} kg)")
formula(f"tack coat (L) = {tc['rate_l_m2']} L/m² x (W'L' + perimeter x asphalt depth)     (floor and sides)")
formula(f"deep patch:  base (m³) = W'L' x (d - {MAT['surface_layer_m']} m);   prime coat (L) = {pc['rate_l_m2']} L/m² x W'L'")
formula("materials cost = Σ quantity x unit price")
p(f"The rates are the DOH manual's: tack coat {tc['rate_l_m2']} L/m² of CRS-2, prime coat {pc['rate_l_m2']} L/m² of CSS-1 "
  f"on a new base, and about {cm['density_kg_m3']:,} kg of cold mix per compacted m³. The manual publishes no waste "
  f"allowance; its worked example rounds up by about 3 %, which the app uses. Because of the 30 cm margin the repair is "
  "much larger than the scanned hole: a 0.5 x 0.5 m pothole becomes a 1.1 x 1.1 m patch.")
table(["Material", "Unit", f"Price ({SYM})", "Source of the default"], [
    [f"{m['label']} ({m.get('label_th', '')})", f"bag of {m['bag_kg']:g} kg" if k == "cold_mix" else m["unit"],
     f"{m['price']:,.2f}" if m["price"] else "not set", m.get("source", "")]
    for k, m in MAT["materials"].items()
], [5.0, 2.2, 2.0, 7.4], "Default material prices, excluding VAT and transport (Research Desk, 15 Nov 2026). An admin replaces them in Settings, Material prices; the card then says \"set by your admin\".")
p("A material with no price is left out of the total and named on the card, so a missing price is never hidden as zero. "
  "No official or quoted price for crushed-rock base was found, so deep patches show their base quantity but not its cost "
  "until an admin enters a local price. The emulsion prices are bulk prices per tonne, taken as 1 kg per litre; crews "
  "buying cans pay more (48-60 THB/L in Bangkok stores). The premix default is the median of four Bangkok store listings; "
  "a producer's quote to the Department of Rural Roads was 185 THB a bag.")
p("Factor F is not offered. It covers overhead, interest, profit and VAT and contains no labour, but the Comptroller "
  "General's rules apply it to the full direct cost, labour and equipment included. Multiplying a materials-only total by "
  "it does not give a valid figure. For road contracts up to 5 million THB the current table gives about 1.36, not the 1.3 "
  "in the design brief.", italic=True)
figure(FIG / "f14_materials_by_depth.png", "Left: cold-mix bags and base rock for a 1 m² pothole as depth grows; the steps are whole bags, "
       "and the method changes at the grey lines. Right: materials cost for three pothole sizes (computed with civil/materials.py "
       "and the default prices; base rock has no price, so it adds nothing).")
ex = materials.bill({"area_m2": 1.417, "depth_max_m": 0.10}, MAT)
p(f"Worked example (the pothole in the design brief: 1.417 m², 10 cm deep). Cut {ex['cut_w_m']} x {ex['cut_l_m']} m = "
  f"{ex['cut_area_m2']} m²; method: {ex['method_label'].lower()}; {ex['mix_kg']:.0f} kg of cold mix = {ex['bags']} bags; "
  f"{ex['tack_l']} L of tack coat. Materials cost {SYM}{ex['subtotal']:,.2f}.")
import math as _m
_only = _m.ceil(1.417 * 0.10 * cm["density_kg_m3"] * (1 + cm["compaction_allowance"]) / cm["bag_kg"])
p(f"The design brief showed 18 bags for that pothole. Filling only the damaged area would take {_only} bags; the app "
  f"orders {ex['bags']} because the DOH method cuts 30 cm past the damage on every side.", italic=True)

doc.add_heading("6.2 The pothole job card on phone and iPad", level=2)
p("Tapping a pothole's cost, in the inventory, the fix-first list, a map pin or the pothole's side panel, opens its job card. "
  "On a phone or tablet it fills the screen as a sheet, with a bar of four sections at the top; on an iPad it keeps two "
  "columns; on a computer it is a centred window. The four parts follow the design brief (figure below):")
bullets([
    ("1 Location:", "a photo from the drive with the detector's boxes, the severity, the job number, the street address, the "
     "coordinates (tap to copy), a large Navigate button (Google Maps directions) and the measured size, depth and volume."),
    ("2 Cost and materials:", "the bill of materials of section 6.1, line by line with quantities and prices, the materials "
     "total, the tools needed (not costed) and what is not included."),
    ("3 Best time:", "a suggested work window from the road's class, with the reason. It is a rule of thumb, not a traffic "
     "forecast; when Google live congestion was fetched in the last 5 minutes it is shown next to it."),
    ("4 Repair plan:", "urgency from severity, a one-line hazard summary, the method and numbered steps with this pothole's "
     "own quantities, and buttons to ask Civil Helper about it, add it to a work order, send it to an engineer or show it on the map."),
])
figure(FIG / "f16_jobcard_phone.png", "The job card on a phone (390 px wide), pothole 2 of the field test (section 12). "
       "Prices are the default prices of section 6.1, not contract prices.", 16.4)
p("Choosing the photo. For video surveys every frame has a camera position from LingBot-Map, in the same frame as the "
  "findings. For a pothole at p the card takes the frame whose camera c is 2-10 m before it and looking most directly at it, "
  "and prefers frames where the detector drew a box:")
formula("score = angle(camera forward, p - c) [deg] + 6 x | |p - c| - 4.5 m |  - 10 if the frame has a detector box")
p("Only frames with the pothole within 35° of the view direction count. Detector boxes are stored in LingBot's model-image "
  "pixels and are scaled back to the frame. Pins and surveys without frames show a map tile with the spot marked.")
table(["Road class (OpenStreetMap)", "Window", "Days", "Reason shown"], [
    [", ".join(c["roads"][:6]) + ("…" if len(c["roads"]) > 6 else "") if c["roads"] else "not known yet", c["window"], c["days"], c["reason"]]
    for c in TIMING.values()
], [4.2, 2.2, 3.0, 7.2], "Suggested repair windows (config/repair_timing.json; rules of thumb that the admin can edit).")
p("The address comes from OpenStreetMap Nominatim (only the coordinates are sent, at most one request per second, cached "
  "in the server's database; off when the admin turns OpenStreetMap off). A shared pin has no 3D measurement, so the pin "
  "form and the card take an optional width, length and depth in centimetres; a pin without them shows \"Add size\".")

# ------------------------------------------------------------------------------------------- 7 priority
doc.add_heading("7. Which pothole to fix first", level=1)
p("Survey defects and shared pins go into one ranked list:")
formula("priority = severity weight x safety factor x traffic factor  (x confirmation factor for pins)")
table(["Term", "Values", "Source"], [
    ["Severity weight", "low 1.0 · medium 2.0 · high 3.5", "civil/catalog.py"],
    ["Safety factor", "pothole 1.6 · trip hazard 1.6 · sunken manhole 1.3 · heave 1.2 · depression 1.1 · other 1.0", "civil/planning.py"],
    ["Road weight", "vehicles/day entered: clamp(log10 AADT, 1, 5); else OSM class: motorway 5 · trunk 4.5 · primary 4 · secondary 3 · tertiary 2.5 · residential 1.5 · service 1; else 1", "civil/traffic.py"],
    ["Congestion", "c = Google live travel time / free-flow time; multiplier 1 + 0.5 (min(c, 3) - 1), at most 2", "civil/traffic.py"],
    ["Traffic factor", "road weight x congestion multiplier", "civil/traffic.py"],
    ["Confirmations", "1 + 0.25 x min(8, number of engineers who confirmed the pin)", "civil/priority.py"],
], [3.2, 9.6, 3.8], "Terms of the fix-first priority.")
figure(FIG / "f5_priority.png", "Left: pothole priority by severity and road class without congestion. Right: how live congestion raises the traffic factor (from the app's own functions).")
figure(FIG / "f6_road_weight.png", "Road weight from vehicles per day, compared with the OpenStreetMap road-class weights.")
p("Example: a medium pothole on a congested primary road (2.0 x 1.6 x 4 x 1.5 = 19.2) ranks above a high-severity "
  "pothole on a residential street (3.5 x 1.6 x 1.5 = 8.4). This is the behaviour the automated test "
  "test_ranking_puts_busy_roads_first checks.")
p("Google's terms do not allow storing Routes API results. Civil Scan therefore keeps congestion only in the server's "
  "memory for 5 minutes and never writes it to disk; surveys and pins store only the OpenStreetMap road class and any "
  "vehicles/day an engineer typed in. Google's pricing for this call (Compute Routes Pro, reported by Research Desk on "
  "14 Nov 2026): 5,000 requests free per month, then US$10 per 1,000. Every pothole also links to Google Maps with the "
  "traffic layer on, which needs no key.")

# ------------------------------------------------------------------------------------------- 8 verify
doc.add_heading("8. Proving a repair (before and after)", level=1)
p("Both surveys are in the same map frame, so each defect's location can be looked up in the after-repair survey. For "
  "every defect three checks run (civil/verify.py):")
bullets([("Coverage:", "the after survey has points at that location."),
         ("Re-detection:", "the after analysis has a defect of the same family within 1 m."),
         ("Surface:", "the mean height inside the old outline compared with a ring around it (reported as evidence).")])
p("A defect is verified when the spot is covered and no defect of the same family is found within 1 m; if one is, it "
  "stays \"still present\"; with fewer than 5 points at the spot it is \"not covered\".")

# ------------------------------------------------------------------------------------------- 9 accounts/security
doc.add_heading("9. Accounts, chat and privacy", level=1)
doc.add_heading("9.1 Username-only sign-in bound to the device", level=2)
p("There is no password. On the first sign-in the browser creates an ECDSA P-256 key pair whose private half cannot be "
  "exported; the server stores the public half. Every later sign-in signs a fresh, single-use server nonce. Anyone typing "
  "the same username on another device is refused until an admin resets that device.")
figure(FIG / "f8_login.png", "Sign-in: the device proves it holds the key bound to the username.")
doc.add_heading("9.2 Usernames and names are encrypted at rest", level=2)
formula("uid = \"u\" + HMAC-SHA256(index key, username)[:40 hex]      -> the key every table uses")
formula("stored name = AES-256-GCM(field key, text, associated data = column name)")
p("Both keys are derived with HKDF from one 32-byte server key (data/secrets/db.key, or the CIVIL_DB_KEY environment "
  "variable). The database file and its write-ahead log were checked byte by byte after migration: no username or name "
  "appears in clear. If the key is kept in the data folder, a copy of the whole folder can still be read; keeping the key "
  "in CIVIL_DB_KEY outside the folder means a copied database alone reveals nobody.")
doc.add_heading("9.3 Encrypted chat (Signal Protocol)", level=2)
p("Each device publishes public keys; a sender runs X3DH with the recipient's bundle and then the Double Ratchet, so every "
  "message has a new key. The server stores only ciphertext until the recipient's device confirms delivery, then deletes "
  "it (SQLite secure_delete zeroes the freed space). Plain text and keys stay in the device's IndexedDB. Both people can "
  "compare a 60-digit security code to rule out anyone in the middle.")
figure(FIG / "f7_chat.png", "One message from Ann to Bob through the relay; groups reuse the same sessions.")
p("Group chats: a company admin creates the group from the company's engineers, people they've talked to, or anyone on the "
  "server found by exact username. The sender's device encrypts each message once per member; the server checks that the "
  "sender and every recipient are members and relays each copy. The group id is inside the encryption as well as on the "
  "envelope, and a device drops a message whose two labels disagree. The server can see who is in a group, when messages "
  "are sent and their size, but not their content.")
table(["Data", "Where it is kept", "Who can read it"], [
    ["Chat text, locations, shared potholes in chat", "Each participant's device (IndexedDB)", "The participants only"],
    ["Chat in transit", "Server, as ciphertext, until delivered", "Nobody (deleted after delivery, at most 30 days)"],
    ["Usernames, names, group names", "Server database, encrypted", "Signed-in colleagues via the app"],
    ["Group membership, message timing", "Server database", "Server operator (needed for routing)"],
    ["Pothole pins and confirmations", "Server database", "Everyone signed in on the server, by design"],
    ["Survey video, point clouds, findings", "Server project folders", "Engineers of the owning company"],
    ["Google traffic results", "Server memory, 5 minutes", "Not stored"],
    ["Civil Helper questions", "Sent to the chosen LLM provider", "That provider (local Ollama by default)"],
], [5.2, 5.4, 6.0], "What is stored where.")

# ------------------------------------------------------------------------------------------- 10 helper
doc.add_heading("9.4 Creating an account: company or individual", level=2)
p("Besides the first setup and accounts that an admin adds, people can create their own account from the sign-in screen "
  "(Create account). There are two ways in:")
table(["Way in", "What happens", "Role"], [
    ["For a company: new company", "Creates the company; the creator becomes its admin. The company gets a join code "
     "(8 characters, for example LC86-JBP6) shown in Settings, Company.", "admin"],
    ["For a company: join with a code", "Puts the new account in the company whose current join code was typed. Case and "
     "dashes do not matter. A new code stops the old one; the admin can also turn joining by code off.", "engineer"],
    ["Just me (individual)", "A workspace of one: own projects, material prices and Civil Helper library, no team list. "
     "Shared pothole pins and chat by username work as for everyone. Shown to others as \"Independent\". It can be "
     "turned into a company later (Settings, Your account); that cannot be undone.", "admin of their own workspace"],
], [4.2, 9.4, 3.0], "The ways to create an account (civil/auth.py, POST /api/auth/register).")
p("The browser creates the device key before the account exists and sends its public half with the request, so the "
  "username is bound to that device in the same step: nobody can claim it between \"create\" and the first sign-in. The "
  "admin of the company that set up the server decides which kinds of sign-up are allowed (Settings, Company, Sign-up on "
  "this server; both on by default). With both off, only admins add people. A client address can create at most 10 "
  "accounts an hour.")
figure(SHOT / "create-account.png", "Create account on the sign-in screen: for a company (new, or join with a code) or just me.", 15.5)
figure(SHOT / "company-join-code.png", "A new company's admin sees the join code in Settings, with Copy, New code and Turn off.", 15.5)

doc.add_heading("10. Civil Helper: answers from your own documents", level=1)
p("Questions in the side panel are routed first. Survey questions (where, how many, cost, verified) are answered by fixed "
  "rules on the survey data. General engineering questions (starting with how should / how thick / why / explain / what is "
  "the recommended…, or addressed as \"Civil Helper, …\") go to Civil Helper.")
figure(FIG / "f9_rag.png", "Routing and retrieval-augmented answering (civil/chat.py, civil/helper.py).")
formula("score = 0.45 x BM25_normalised + 0.55 x cosine_normalised   (BM25 only when no embedding model is available)")
p("Documents are cut into passages of about 1,100 characters with 180 characters of overlap. The 6 best passages go to "
  "the model, which must cite them as [n] and never invent standards, clause numbers, quantities or prices. If the "
  "library doesn't cover the question it says so and labels anything else \"General guidance (not from your library)\". In the test, Civil Helper answered the lift-"
  "thickness question from a test document in 9.5 s on qwen3.5:9b and cited it. The provider is set per company: local "
  "Ollama (smallest Qwen by default), OpenAI or any compatible endpoint, Anthropic, or Google Gemini.")

# ------------------------------------------------------------------------------------------- 11 network
doc.add_heading("11. Who can reach the app", level=1)
table(["Mode", "Reach", "HTTPS"], [
    ["Internet (default)", "Anywhere", "Certificate files, or a reverse proxy in front"],
    ["Office network (LAN)", "Devices on the office network", "Self-signed certificate, accepted once per device"],
    ["This computer only", "Only the server itself", "Not needed"],
], [4.0, 5.6, 7.0], "Network modes chosen by the admin of the company that set up the server.")
p("The server answers only to its own host names (protection against DNS rebinding), and every request that changes "
  "data must carry a custom header that other websites cannot send.")


# ------------------------------------------------------------------------------------------- 12 field test
import json as _json
FT = _json.loads((FIG / "field_test.json").read_text())
FB = _json.loads((FIG / "field_test_before.json").read_text())
doc.add_heading("12. Field test on a real road video", level=1)
p("Video: \"Terrible potholes in Rangoon Road\", Northern Natal News (YouTube, R2Vr3R_Dpj0), "
  f"{FT['duration_s']:.0f} s, {FT['size']} at {FT['fps']:.0f} fps. It is filmed by a person walking along a gravel-patched "
  "road with large water-filled potholes, camera at about chest height. There is no GPS, so scale comes from the assumed "
  "camera height of 1.4 m. The walk is placed on Rangoon Road in Leonardsville, Ladysmith (KwaZulu-Natal): it is the only "
  "Rangoon Road in the province on OpenStreetMap, and the news outlet's name points to the same province. Which stretch "
  "was filmed and the walking direction are assumptions (section 12.3). Tested on 14 November 2026 on this computer "
  "(RTX 5080, 16 GB); placed on the map on 15 November.")
doc.add_heading("12.1 What happened at each step", level=2)
ev = FT["events"]
table(["Step", "Result"], [
    ["Detector (Roboflow, 3 frames/s)", f"{FT['frames_with_box']} of 121 sampled frames had a pothole box; {FT['detections']} boxes, "
                                         f"confidence {FT['conf_min']:.2f}-{FT['conf_max']:.2f} (median {FT['conf_median']:.2f})"],
    ["Events (2+ hits within 1 s)", "; ".join(f"{a:.1f}-{b:.1f} s ({h} hits)" for a, b, h in ev)],
    ["Clips for 3D (±10 s, merged)", ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in FT["windows"]) + " (potholes are on screen almost all the time, so one clip covers the whole video)"],
    ["LingBot-Map", f"{FT['lingbot_frames']} frames at 5 fps; {FT['lingbot'].replace('Inference done in', 'inference').strip()}; {FT['points']:,} points"],
    ["Scale and placement", "; ".join(FT["align_notes"]) if isinstance(FT["align_notes"], list) else str(FT["align_notes"])],
    ["Walked path", f"{FT['path_m']:.1f} m (about 0.5 m/s, a walking pace); one {FT['segment']['length_m']:.1f} m segment"],
], [4.6, 12.0], "Pipeline steps on the Rangoon Road video.")
figure(FIG / "f10_field_timeline.png", "Detector confidence over the video, the two confirmed events and the clip sent to LingBot-Map.")
figure(FIG / "f11_field_detections.png", "Detector boxes on four frames (confidence shown). One low-confidence box (0.49, bottom right of the first frame) is on a broken-up patch rather than a clear pothole.")
doc.add_heading("12.2 What the 3D analysis found, before and after the fix", level=2)
p("The first run found the potholes but exaggerated two of them (4.9 m across and 43 cm deep, and 2.6 m and 28 cm), "
  f"flagged two \"fire hydrants\" that do not exist, and found only 5 potholes. Figure {fig_no + 1}, middle panel, shows the cause: "
  "the reconstructed road bends by about ±25 cm along the 22 m walk, and a single surface fit read the low ends as holes. "
  "Two changes followed: the windowed surface fit (section 4.1) and a rule that a hydrant must be an isolated post "
  "(top less than 1 m across; the false ones were 3.8 m, the edge of the verge). The demo street still finds its one "
  "planted hydrant, and all 44 automated tests pass.")
def count(d, k): return d["counts"].get(k, 0)
def pot_range(d):
    ps = [f for f in d["findings"] if f["type"] == "pothole"]
    dm = [f["metrics"].get("diameter_m", 0) for f in ps]; dp = [f["metrics"].get("depth_max_m", 0) for f in ps]
    conf = sum(1 for f in ps if "pothole detector" in (f["evidence"] or ""))
    return f"{min(dm):.2f}-{max(dm):.2f} m", f"{min(dp)*100:.0f}-{max(dp)*100:.0f} cm", conf
b_d, b_z, b_c = pot_range(FB); a_d, a_z, a_c = pot_range(FT)
table(["", "First run (one fit per segment)", "After the fix (8 m windows)"], [
    ["Potholes", f"{count(FB, 'pothole')} ({b_c} confirmed by the detector)", f"{count(FT, 'pothole')} ({a_c} confirmed by the detector)"],
    ["Pothole size across", b_d, a_d],
    ["Pothole depth (max)", b_z, a_z],
    ["Raised areas (heave)", str(count(FB, "heave")), str(count(FT, "heave"))],
    ["Rough surface patches", str(count(FB, "surface_roughness")), str(count(FT, "surface_roughness"))],
    ["Fire hydrants (false)", str(count(FB, "fire_hydrant")), str(count(FT, "fire_hydrant"))],
    ["Condition index of the segment", f"{FB['segment']['condition']:.0f} ({FB['segment']['rating']})", f"{FT['segment']['condition']:.0f} ({FT['segment']['rating']})"],
], [4.6, 6.0, 6.0], "Findings on the same reconstruction, before and after the fix.")
top_fig = figure(FIG / "f12_field_topdown.png", "Top view of the reconstructed road. Left: colour. Middle: raw height, showing the bend. Right: height above the local road surface, with the findings after the fix.")
pots = [f for f in FT["findings"] if f["type"] == "pothole"]
table(["No.", "Severity", "Depth (max)", "Across", "Missing material", "Detector", "Latitude, longitude"], [
    [str(int(f["id"].split("-")[1])), f["severity"], f"{f['metrics']['depth_max_m']*100:.1f} cm", f"{f['metrics']['diameter_m']:.2f} m",
     f"{f['metrics'].get('volume_m3', 0)*1000:.0f} L", "yes" if "pothole detector" in f["evidence"] else "no",
     f"{f['lat']:.6f}, {f['lon']:.6f}"] for f in pots
], [1.2, 1.8, 2.0, 1.7, 2.4, 1.7, 5.6], f"Potholes found after the fix. The numbers match the map in figure {fig_no + 1}; positions are approximate (section 12.3).")

doc.add_heading("12.3 Where the potholes are", level=2)
p(f"Figure {fig_no + 1} puts the findings on the street. The left panel shows Rangoon Road in Leonardsville, Ladysmith; the right "
  "panel shows the surveyed stretch, with each pothole drawn as a circle of its measured size, coloured by severity and "
  "numbered as in the table above. They spread over about 22 m north-west of the Nagpur Road junction, 0.4-5.7 m from "
  "the street's centre line in OpenStreetMap. Part of that spread comes from the walk itself, which wanders across the "
  f"road, and part from the reconstruction's drift (figure {top_fig}), so treat the side of the road as approximate.")
map_fig = figure(FIG / "f13_field_map.png", "Pothole locations on Rangoon Road. Left: the neighbourhood (200 m scale bar). Right: the surveyed stretch "
       "(10 m scale bar); circles are drawn at the measured size. Map data © OpenStreetMap contributors (ODbL).")
p("How the walk was placed. The clip has no GPS, so the street is matched by name: OpenStreetMap way 854179657 is the only "
  "Rangoon Road in KwaZulu-Natal. The walk is set at the Nagpur Road junction and turned to run along the street's straight "
  "middle stretch (heading 304°, north-west). The finished survey was turned as one rigid piece: the 3D points, the camera "
  "path and every finding moved together, so no measurement changed. If the clip was filmed elsewhere on the street, or in "
  "the other direction, the pattern of potholes stays the same but its position along the street shifts.")
figure(SHOT / "map-rangoon.png", "The same survey in the app's map, with OpenStreetMap streets underneath. This browser had WebGL "
       "turned off, so the app's basic map is shown; it now draws street tiles too.", 15.5)
p("With the survey on a real street, the fix-first ranking works as it would in the field. OpenStreetMap lists Rangoon Road "
  "as residential, which gives a traffic weight of ×1.5, so each high-severity pothole scores 5.6 × 1.5 = 8.4. Google live "
  "congestion was not included because no Google Maps key is set. The public OpenStreetMap servers were overloaded during "
  "the test: the app's first two lookups for this street failed with the message that the servers are busy, and it fell "
  "back to equal road weights as designed. The same lookup run directly with the app's code then succeeded after 31-36 s "
  "and was cached, and the app's next update used that answer.")

doc.add_heading("12.4 How far to trust these numbers", level=2)
bullets([
    ("Detection: good.", "Of the boxes checked by eye, all sit on potholes except one low-confidence box (0.49) on a broken-up patch; potholes are detected in 112 of 121 sampled frames."),
    ("Counts and positions: plausible.", "Counting by eye, about 8-10 separate potholes appear in the video; the analysis finds 10, 8 of them confirmed by the detector. No ground truth exists for this clip."),
    ("Sizes and depths: indicative only.", "Scale rests on an assumed 1.4 m camera height (no GPS, no calibration), and most of these potholes hold water. "
     "Water reflects the sky and has no texture, so depth measured through it is unreliable. A 20 cm reading may be the water surface or a reflection."),
    ("Heaves and rough patches: unconfirmed.", "On a gravel-patched road some are real (loose gravel, the ridge between ruts) and some are reconstruction noise; they need a look on site."),
    ("Sizes depend on the analysis grid's angle.", "Before placing the walk by turning the finished result, we re-ran the analysis with the walk already turned "
     "to the street. The count stayed at 10 and the deepest pothole stayed at 19.7 cm, but the largest went from 2.27 m to 3.06 m across (35% larger), "
     "because the analysis grid follows the map axes rather than the road. Placement now turns the finished result, so the numbers above do not move, "
     "but this one comparison shows that sizes from a single run can be off by a third or more."),
    ("Location: approximate.", "The street is matched by name, and the stretch and direction are assumed (section 12.3)."),
    ("Condition index 0 (failed):", "consistent with the video, which shows a road that has largely broken up."),
])
p("To turn this into measurements a city can budget on: drive with a phone or dashcam that records GPS, calibrate the camera "
  "once (civil calibrate), and survey in dry weather or mark water-filled potholes for a manual depth check.", italic=True)

doc.add_heading("12.5 Materials for the Rangoon Road potholes", level=2)
p(f"With the default prices of section 6.1, the ten potholes need materials costing {SYM}{MR['total']:,.0f} in total, not counting "
  "crushed-rock base, which has no price yet. Most are "
  f"deeper than {MAT['base_threshold_m'] * 100:.0f} cm and get the deep-patch method (base rock under {MAT['surface_layer_m'] * 100:.0f} cm of cold mix). The depths here are the least certain "
  "numbers of the test (section 12.4), so the method and cost of each pothole should be checked on site before ordering.")
mrows = []
for r in MR["rows"]:
    bl = r["bill"]
    line = {x["key"]: x for x in bl["lines"]}
    mrows.append([str(r["no"]), {"full_depth": "deep patch"}.get(bl["method"], bl["method"].replace("_", " ")), f"{bl['depth_m'] * 100:.1f} cm", f"{bl['cut_area_m2']:.2f} m²",
                  str(bl["bags"]), f"{bl['tack_l']:.1f} L", f"{bl['base_m3']:.2f} m³" if bl["base_m3"] else "-",
                  f"{bl['subtotal']:,.0f}" + (" *" if bl["missing_prices"] else "")])
table(["No.", "Method", "Depth", "Cut area", "Bags", "Tack coat", "Base", f"Materials ({SYM})"], mrows,
      [1.0, 2.6, 1.6, 1.9, 1.3, 1.8, 1.8, 3.0],
      f"Bill of materials per pothole (numbers as in figure {map_fig})." + (" * a price is not set, so that material is not in the total." if any(r["bill"]["missing_prices"] for r in MR["rows"]) else ""))
figure(FIG / "f15_rangoon_materials.png", "Materials cost per pothole on Rangoon Road, split by material, with each pothole's method.")

# ------------------------------------------------------------------------------------------- 13 limits
doc.add_heading("13. Limits and what is not yet proven", level=1)
bullets([
    "One real road video has been processed end to end (section 12), filmed on foot without GPS. A vehicle-mounted drive "
    "with GPS, compared against tape-measured potholes, is still needed to know how accurate depth and size are.",
    "Depth through standing water is unreliable (reflections, no texture).",
    "Pothole sizes change with the angle of the analysis grid, which follows the map axes rather than the road: up to 35% "
    "in the field test (section 12.4). Aligning the grid with the walked path would remove this.",
    "Perspective sizes need a one-time camera calibration; until then they are hidden.",
    "The condition index is PCI-like, not certified; the all-in unit costs of section 6 are placeholders.",
    "Materials quantities rest on the measured depth, which is the least reliable measurement (water, no calibration). The "
    "rates follow the DOH manual, but the depth at which a deep patch starts (10 cm) is the app's own setting, and the "
    "premix price rests on store listings and one producer quote. Crushed-rock base has no price yet.",
    "The best-time window is a rule by road class, not a forecast; local rules on lane closures and work hours take precedence.",
    "The job card has been checked in a desktop browser at phone (390 x 844) and iPad (820 x 1180) sizes, not yet on a real "
    "phone or iPad.",
    "Google live congestion has not been tested with a real key; how precise travel-time ratios are on 25-200 m pieces "
    "of road is undocumented and needs a field test.",
    "Every message to a group of n people costs n encryptions on the sender's device; that is fine for crews of tens, "
    "not for hundreds.",
    "The bundled Signal library (libsignal-protocol-typescript) is GPL-3.0. Distributing the app outside the organisation "
    "would require releasing it under GPL-3.0 or replacing the library.",
])

# ------------------------------------------------------------------------------------------- 13 screens
doc.add_heading("14. Screens", level=1)
for f, cap in [("sign-in.png", "Sign-in with the pitch: username only."),
               ("welcome.png", "First-run welcome for an admin."),
               ("get-started.png", "The admin's Get-started checklist in Settings."),
               ("map.png", "Condition map with a strip diagram along the route (demo district, synthetic data; basic map with street tiles)."),
               ("3d-lingbot-real.png", "3D reconstruction from LingBot-Map (indoor test clip)."),
               ("fix-first.png", "Fix-first list: severity x safety x traffic, with Google Maps links and the materials cost of each pothole."),
               ("jobcard-desktop.png", "The pothole job card on a computer: a centred window with two columns."),
               ("jobcard-ipad.png", "The job card on an iPad (820 x 1180): a full-screen sheet that keeps two columns."),
               ("group-chat.png", "Encrypted group chat for a crew (test data).")]:
    if (SHOT / f).exists():
        figure(SHOT / f, cap, 15.5)
if (SHOT / "phone-chat.png").exists():
    figure(SHOT / "phone-chat.png", "The same chat on a phone (390 px wide), with worst-case data: a Thai name and an unbroken link.", 6.0)

# ------------------------------------------------------------------------------------------- 14 sources
doc.add_heading("15. Sources", level=1)
bullets([
    "LingBot-Map: Robbyant (Ant Group), arXiv:2604.14141; github.com/Robbyant/lingbot-map; Apache-2.0.",
    "Pothole detector: Roboflow Universe, \"pothole-all-conditions\" (model version 1).",
    "Field-test video: \"Terrible potholes in Rangoon Road\", Northern Natal News, YouTube (youtube.com/watch?v=R2Vr3R_Dpj0); used for testing only, not redistributed.",
    "Perspective transform method: toolcluster.app, \"OpenCV perspective transform\" (getPerspectiveTransform / warpPerspective).",
    "Signal Protocol: signal.org/docs, X3DH key agreement and Double Ratchet specifications.",
    "Google Routes API pricing and storage terms: as reported by Research Desk on 14 Nov 2026 "
    "(Shared/Project_CIVIL/research/traffic-and-rag-sources.md); confirm before production use.",
    "OpenStreetMap road classes via the Overpass API, and street addresses via Nominatim (data © OpenStreetMap contributors, ODbL).",
    "Repair method and rates: Department of Highways, Road Maintenance Manual (2006), sections 2.5-2.6.",
    "Material prices: Ministry of Commerce (TPSO) construction material prices, Bangkok area, October 2026 (index.tpso.go.th); "
    "Sola Asphalt quote to the DRR Bureau of Road Maintenance, 10 Nov 2026; four Bangkok store listings, Nov 2026. "
    "Factor F: Comptroller General's Department criteria and circular ว 481 (26 Jun 2026). All compiled by Research Desk on "
    "15 Nov 2026 (Shared/Project_CIVIL/research/repair-cost-sources.md).",
    "Job card layout: the user's design brief (IMG_1764.png, four tablet screens: Location, Cost & Material, Time Analytics, Planning), 15 Nov 2026.",
    "Field-test location: OpenStreetMap way 854179657, Rangoon Road, Leonardsville, Ladysmith, KwaZulu-Natal, found with "
    "Nominatim and Overpass on 15 Nov 2026; map tiles © OpenStreetMap contributors (ODbL).",
])

doc.save(OUT)
print(OUT)

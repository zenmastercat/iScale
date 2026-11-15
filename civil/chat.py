"""Deterministic assistant: answers questions about the inventory with rules, not a model.

It recognises a handful of intents (find/count assets and defects, condition,
worst segments, cost and budget plans, verification) from keywords and the issue
catalog's synonyms.  Every answer is computed from the project data and returns the
ids it refers to, so the UI can highlight them on the map.  It never changes data.
"""

from __future__ import annotations

import re

from . import catalog
from .planning import round_money, segment_plan, spot_plan

HELP = (
    "I answer from this project's survey data, with fixed rules (no AI model). Try:\n"
    "- `identify all the stop signs`\n"
    "- `how many high severity potholes`\n"
    "- `show trip hazards in S004`\n"
    "- `worst 3 segments`\n"
    "- `condition summary`\n"
    "- `what will it cost to fix the potholes`\n"
    "- `plan repairs with a budget of 5k`\n"
    "- `resurfacing plan with 200k`\n"
    "- `what has been verified`"
)

FIND_WORDS = ("identify", "find", "show", "list", "where", "locate", "how many", "count", "all the", "which")
COST_WORDS = ("cost", "price", "estimate", "how much", "budget", "plan", "spend", "fix")


def _money(text: str) -> float | None:
    m = re.search(r"(?:budget|with|of|\$|usd|thb|฿)\s*\$?\s*([\d][\d,\.]*)\s*([km])?\b", text)
    if not m:
        m = re.search(r"\b([\d][\d,\.]*)\s*([km])\b", text)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)
    return v * mult


def _severity(text: str) -> list[str] | None:
    sev = [s for s in catalog.SEVERITIES if re.search(rf"\b{s}\b", text)]
    if "severe" in text or "dangerous" in text or "worst" in text and "segment" not in text:
        sev = sev or ["high"]
    return sev or None


def _segment_ids(text: str, segments: list[dict]) -> list[str]:
    ids = {s["id"].lower(): s["id"] for s in segments}
    return [ids[t] for t in re.findall(r"\bs\d{3}\b", text) if t in ids]


def _fmt_finding(f: dict) -> str:
    sev = f", {f['severity']} severity" if f.get("severity") else ""
    return f"- **{catalog.CATALOG[f['type']].label}** in segment {f.get('segment_id', '?')}{sev}: {f['evidence']} ({f['id']})"


# "Civil Helper, ...", "@civil-helper ...", "Helper: ..." (and the old name "Foreman, ...") address the assistant directly.
HELPER_PREFIX = re.compile(r"^\s*@?(civil[\s_-]*helper|helper|foreman)\b[,:]?", re.I)
KNOWLEDGE_RE = re.compile(
    r"^\s*(how (do|does|should|to|thick|deep|wide|long|often|can)\b|why\b|explain\b|should\b|can (i|we)\b|"
    r"when (should|do|is)\b|what (is|are) (the )?(best|recommended|minimum|maximum|standard|typical|difference|cause|"
    r"procedure|method)|which (method|material|mix|standard|treatment) (should|is|to)\b)", re.I)
# Words that tie a question to this project's survey data rather than to general practice.
DATA_RE = re.compile(r"\b(where|how many|count|list|show|highlight|find|this (survey|street|road|project|drive)|"
                     r"segment|segments|cost|budget|price|verified|work orders?)\b", re.I)


def is_knowledge_question(message: str) -> bool:
    """General civil-engineering questions go to Civil Helper even when a survey is loaded."""
    if HELPER_PREFIX.match(message):
        return True
    return bool(KNOWLEDGE_RE.match(message)) and not DATA_RE.search(message)


def answer(message: str, analysis: dict | None, workorders: list[dict], verification: dict | None) -> dict:
    text = " " + message.lower().strip() + " "
    reply = {"reply": "", "highlight": [], "segments": [], "plan": None}
    if analysis is None:
        reply["reply"] = "There is no analysed survey in this project yet. Upload a scan or load the demo first."
        reply["matched"] = False
        return reply
    findings = analysis["findings"]
    segments = analysis["segments"]
    if is_knowledge_question(message):
        reply["matched"] = False
        return reply
    if re.search(r"\b(help|what can you|commands)\b", text) or not text.strip():
        reply["reply"] = HELP
        return reply

    types = catalog.match_type(text)
    sev = _severity(text)
    segs = _segment_ids(text, segments)
    budget = _money(text)

    # --- verification ------------------------------------------------------------
    if re.search(r"\b(verif|prove|proof|fixed|repaired|done)\w*", text) and not re.search(r"\b(cost|budget)\b", text):
        if not verification:
            reply["reply"] = "No before/after verification has been run yet. Add an after-repair survey and press **Verify**."
            return reply
        c = verification["counts"]
        res = verification["results"]
        lines = [f"Verification against the after survey: **{c['verified']} verified**, "
                 f"**{c['not_fixed']} still present**, {c['not_covered']} not covered."]
        for r in res[:12]:
            lines.append(f"- {r['finding_id']} {catalog.CATALOG[r['type']].label}: **{r['status'].replace('_', ' ')}**, {r['evidence']}")
        reply["reply"] = "\n".join(lines)
        reply["highlight"] = [r["finding_id"] for r in res]
        return reply

    # --- cost / plans --------------------------------------------------------------
    if any(w in text for w in COST_WORDS) and not re.search(r"\b(how many|count|where)\b", text):
        if re.search(r"\b(resurfac|overlay|segment|network|treatment|paving|repav)\w*", text):
            plan = segment_plan(segments, budget)
            cur = plan["currency"]
            lines = [f"Segment treatment plan{' within ' + cur + ' ' + round_money(budget) if budget else ''}: "
                     f"**{cur} {round_money(plan['total'])}** for {len(plan['items'])} segments"
                     f"{f', {len(plan["deferred"])} deferred' if plan['deferred'] else ''}."]
            for it in plan["items"][:10]:
                lines.append(f"- {it['segment_id']} (index {it['condition']}): {it['label']}, {it['area_m2']} m², {cur} {round_money(it['cost'])}")
            reply["segments"] = [i["segment_id"] for i in plan["items"]]
        else:
            fl = [f for f in findings if (not segs or f.get("segment_id") in segs)
                  and (not sev or f.get("severity") in sev)]
            plan = spot_plan(fl, budget, types=types or None)
            cur = plan["currency"]
            what = ", ".join(catalog.CATALOG[t].label.lower() for t in types) if types else "all open defects"
            if not plan["items"] and not plan["deferred"]:
                reply["reply"] = f"No open repairable defects match ({what})."
                return reply
            lines = [f"Spot repairs for {what}{' within ' + cur + ' ' + round_money(budget) if budget else ''}: "
                     f"**{cur} {round_money(plan['total'])}** for {len(plan['items'])} repairs"
                     f" (incl. {cur} {round_money(plan['mobilization'])} mobilisation)"
                     f"{f'; {len(plan["deferred"])} deferred for budget' if plan['deferred'] else ''}."]
            for a in plan["by_action"]:
                lines.append(f"- {a['label']}: {a['count']} jobs, {a['quantity']} {a['unit']}, {cur} {round_money(a['cost'])}")
            reply["highlight"] = [i["finding_id"] for i in plan["items"]]
        lines.append("\n_Unit costs are placeholders from config/unit_costs.json until you set your own rates._")
        reply["reply"] = "\n".join(lines)
        reply["plan"] = plan
        return reply

    # --- worst segments / condition --------------------------------------------------
    if re.search(r"\b(worst|poorest|lowest|bad|weakest)\b", text) and ("segment" in text or "road" in text or "street" in text):
        n = int(m.group(1)) if (m := re.search(r"\b(\d{1,2})\b", text)) else 3
        ranked = sorted([s for s in segments if s.get("condition") is not None], key=lambda s: s["condition"])[:n]
        lines = [f"The {len(ranked)} lowest-scoring segments:"]
        for s in ranked:
            lines.append(f"- **{s['id']}**: index {s['condition']} ({s['rating']}), {s['defect_count']} defects, {s['length_m']:.0f} m")
        reply["reply"] = "\n".join(lines)
        reply["segments"] = [s["id"] for s in ranked]
        return reply
    if re.search(r"\b(condition|summary|overview|status|health|how is|how are)\b", text) and not types:
        scored = [s for s in segments if s.get("condition") is not None]
        if not scored:
            reply["reply"] = "No segment has enough coverage to score."
            return reply
        length = sum(s["length_m"] for s in scored)
        avg = sum(s["condition"] * s["length_m"] for s in scored) / max(1.0, length)
        bands: dict[str, float] = {}
        for s in scored:
            bands[s["rating"]] = bands.get(s["rating"], 0) + s["length_m"]
        defects = [f for f in findings if catalog.CATALOG[f["type"]].kind == "defect"]
        assets = [f for f in findings if catalog.CATALOG[f["type"]].kind == "asset"]
        lines = [f"**{length:.0f} m** surveyed in {len(scored)} segments. Length-weighted condition index **{avg:.0f}/100**.",
                 "By rating: " + ", ".join(f"{k} {v:.0f} m" for k, v in sorted(bands.items(), key=lambda kv: -kv[1])) + ".",
                 f"{len(defects)} defects ({sum(1 for f in defects if f.get('severity') == 'high')} high severity) and {len(assets)} assets inventoried."]
        open_wo = [w for w in workorders if w["status"] in ("open", "scheduled")]
        if open_wo:
            lines.append(f"{len(open_wo)} work orders open.")
        reply["reply"] = "\n".join(lines)
        return reply

    # --- find / count ------------------------------------------------------------------
    if types or any(w in text for w in FIND_WORDS):
        if not types:
            if "defect" in text or "issue" in text or "problem" in text or "damage" in text:
                types = [t for t, it in catalog.CATALOG.items() if it.kind == "defect"]
            elif "asset" in text or "inventory" in text:
                types = [t for t, it in catalog.CATALOG.items() if it.kind == "asset"]
            else:
                reply["reply"] = "I didn't recognise what to look for. " + HELP
                reply["matched"] = False
                return reply
        # "signs" means every sign subtype
        if types == ["sign_other"]:
            types = [t for t in catalog.CATALOG if t.startswith("sign_")]
        fl = [f for f in findings if f["type"] in types and (not sev or f.get("severity") in sev)
              and (not segs or f.get("segment_id") in segs) and f.get("status") != "dismissed"]
        fl0 = fl
        def plural(lbl: str, n: int) -> str:
            if n == 1 or lbl.endswith("s") or "(" in lbl:
                return lbl
            head, sep, tail = lbl.partition(" / ")
            return head + ("es" if head.endswith(("ch", "sh", "x")) else "s") + sep + tail
        what = ", ".join(plural(catalog.CATALOG[t].label.lower(), 2 if len(types) > 1 else len(
            [f for f in fl0 if f["type"] == t])) for t in types[:4]) + ("…" if len(types) > 4 else "")
        where = f" in {', '.join(segs)}" if segs else ""
        sevtxt = f" ({'/'.join(sev)} severity)" if sev else ""
        if not fl:
            note = ""
            if any(catalog.CATALOG[t].detection == ("manual", "decoder") or "geometry" not in catalog.CATALOG[t].detection for t in types):
                note = " Geometry rules can't detect this type; tag it in the 3D view or use decoder labels."
            reply["reply"] = f"Found no {what}{sevtxt}{where}.{note}"
            return reply
        lines = [f"Found **{len(fl)}** {what}{sevtxt}{where}. {'It is' if len(fl) == 1 else 'They are'} highlighted on the map."]
        lines += [_fmt_finding(f) for f in fl[:15]]
        if len(fl) > 15:
            lines.append(f"…and {len(fl) - 15} more (see Inventory).")
        reply["reply"] = "\n".join(lines)
        reply["highlight"] = [f["id"] for f in fl]
        return reply

    reply["reply"] = "I couldn't match that to a question I can answer. " + HELP
    reply["matched"] = False
    return reply

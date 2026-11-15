"""Figures for iScale-Logic-and-Figures.docx.

Every curve is computed with the app's own modules (civil.*), so the figures show the
logic the code actually runs. Example inputs are labelled "example".
Run:  uv run python docs/build/figures.py   (writes docs/build/fig/*.png)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from civil import catalog, planning, traffic  # noqa: E402
from civil.analysis import condition  # noqa: E402
from civil.video import windows  # noqa: E402

OUT = Path(__file__).with_name("fig")
OUT.mkdir(exist_ok=True)
INK, INK2, RULE, ACTION, TINT = "#1d2622", "#5e6a64", "#d9dfdb", "#1e4f8f", "#e8eef6"
OK, LOW, MED, HIGH = "#2f7d55", "#c9a100", "#d9730d", "#b42318"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "savefig.dpi": 200, "savefig.bbox": "tight"})


def box(ax, x, y, w, h, text, fc="#ffffff", ec=RULE, bold=False, size=9.5, color=INK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06", fc=fc, ec=ec, lw=1.1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=color,
            fontweight="bold" if bold else "normal", wrap=True)


def arrow(ax, a, b, color=INK2, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=11, color=color, lw=1.2, linestyle=ls))


# 1. architecture -----------------------------------------------------------------------------
def architecture():
    fig, ax = plt.subplots(figsize=(10, 5.6))
    ax.set_xlim(0, 10), ax.set_ylim(0, 5.6), ax.axis("off")
    ax.text(0.1, 5.35, "Devices (browser)", fontsize=10, color=INK2, fontweight="bold")
    ax.text(3.6, 5.35, "Company server (iScale, FastAPI)", fontsize=10, color=INK2, fontweight="bold")
    ax.text(8.0, 5.35, "Outside services", fontsize=10, color=INK2, fontweight="bold")
    box(ax, 0.1, 3.9, 2.8, 1.2, "Engineer's browser\nmap, 3D, repairs, chat\nOMEMO keys + chat history\nin IndexedDB (this device only)", fc=TINT, ec="#cfdbec")
    box(ax, 0.1, 2.2, 2.8, 1.2, "Admin's browser\nteam, Civil Helper provider,\ntraffic, network mode", fc=TINT, ec="#cfdbec")
    box(ax, 3.5, 4.3, 4.0, 0.8, "Accounts: username + device key, sessions\nusernames/names encrypted (AES-GCM, HMAC id)")
    box(ax, 3.5, 3.35, 1.9, 0.8, "XMPP chat (ejabberd)\nOMEMO ciphertext only,\ndeleted on delivery", size=8.8)
    box(ax, 5.6, 3.35, 1.9, 0.8, "Shared pins\n+ fix-first ranking", size=8.8)
    box(ax, 3.5, 2.4, 1.9, 0.8, "Survey pipeline\ndetect, align, rules,\ncondition, plans", size=8.8)
    box(ax, 5.6, 2.4, 1.9, 0.8, "Civil Helper (RAG)\nlibrary search +\nLLM provider", size=8.8)
    box(ax, 3.5, 1.2, 4.0, 0.9, "SQLite civil.db + project folders (on this server)\nno chat content, no Google traffic stored")
    box(ax, 3.5, 0.15, 4.0, 0.75, "LingBot-Map (local GPU, separate process)\nvideo clip -> camera poses + depth", fc="#f7faf8")
    box(ax, 8.0, 4.25, 1.9, 0.8, "Roboflow detector\nused by: survey pipeline", size=8.5)
    box(ax, 8.0, 3.3, 1.9, 0.8, "OpenStreetMap\nused by: fix-first list", size=8.5)
    box(ax, 8.0, 2.35, 1.9, 0.8, "Google Routes, optional\nused by: fix-first list", size=8.5)
    box(ax, 8.0, 1.4, 1.9, 0.8, "Ollama/Qwen, or your\nLLM; used by: Civil Helper", size=8.5)
    for y in (4.5, 2.8):
        arrow(ax, (2.9, y), (3.5, y), ACTION, "<|-|>")
    ax.plot([3.5, 3.25, 3.25], [2.5, 2.5, 0.52], color=INK2, lw=1.2)
    arrow(ax, (3.25, 0.52), (3.5, 0.52), INK2)
    ax.text(3.2, 1.6, "clips", rotation=90, ha="right", va="center", fontsize=8, color=INK2)
    ax.vlines(7.75, 1.6, 4.85, color=RULE, lw=2)
    for y in (3.75, 2.8):
        ax.hlines(y, 7.5, 7.75, color=RULE, lw=2)
    for y in (4.65, 3.7, 2.75, 1.8):
        ax.hlines(y, 7.75, 8.0, color=RULE, lw=2)
    ax.text(5.0, -0.25, "Every outside service is optional and switchable by the admin. Chat stays on this server's XMPP service (no federation).",
            ha="center", fontsize=8.5, color=INK2)
    fig.savefig(OUT / "f1_architecture.png")
    plt.close(fig)


# 2. detection -> windows --------------------------------------------------------------------
def pipeline_windows():
    duration = 120.0
    rng = np.random.default_rng(7)
    hits = sorted([18.0, 18.33, 18.67, 19.0, 41.3, 41.67, 44.0, 44.33, 95.0, 95.33, 63.0])  # example
    noise = [63.0]  # a lone hit: not confirmed (min_hits = 2)
    ev = windows.events(hits, min_hits=2, hit_gap_s=1.0)
    win = windows.windows(ev, duration, before_s=10, after_s=10)
    fig, ax = plt.subplots(figsize=(10, 2.9))
    ax.set_xlim(0, duration), ax.set_ylim(0, 3), ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("time in the drive video (s), example data")
    ax.hlines(2.4, 0, duration, color=RULE, lw=6)
    ax.text(0, 2.75, "Detector samples 3 frames/s (Roboflow, confidence >= 0.45)", fontsize=9, color=INK2)
    for t in hits:
        ax.plot(t, 2.4, "o", color=HIGH if t not in noise else INK2, ms=5)
    ax.text(63, 2.0, "single hit:\nignored", ha="center", fontsize=8, color=INK2)
    for e in ev:
        ax.annotate("", xy=(e["t0"], 1.55), xytext=(e["t0"], 2.25), arrowprops=dict(arrowstyle="-|>", color=INK2))
    for w in win:
        ax.add_patch(plt.Rectangle((w["start"], 0.75), w["end"] - w["start"], 0.7, fc=TINT, ec=ACTION, lw=1.2))
        ax.text((w["start"] + w["end"]) / 2, 1.1, f"clip {w['index'] + 1}: {w['start']:.0f}-{w['end']:.0f} s\n{len(w['events'])} event(s)",
                ha="center", va="center", fontsize=8.5, color=ACTION)
    ax.text(0, 0.2, "Confirmed event = 2+ hits within 1 s.  Clip = [first hit - 10 s, last hit + 10 s], clamped to the video; "
            "overlapping clips merge.  Only clips go to LingBot-Map.", fontsize=8.5, color=INK)
    fig.savefig(OUT / "f2_windows.png")
    plt.close(fig)
    return win


# 3. perspective transform --------------------------------------------------------------------
def homography(src, dst):
    a = []
    for (x, y), (u, v) in zip(src, dst):
        a.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        a.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.array(a))
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


def perspective():
    W, H = 1280, 720
    src_f = [(0.43, 0.6), (0.08, 0.92), (0.92, 0.92), (0.57, 0.6)]  # config/video.json defaults (uncalibrated)
    width_m, length_m, near_m = 3.5, 12.0, 4.0
    src = np.array([(x * W, y * H) for x, y in src_f])
    dst = np.array([(0, length_m), (0, 0), (width_m, 0), (width_m, length_m)])  # metres: x across, y ahead of near edge
    Hm = homography(src, dst)
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.9), gridspec_kw={"width_ratios": [1.6, 1]})
    a.set_xlim(0, W), a.set_ylim(H, 0), a.set_aspect("equal"), a.set_title("Camera frame (pixels)", fontsize=10, color=INK)
    a.add_patch(plt.Rectangle((0, 0), W, H, fc="#eef1ee", ec=RULE))
    a.add_patch(Polygon(src, closed=True, fc=TINT, ec=ACTION, lw=1.5))
    for (x, y), lab in zip(src, ["TL", "BL", "BR", "TR"]):
        a.plot(x, y, "o", color=ACTION)
        a.text(x + 12, y - 10, lab, fontsize=8, color=ACTION)
    # a pothole box in the frame (example) and its mapped footprint
    pb = np.array([(560, 520), (700, 520), (700, 575), (560, 575)])
    a.add_patch(Polygon(pb, closed=True, fc="none", ec=HIGH, lw=1.6))
    a.text(560, 510, "detector box (example)", fontsize=8, color=HIGH)
    b.set_title("Top-down road plane (metres)", fontsize=10, color=INK)
    b.add_patch(plt.Rectangle((0, 0), width_m, length_m, fc=TINT, ec=ACTION, lw=1.5))
    ph = np.c_[pb, np.ones(4)] @ Hm.T
    pm = ph[:, :2] / ph[:, 2:]
    b.add_patch(Polygon(pm, closed=True, fc="none", ec=HIGH, lw=1.6))
    wid = np.linalg.norm(pm[1] - pm[0])
    ln = np.linalg.norm(pm[3] - pm[0])
    b.text(width_m + 0.2, pm[:, 1].mean(), f"~{wid:.2f} m x {ln:.2f} m\n(example; needs calibration)", fontsize=8, color=HIGH, va="center")
    b.set_xlim(-0.5, width_m + 3.2), b.set_ylim(-0.5, length_m + 0.5), b.set_aspect("equal")
    b.set_xlabel("across the lane (m)"), b.set_ylabel("ahead of the near edge (m)")
    b.text(0, -1.6, f"near edge = {near_m:.0f} m in front of the camera", fontsize=8, color=INK2)
    fig.text(0.5, -0.06, "cv2.getPerspectiveTransform(4 road points -> 3.5 m x 12 m rectangle), then warpPerspective. "
             "Corner points are the uncalibrated defaults from config/video.json.", ha="center", fontsize=9, color=INK2)
    fig.savefig(OUT / "f3_perspective.png")
    plt.close(fig)


# 4. condition index ----------------------------------------------------------------------------
def condition_fig():
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.6))
    dens = np.linspace(0, 10, 200)
    for sev, col in (("low", LOW), ("medium", MED), ("high", HIGH)):
        d = condition.BASE_DEDUCT[sev] * condition.TYPE_FACTOR["pothole"] * (1 + np.log10(1 + dens))
        a.plot(dens, d, color=col, lw=2, label=sev)
    a.set_xlabel("defect area as % of the segment's road area"), a.set_ylabel("deduct points (pothole)")
    a.set_title("One pothole's deduct", fontsize=10), a.legend(frameon=False, title="severity")
    seg_area = 25 * 7.0
    for sev, col in (("low", LOW), ("medium", MED), ("high", HIGH)):
        xs, ys = range(0, 9), []
        for n in xs:
            ds = sorted([condition.BASE_DEDUCT[sev] * (1 + math.log10(1 + 100 * 0.25 / seg_area))] * n, reverse=True)
            ys.append(max(0.0, 100 - sum(d * 0.7 ** i for i, d in enumerate(ds))))
        b.plot(list(xs), ys, "o-", color=col, lw=2, ms=4, label=sev)
    for lo, name, colr in condition.BANDS[:-1]:
        b.axhline(lo, color=RULE, lw=0.8, zorder=0)
        b.text(8.15, lo + 1, name, fontsize=7.5, color=INK2)
    b.set_xlabel("number of 0.25 m² potholes in a 25 m x 7 m segment"), b.set_ylabel("condition index (0-100)")
    b.set_title("Segment index: 100 - sum(deduct_i x 0.7^i)", fontsize=10), b.set_ylim(0, 102), b.set_xlim(0, 9)
    fig.savefig(OUT / "f4_condition.png")
    plt.close(fig)


# 5. priority ----------------------------------------------------------------------------------------
def priority_fig():
    roads = ["residential", "tertiary", "secondary", "primary", "trunk", "motorway"]
    sevs = ["low", "medium", "high"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.7), gridspec_kw={"width_ratios": [1.35, 1]})
    m = np.array([[catalog.SEVERITY_WEIGHT[s] * planning.SAFETY["pothole"] * traffic.factor(r, None) for r in roads] for s in sevs])
    im = a.imshow(m, cmap="YlOrRd", aspect="auto")
    a.set_xticks(range(len(roads)), roads, rotation=20), a.set_yticks(range(3), sevs)
    for i in range(3):
        for j in range(len(roads)):
            a.text(j, i, f"{m[i, j]:.1f}", ha="center", va="center", fontsize=8.5, color=INK if m[i, j] < 22 else "white")
    a.set_title("Pothole priority = severity x safety (1.6) x road weight", fontsize=10)
    a.spines[:].set_visible(False)
    c = np.linspace(1, 3.5, 100)
    b.plot(c, 1 + 0.5 * (np.minimum(c, 3) - 1), color=ACTION, lw=2)  # traffic.factor() without its 2-decimal rounding
    b.set_xlabel("Google congestion ratio (live time / free-flow time)"), b.set_ylabel("multiplier on road weight")
    b.set_title("Congestion term: 1 + 0.5 (min(c, 3) - 1)", fontsize=10)
    b.axvline(3, color=RULE, ls="--"), b.text(3.05, 1.1, "cap", fontsize=8, color=INK2)
    fig.savefig(OUT / "f5_priority.png")
    plt.close(fig)


def road_weight_fig():
    fig, ax = plt.subplots(figsize=(10, 3.2))
    aadt = np.logspace(1, 5.7, 200)
    ax.semilogx(aadt, [traffic.road_weight(None, x) for x in aadt], color=ACTION, lw=2, label="from vehicles/day an engineer enters")
    for name in ("residential", "tertiary", "secondary", "primary", "trunk", "motorway"):
        w = traffic.ROAD_WEIGHT[name]
        ax.axhline(w, color=RULE, lw=0.9, zorder=0)
        ax.text(12, w + 0.05, f"OSM {name}: {w}", fontsize=8, color=INK2)
    ax.set_xlabel("vehicles per day (AADT)"), ax.set_ylabel("road weight"), ax.set_ylim(0.8, 5.4)
    ax.set_title("Road weight: entered volume clamp(log10 AADT, 1, 5), else OpenStreetMap road class, else 1", fontsize=10)
    ax.legend(frameon=False, loc="lower right")
    fig.savefig(OUT / "f6_road_weight.png")
    plt.close(fig)


# 6. sequences ----------------------------------------------------------------------------------------
def lanes(ax, names, xs, top=5.2, bottom=0.2):
    for n, x in zip(names, xs):
        box(ax, x - 0.9, top, 1.8, 0.5, n, fc=TINT, ec="#cfdbec", bold=True, size=9)
        ax.vlines(x, bottom, top, color=RULE, lw=1.2, linestyles="--")


def msg(ax, x0, x1, y, text, color=INK, dashed=False):
    arrow(ax, (x0, y), (x1, y), color, ls="--" if dashed else "-")
    ax.text((x0 + x1) / 2, y + 0.1, text, ha="center", va="bottom", fontsize=8.3, color=color)


def chat_seq():
    fig, ax = plt.subplots(figsize=(10, 5.6))
    ax.set_xlim(0, 10), ax.set_ylim(0, 6.1), ax.axis("off")
    A, S, B = 1.4, 5.0, 8.6
    lanes(ax, ["Ann's browser", "XMPP server", "Bob's browser"], [A, S, B], top=5.5, bottom=0.75)
    msg(ax, B, S, 5.05, "sign in with a 1-hour iScale token (JWT)")
    msg(ax, B, S, 4.6, "publish OMEMO device list + key bundle (PEP)")
    msg(ax, A, S, 4.1, "PEP fetch: Bob's device list and bundle")
    msg(ax, S, A, 3.7, "bundle (public keys only)", INK2, True)
    ax.text(A, 3.15, "X3DH -> session\nDouble Ratchet per device;\nAES-GCM for the text", ha="center", fontsize=8.3, color=ACTION)
    msg(ax, A, S, 2.55, "OMEMO message: ciphertext + a key per device", ACTION)
    msg(ax, S, B, 2.1, "live, or offline store until Bob is back", ACTION, True)
    ax.text(B, 1.55, "decrypt, store plaintext\nin IndexedDB only", ha="center", fontsize=8.3, color=ACTION)
    ax.text(S, 1.15, "offline copy deleted on delivery;\nno archive (no MAM)", ha="center", fontsize=8.3, color=INK2)
    ax.text(5, 0.3, "Groups: a members-only XMPP room (XEP-0045) per iScale group. Ann's browser encrypts the text once and adds a key "
            "for every member's device; ejabberd lets only members in.", ha="center", fontsize=8.3, color=INK2, wrap=True)
    fig.savefig(OUT / "f7_chat.png")
    plt.close(fig)


def login_seq():
    fig, ax = plt.subplots(figsize=(10, 3.9))
    ax.set_xlim(0, 10), ax.set_ylim(0, 4.4), ax.axis("off")
    D, S = 2.0, 8.0
    lanes(ax, ["Engineer's device", "Company server"], [D, S], top=3.8)
    msg(ax, D, S, 3.35, "username (e.g. somchai.k)")
    msg(ax, S, D, 2.9, "fresh nonce (single use, 2 min)", INK2, True)
    ax.text(D, 2.3, "sign 'civil-scan-login:nonce:username'\nwith ECDSA P-256 key (non-extractable)", ha="center", fontsize=8.3, color=ACTION)
    msg(ax, D, S, 1.7, "signature (+ public key on first sign-in only)", ACTION)
    ax.text(S, 1.0, "first time: bind public key to HMAC(username)\nlater: verify signature with stored key\n-> session cookie (HttpOnly, SameSite=Strict, 30 days)",
            ha="center", fontsize=8.3, color=INK)
    fig.savefig(OUT / "f8_login.png")
    plt.close(fig)


def rag_fig():
    fig, ax = plt.subplots(figsize=(10, 3.4))
    ax.set_xlim(0, 10), ax.set_ylim(0, 3.6), ax.axis("off")
    box(ax, 0.1, 2.3, 1.9, 0.9, "Question in the\nside panel")
    box(ax, 2.5, 2.3, 2.2, 0.9, "Survey question?\n(where / how many / cost)\n-> fixed rules on the data", size=8.5)
    box(ax, 2.5, 0.6, 2.2, 1.2, "Knowledge question\n(how/why/explain, or\n'Civil Helper, ...') -> Civil Helper", size=8.5, fc=TINT, ec="#cfdbec")
    box(ax, 5.2, 0.6, 2.2, 1.2, "Library search\nBM25 keywords + embeddings\n0.45 BM25 + 0.55 cosine\ntop 6 passages", size=8.0)
    box(ax, 7.9, 0.6, 2.0, 1.2, "LLM provider\n(local Qwen via Ollama,\nor OpenAI / Anthropic /\nGemini / compatible)", size=8.3)
    box(ax, 7.9, 2.3, 2.0, 0.9, "Answer with [n]\ncitations + sources", size=8.5, fc="#f7faf8")
    arrow(ax, (2.0, 2.75), (2.5, 2.75))
    arrow(ax, (2.0, 2.6), (2.5, 1.3))
    arrow(ax, (4.7, 1.2), (5.2, 1.2))
    arrow(ax, (7.4, 1.2), (7.9, 1.2))
    arrow(ax, (8.9, 1.8), (8.9, 2.3))
    ax.text(0.1, 0.15, "Documents are split into ~1,100-character passages with 180 characters of overlap; each passage keeps its page number.",
            fontsize=8.3, color=INK2)
    fig.savefig(OUT / "f9_rag.png")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    pipeline_windows()
    perspective()
    condition_fig()
    priority_fig()
    road_weight_fig()
    chat_seq()
    login_seq()
    rag_fig()
    print("\n".join(sorted(p.name for p in OUT.glob("*.png"))))

"""Figures for the materials-only cost and the pothole job card (section 7 of the Word document).

Uses the app's own code (civil/materials.py) and config, so the figures always match the app.
Run:  .venv/bin/python docs/build/materials_figs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from civil import materials  # noqa: E402

FIG = Path(__file__).with_name("fig")
SHOT = ROOT / "docs" / "screenshots"
INK, INK2, ACTION, OK, HIGH, MED = "#1d2622", "#5e6a64", "#1e4f8f", "#2f7d55", "#b42318", "#d9730d"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": "#c9d0cc", "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False})
COLORS = {"cold_mix": ACTION, "tack_coat": "#7aa0cf", "prime_coat": "#b9cde6", "base": "#a0855b"}


def by_depth(cfg: dict) -> None:
    """Left: cold-mix bags and method by depth for a 1 m² pothole. Right: materials cost by depth for 3 sizes."""
    depths = np.arange(0.02, 0.255, 0.005)
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.8))
    bags = [materials.bill({"area_m2": 1.0, "depth_max_m": d}, cfg)["bags"] for d in depths]
    base = [materials.bill({"area_m2": 1.0, "depth_max_m": d}, cfg)["base_m3"] for d in depths]
    a.step(depths * 100, bags, where="post", color=ACTION, lw=2, label="cold-mix bags")
    a2 = a.twinx()
    a2.plot(depths * 100, base, color=COLORS["base"], lw=2, ls="--", label="crushed-rock base (m³)")
    a2.spines["top"].set_visible(False)
    a2.set_ylabel("base (m³)", color=COLORS["base"])
    for x, lbl in ((cfg["max_layer_m"] * 100, "2 layers"), (cfg["base_threshold_m"] * 100, "deep patch")):
        a.axvline(x, color="#c9d0cc", lw=1)
        a.text(x + 0.3, max(bags) * 1.02, lbl, color=INK2, fontsize=8.5)
    a.text(2.0, max(bags) * 1.02, "1 layer", color=INK2, fontsize=8.5)
    a.set_ylim(top=max(bags) * 1.1)
    a.set_xlabel("pothole depth (cm)")
    a.set_ylabel(f"bags of {cfg['materials']['cold_mix']['bag_kg']:g} kg")
    a.set_title("Materials for a 1 m² pothole", loc="left", fontsize=10.5, color=INK)
    h1, l1 = a.get_legend_handles_labels()
    h2, l2 = a2.get_legend_handles_labels()
    a.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8.5, loc="lower right")
    for area, c in ((0.25, "#7aa0cf"), (1.0, ACTION), (2.5, INK)):
        cost = [materials.bill({"area_m2": area, "depth_max_m": d}, cfg)["subtotal"] for d in depths]
        b.plot(depths * 100, cost, color=c, lw=2, label=f"{area:g} m²")
    b.set_xlabel("pothole depth (cm)")
    b.set_ylabel(f"materials cost ({cfg['symbol']})")
    b.set_title("Materials cost by size and depth", loc="left", fontsize=10.5, color=INK)
    b.legend(frameon=False, fontsize=8.5, title="measured area", title_fontsize=8.5)
    b.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    fig.tight_layout()
    fig.savefig(FIG / "f14_materials_by_depth.png", dpi=200)
    plt.close(fig)


def rangoon(cfg: dict) -> dict:
    an = json.loads((FIG / "field_test.json").read_text())
    pots = [f for f in an["findings"] if f["type"] == "pothole"]
    rows, stacks = [], {k: [] for k in COLORS}
    for f in pots:
        bl = materials.bill(f["metrics"], cfg, f.get("bbox"))
        rows.append({"no": int(f["id"].split("-")[1]), "bill": bl, "severity": f["severity"]})
        for k in COLORS:
            ln = next((x for x in bl["lines"] if x["key"] == k), None)
            stacks[k].append((ln["amount"] or 0) if ln else 0)
    fig, ax = plt.subplots(figsize=(10, 3.4))
    x = np.arange(len(rows))
    bottom = np.zeros(len(rows))
    for k, lbl in (("cold_mix", "premix cold asphalt"), ("tack_coat", "tack coat"), ("prime_coat", "prime coat"), ("base", "crushed-rock base")):
        v = np.array(stacks[k])
        if v.any():
            ax.bar(x, v, bottom=bottom, color=COLORS[k], label=lbl, width=0.65)
        bottom += v
    for i, r in enumerate(rows):
        ax.text(i, bottom[i] + max(bottom) * 0.02, f"{bottom[i]:,.0f}", ha="center", fontsize=8, color=INK)
    ax.set_xticks(x, [f"{r['no']}\n{ {'full_depth': 'deep patch'}.get(r['bill']['method'], r['bill']['method'].replace('_', ' ')) }" for r in rows], fontsize=7.5)
    ax.set_ylabel(f"materials cost ({cfg['symbol']})")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(frameon=False, fontsize=8.5, ncols=4, loc="upper left")
    ax.set_ylim(0, max(bottom) * 1.18)
    if any(r["bill"]["missing_prices"] for r in rows):
        ax.text(0.99, 0.97, "crushed-rock base: no price set, not included", transform=ax.transAxes, ha="right", va="top",
                fontsize=8, color=INK2)
    fig.tight_layout()
    fig.savefig(FIG / "f15_rangoon_materials.png", dpi=200)
    plt.close(fig)
    return {"rows": rows, "total": float(bottom.sum())}


def phone_strip() -> None:
    """The four phone screens side by side, numbered like the design brief."""
    names = [("jobcard-phone-1-location.png", "Location"), ("jobcard-phone-2-cost.png", "Cost & materials"),
             ("jobcard-phone-3-time.png", "Best time"), ("jobcard-phone-4-plan.png", "Repair plan")]
    ims = [Image.open(SHOT / n).convert("RGB") for n, _ in names if (SHOT / n).exists()]
    if len(ims) != 4:
        return
    h = 900
    ims = [im.resize((round(im.width * h / im.height), h)) for im in ims]
    pad, top = 40, 150
    W = sum(i.width for i in ims) + pad * 5
    canvas = Image.new("RGB", (W, h + top + pad), "white")
    d = ImageDraw.Draw(canvas)
    ttf = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    f_num = ImageFont.truetype(str(ttf / "DejaVuSans-Bold.ttf"), 34)
    f_lbl = ImageFont.truetype(str(ttf / "DejaVuSans.ttf"), 32)
    x = pad
    for i, (im, (_, lbl)) in enumerate(zip(ims, names)):
        cx = x + im.width // 2
        d.ellipse((cx - 30, 10, cx + 30, 70), fill=ACTION)
        d.text((cx, 40), str(i + 1), font=f_num, fill="white", anchor="mm")
        d.text((cx, 108), lbl, font=f_lbl, fill=INK, anchor="mm")
        canvas.paste(im, (x, top))
        d.rectangle((x - 1, top - 1, x + im.width, top + h), outline="#c9d0cc", width=2)
        x += im.width + pad
    canvas.save(FIG / "f16_jobcard_phone.png")


if __name__ == "__main__":
    cfg = materials.defaults()
    by_depth(cfg)
    out = rangoon(cfg)
    phone_strip()
    (FIG / "materials_rangoon.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"Rangoon Road materials total: {out['total']:,.0f}")

"""
Recreates graph_latest.jpg in the same hand-drawn sketch style,
replacing the outer "Graph of Knowing" nodes with biomedical entities
sourced from the BioMedical_KnowledgeGraph_ontology_MCP repo.

Biomedical outer nodes (6, matching original hexagonal count):
  Drug | Disease | Clinical Trial | Patient | Gene | Biomarker

Relationships driving the polygon edge triangulation
(from repo relationship CSVs):
  Drug      --[treats]--> Disease
  Disease   --[has outcome in]--> Clinical Trial
  Clinical  --[enrolls]--> Patient
  Patient   --[expressed by]--> Gene
  Gene      --[predicts via]--> Biomarker
  Biomarker --[targets]--> Drug   (closes the ring)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Circle
import numpy as np
import math

# ── helpers ──────────────────────────────────────────────────────────────────
def P(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)

def jitter(scale=0.003):
    return (np.random.randn() * scale, np.random.randn() * scale)

def sketchy_line(ax, x0, y0, x1, y1, lw=1.2, color='black', alpha=1.0, zorder=5):
    """Slightly wobbly line to mimic hand-drawn strokes."""
    n = 6
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    xs[1:-1] += np.random.randn(n - 2) * 0.003
    ys[1:-1] += np.random.randn(n - 2) * 0.003
    ax.plot(xs, ys, color=color, lw=lw, alpha=alpha, zorder=zorder,
            solid_capstyle='round')

def sketchy_circle(ax, cx, cy, r, lw=1.4, color='black', fc='white', zorder=5):
    theta = np.linspace(0, 2 * np.pi, 120)
    xs = cx + r * np.cos(theta) + np.random.randn(120) * 0.002
    ys = cy + r * np.sin(theta) + np.random.randn(120) * 0.002
    ax.fill(xs, ys, color=fc, zorder=zorder - 1)
    ax.plot(xs, ys, color=color, lw=lw, zorder=zorder)

def arrow(ax, x0, y0, x1, y1, lw=1.2, color='black', rad=0.08, zorder=7):
    dx, dy = x1 - x0, y1 - y0
    d = math.hypot(dx, dy)
    ox, oy = dx / d * 0.055, dy / d * 0.055
    ax.annotate('', xy=(x1 - ox, y1 - oy), xytext=(x0 + ox, y0 + oy),
                arrowprops=dict(arrowstyle='-|>', color=color, lw=lw,
                                connectionstyle=f'arc3,rad={rad}'), zorder=zorder)

# ── stick figure ─────────────────────────────────────────────────────────────
def stick_figure(ax, x, y, s=0.065, flip=False, zorder=12):
    d = -1 if flip else 1
    sketchy_circle(ax, x, y + s * 1.9, s * 0.38, lw=1.1, zorder=zorder)
    sketchy_line(ax, x, y + s*1.5, x, y + s*0.55, lw=1.1, zorder=zorder)
    sketchy_line(ax, x, y + s*1.2, x + d*s*0.7, y + s*0.9, lw=1.1, zorder=zorder)
    sketchy_line(ax, x, y + s*1.2, x - d*s*0.35, y + s*0.75, lw=1.1, zorder=zorder)
    sketchy_line(ax, x, y + s*0.55, x - d*s*0.45, y - s*0.4, lw=1.1, zorder=zorder)
    sketchy_line(ax, x, y + s*0.55, x + d*s*0.45, y - s*0.3, lw=1.1, zorder=zorder)

def ladder(ax, bx, by, height=0.55, width=0.07, zorder=11):
    sketchy_line(ax, bx, by, bx, by + height, lw=1.6, zorder=zorder)
    sketchy_line(ax, bx + width, by, bx + width, by + height, lw=1.6, zorder=zorder)
    n = int(height / 0.09)
    for i in range(1, n + 1):
        ry = by + i * height / (n + 1)
        sketchy_line(ax, bx, ry, bx + width, ry, lw=1.2, zorder=zorder)

# ── main drawing ──────────────────────────────────────────────────────────────
np.random.seed(42)

with plt.xkcd(scale=0.6, length=120, randomness=2):
    fig, ax = plt.subplots(figsize=(13, 13))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    ax.set_xlim(-1.45, 1.45)
    ax.set_ylim(-1.48, 1.52)
    ax.set_aspect('equal')
    ax.axis('off')

    cx, cy = 0.0, 0.0

    # ── Title ────────────────────────────────────────────────────────────────
    ax.text(0, 1.42, 'GRAPH ENGINEERING', ha='center', va='center',
            fontsize=34, fontweight='bold', color='black',
            fontfamily='DejaVu Sans')

    # ── Graph of Weights — centre geodesic sphere ─────────────────────────────
    R_sp = 0.155
    sketchy_circle(ax, cx, cy, R_sp, lw=1.6, fc='#F0F0F0', zorder=6)

    # geodesic mesh inside sphere
    n_mesh = 28
    pts = []
    for i in range(n_mesh):
        ang = 2 * math.pi * i / n_mesh + np.random.randn() * 0.05
        rr = R_sp * (0.35 + 0.65 * np.random.random())
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    for i, pi in enumerate(pts):
        for j, pj in enumerate(pts):
            if j <= i:
                continue
            d = math.hypot(pi[0] - pj[0], pi[1] - pj[1])
            if d < R_sp * 0.85:
                ax.plot([pi[0], pj[0]], [pi[1], pj[1]],
                        'k-', lw=0.25, alpha=0.55, zorder=5)
    for pt in pts:
        ax.plot(pt[0], pt[1], 'ko', markersize=1.6, zorder=6, alpha=0.8)

    # ── Graph of Doing — inner cycle ──────────────────────────────────────────
    R_do = 0.315
    DO = [('assess', 75), ('check', 10), ('decide', -55), ('act', -130), ('observe', 165)]
    do_pos = [(lbl, P(cx, cy, R_do, a)) for lbl, a in DO]

    for i in range(len(do_pos)):
        _, p0 = do_pos[i]
        _, p1 = do_pos[(i + 1) % len(do_pos)]
        arrow(ax, p0[0], p0[1], p1[0], p1[1], lw=1.1, rad=0.12)

    for lbl, pos in do_pos:
        e = mpatches.Ellipse(pos, 0.155, 0.075, color='white',
                             ec='black', lw=1.3, zorder=8)
        ax.add_patch(e)
        ax.text(pos[0], pos[1], lbl, ha='center', va='center',
                fontsize=9, color='black', zorder=9)

    # "graph of doing" annotation
    chk_pos = do_pos[1][1]  # 'check'
    ax.annotate('graph of\ndoing', xy=(chk_pos[0] + 0.04, chk_pos[1]),
                xytext=(0.68, 0.10),
                fontsize=9, color='black', style='italic',
                arrowprops=dict(arrowstyle='->', color='black', lw=1.0),
                zorder=10)

    # ── Graph of Knowing — biomedical outer ring ───────────────────────────────
    # 6 key entities from the BioMedical KG repo (foundation + clinical ontologies)
    R_K = 0.70
    BIO = [
        ('Drug',           90),
        ('Disease',        30),
        ('Clinical\nTrial', -30),
        ('Patient',        -90),
        ('Gene',          -150),
        ('Biomarker',      150),
    ]
    bio_pos = [(lbl, P(cx, cy, R_K, a)) for lbl, a in BIO]
    n_bio = len(bio_pos)

    # Main hexagon edges
    for i in range(n_bio):
        _, p0 = bio_pos[i]
        _, p1 = bio_pos[(i + 1) % n_bio]
        sketchy_line(ax, p0[0], p0[1], p1[0], p1[1], lw=1.4, zorder=5)

    # Triangulated sub-structure: midpoint junction dots + diagonals
    # (matches the triangular web in the original image)
    mid_pts = []
    for i in range(n_bio):
        _, p0 = bio_pos[i]
        _, p1 = bio_pos[(i + 1) % n_bio]
        mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        # push midpoint slightly outward
        nm = math.hypot(mx, my)
        mx_out = mx + (mx / nm) * 0.04
        my_out = my + (my / nm) * 0.04
        mid_pts.append((mx_out, my_out))
        sketchy_line(ax, p0[0], p0[1], mx_out, my_out, lw=0.9, zorder=4)
        sketchy_line(ax, p1[0], p1[1], mx_out, my_out, lw=0.9, zorder=4)
        ax.plot(mx_out, my_out, 'ko', markersize=5.5, zorder=7)

    # Inner junction dots on main nodes (large)
    for _, pos in bio_pos:
        ax.plot(pos[0], pos[1], 'ko', markersize=7, zorder=8)

    # Spokes inward from each midpoint toward inner cycle
    for mx, my in mid_pts:
        nm = math.hypot(mx, my)
        tx = mx - (mx / nm) * 0.22
        ty = my - (my / nm) * 0.22
        sketchy_line(ax, mx, my, tx, ty, lw=0.7, alpha=0.5, zorder=4)
        ax.plot(tx, ty, 'ko', markersize=4.5, zorder=6)

    # Light spokes from main nodes to do-ring area (subtle)
    for _, pos in bio_pos:
        nm = math.hypot(pos[0], pos[1])
        tx = pos[0] - (pos[0] / nm) * (R_K - R_do - 0.05)
        ty = pos[1] - (pos[1] / nm) * (R_K - R_do - 0.05)
        sketchy_line(ax, pos[0], pos[1], tx, ty, lw=0.5, alpha=0.3, zorder=3)

    # Node label boxes
    for lbl, pos in bio_pos:
        has_nl = '\n' in lbl
        bw = 0.175 if not has_nl else 0.19
        bh = 0.052 if not has_nl else 0.082
        box = FancyBboxPatch((pos[0] - bw/2, pos[1] - bh/2), bw, bh,
                             boxstyle='square,pad=0.006',
                             facecolor='white', edgecolor='black',
                             lw=1.5, zorder=9)
        ax.add_patch(box)
        ax.text(pos[0], pos[1], lbl, ha='center', va='center',
                fontsize=9.5, fontweight='bold', color='black',
                zorder=10, linespacing=1.15)

    # "graph of knowing" annotation
    dis_pos = bio_pos[1][1]  # Disease node
    ax.annotate('graph of\nknowing', xy=(dis_pos[0] + 0.08, dis_pos[1] + 0.06),
                xytext=(1.12, 0.70),
                fontsize=9, color='black', style='italic',
                arrowprops=dict(arrowstyle='->', color='black', lw=1.0),
                zorder=10)

    # ── "graph of weights" upward arrow from sphere ───────────────────────────
    ax.annotate('graph of\nweights', xy=(cx + 0.01, cy - R_sp - 0.01),
                xytext=(cx + 0.02, cy - 0.42),
                ha='center', fontsize=9, color='black', style='italic',
                arrowprops=dict(arrowstyle='->', color='black', lw=1.0),
                zorder=10)

    # ── Stick figures ─────────────────────────────────────────────────────────
    # Left figure: pushing the Gene node (lower-left)
    gene_pos = bio_pos[4][1]  # Gene at -150°
    # position figure slightly to the left of Gene, leaning right
    fig_lx = gene_pos[0] - 0.16
    fig_ly = gene_pos[1] + 0.05
    stick_figure(ax, fig_lx, fig_ly, s=0.062, flip=True, zorder=12)
    # push-arm extended toward polygon
    ax.plot([fig_lx + 0.04, fig_lx + 0.12], [fig_ly + 0.09, fig_ly + 0.04],
            'k-', lw=1.1, zorder=12)
    # vibration ticks
    ax.text(fig_lx - 0.09, fig_ly + 0.04, '))', fontsize=8, color='black', zorder=13)

    # Right figure: climbing ladder near Disease node (upper-right)
    dis_xy = bio_pos[1][1]   # Disease ~30°
    lad_x = dis_xy[0] + 0.14
    lad_y = dis_xy[1] - 0.42
    ladder(ax, lad_x, lad_y, height=0.52, width=0.065, zorder=11)
    stick_figure(ax, lad_x + 0.033, lad_y + 0.38, s=0.055, zorder=12)

    # Bottom-right figure: near Clinical Trial node
    ct_pos = bio_pos[2][1]   # Clinical Trial ~ -30°
    stick_figure(ax, ct_pos[0] + 0.16, ct_pos[1] - 0.12, s=0.052, zorder=12)

    # ── Bottom tagline ─────────────────────────────────────────────────────────
    ax.text(0, -1.28,
            'Graph of weights.    Graph of doing.    Graph of knowing.',
            ha='center', va='center', fontsize=11, color='black',
            fontfamily='DejaVu Sans', style='italic')
    # underline
    sketchy_line(ax, -0.80, -1.36, 0.80, -1.36, lw=1.8, zorder=8)

    # ── Save ──────────────────────────────────────────────────────────────────
    out = r"C:\Users\Administrator\Durable_AIOperations\graph\graph_biomedical_final.jpg"
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='white',
                format='jpg')
    plt.close()
    print("Saved:", out)

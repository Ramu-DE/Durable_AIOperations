import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from PIL import Image
import io
import numpy as np

# ── colour palette ──────────────────────────────────────────────────────────
C_BG        = "#FAFAF8"
C_ORIG_RING = "#2B2B2B"   # original outer octagon stroke
C_BIO_NODE  = "#1A6B8A"   # biomedical node fill
C_BIO_EDGE  = "#1A6B8A"
C_DO_NODE   = "#444"
C_WT_NODE   = "#888"
C_TITLE     = "#111"
C_LABEL     = "#FAFAF8"
C_DOING_LBL = "#2B2B2B"
C_ANNO      = "#C0392B"

FIG_W, FIG_H = 14, 14

# ── domain entities ──────────────────────────────────────────────────────────
# Original Graph-of-Knowing nodes (outer octagon, 6 nodes)
ORIG_NODES = ["Customer", "Policy", "Contract", "Evidence", "Risk", "Product"]

# Biomedical nodes — drawn as a second outer ring (10 nodes)
BIO_NODES = [
    "Drug", "Disease", "Gene", "Protein",
    "Patient", "Clinical\nTrial", "Biomarker",
    "Pathway", "Anatomy", "Phenotype"
]

# Graph-of-Doing cycle
DO_NODES = ["observe", "assess", "check", "decide", "act"]

def polar(cx, cy, r, angle_deg):
    a = math.radians(angle_deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)

def draw_frame(ax, bio_visible_count, highlight=None, show_walk=False):
    ax.set_facecolor(C_BG)
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.set_aspect("equal")
    ax.axis("off")

    cx, cy = 0.0, 0.0

    # ── Graph of Weights — centre sphere ────────────────────────────────────
    sphere = plt.Circle((cx, cy), 0.12, color="#CCCCCC", zorder=3, linewidth=1.2,
                         edgecolor="#888")
    ax.add_patch(sphere)
    # mesh lines suggestion
    for ang in range(0, 180, 20):
        x0, y0 = polar(cx, cy, 0.12, ang)
        x1, y1 = polar(cx, cy, 0.12, ang + 180)
        ax.plot([x0, x1], [y0, y1], color="#999", lw=0.4, zorder=4)
    for ang in range(-60, 120, 20):
        x0, y0 = polar(cx, cy, 0.12, ang)
        x1, y1 = polar(cx, cy, 0.12, ang + 180)
        ax.plot([x0, x1], [y0, y1], color="#999", lw=0.4, zorder=4)
    ax.text(cx, cy, "Graph of\nWeights", ha="center", va="center",
            fontsize=5.5, color="#333", zorder=5, fontweight="bold")

    # ── Graph of Doing — inner cycle ─────────────────────────────────────────
    R_DO = 0.28
    do_angles = [90, 18, -54, -126, -198]
    do_positions = [polar(cx, cy, R_DO, a) for a in do_angles]

    for i, (pos, label) in enumerate(zip(do_positions, DO_NODES)):
        circ = plt.Circle(pos, 0.055, color="white", zorder=6,
                          linewidth=1.2, edgecolor=C_DO_NODE)
        ax.add_patch(circ)
        ax.text(pos[0], pos[1], label, ha="center", va="center",
                fontsize=6, color=C_DO_NODE, zorder=7)

    # arrows between doing nodes
    for i in range(len(do_positions)):
        p0 = do_positions[i]
        p1 = do_positions[(i + 1) % len(do_positions)]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        d = math.hypot(dx, dy)
        ox, oy = dx / d * 0.057, dy / d * 0.057
        ax.annotate("", xy=(p1[0] - ox, p1[1] - oy),
                    xytext=(p0[0] + ox, p0[1] + oy),
                    arrowprops=dict(arrowstyle="-|>", color=C_DO_NODE,
                                   lw=0.9), zorder=5)

    # ── Graph of Knowing — original outer ring (hexagon) ─────────────────────
    R_KNOW = 0.58
    n_orig = len(ORIG_NODES)
    orig_angles = [90 + i * (360 / n_orig) for i in range(n_orig)]
    orig_positions = [polar(cx, cy, R_KNOW, a) for a in orig_angles]

    # polygon edges
    for i in range(n_orig):
        p0 = orig_positions[i]
        p1 = orig_positions[(i + 1) % n_orig]
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]],
                color=C_ORIG_RING, lw=1.0, zorder=5, linestyle="-")

    # spokes to centre
    for pos in orig_positions:
        ax.plot([cx, pos[0]], [cy, pos[1]],
                color=C_ORIG_RING, lw=0.5, zorder=4, linestyle="--", alpha=0.4)

    # node boxes
    for i, (pos, label) in enumerate(zip(orig_positions, ORIG_NODES)):
        box = FancyBboxPatch((pos[0] - 0.07, pos[1] - 0.025), 0.14, 0.05,
                             boxstyle="round,pad=0.008", linewidth=1.0,
                             edgecolor=C_ORIG_RING, facecolor="white", zorder=6)
        ax.add_patch(box)
        ax.text(pos[0], pos[1], label, ha="center", va="center",
                fontsize=7, color=C_ORIG_RING, zorder=7, fontweight="bold")

    # ── Biomedical ring ───────────────────────────────────────────────────────
    R_BIO = 0.86
    n_bio = len(BIO_NODES)
    bio_angles = [90 + i * (360 / n_bio) for i in range(n_bio)]
    bio_positions = [polar(cx, cy, R_BIO, a) for a in bio_angles]

    for i in range(min(bio_visible_count, n_bio)):
        pos = bio_positions[i]

        # edge to polygon neighbour (if both visible)
        if i > 0 and i < bio_visible_count:
            p0 = bio_positions[i - 1]
            ax.plot([p0[0], pos[0]], [p0[1], pos[1]],
                    color=C_BIO_EDGE, lw=0.9, zorder=5, alpha=0.6)
        # close polygon when all visible
        if bio_visible_count == n_bio:
            p0 = bio_positions[n_bio - 1]
            ax.plot([p0[0], pos[0]], [p0[1], pos[1]],
                    color=C_BIO_EDGE, lw=0.9, zorder=5, alpha=0.6)

        # connect to nearest orig node
        nearest = min(range(n_orig),
                      key=lambda j: math.hypot(orig_positions[j][0] - pos[0],
                                               orig_positions[j][1] - pos[1]))
        np_ = orig_positions[nearest]
        ax.plot([np_[0], pos[0]], [np_[1], pos[1]],
                color=C_BIO_EDGE, lw=0.5, zorder=4, linestyle=":", alpha=0.5)

        # node circle
        is_hi = (highlight is not None and i == highlight)
        fc = "#E8F4F8" if not is_hi else "#FFF3CD"
        ec = C_BIO_NODE if not is_hi else C_ANNO
        circ = plt.Circle(pos, 0.07, color=fc, zorder=6,
                          linewidth=1.5 if is_hi else 1.1, edgecolor=ec)
        ax.add_patch(circ)
        ax.text(pos[0], pos[1], BIO_NODES[i], ha="center", va="center",
                fontsize=5.8, color=ec if is_hi else C_BIO_NODE,
                zorder=7, fontweight="bold" if is_hi else "normal",
                linespacing=1.2)

    # ── "walk" annotation ────────────────────────────────────────────────────
    if show_walk and bio_visible_count == n_bio:
        # draw a path: Drug → drug_targets_protein → Protein → gene_associated_with_disease → Disease
        walk_indices = [0, 3, 2]   # Drug(0), Protein(3), Gene(2)
        walk_positions = [bio_positions[i] for i in walk_indices] + [orig_positions[4]]  # Risk
        for k in range(len(walk_positions) - 1):
            p0, p1 = walk_positions[k], walk_positions[k + 1]
            ax.annotate("", xy=p1, xytext=p0,
                        arrowprops=dict(arrowstyle="-|>", color=C_ANNO,
                                       lw=1.5, connectionstyle="arc3,rad=0.2"),
                        zorder=9)
        ax.text(0.62, -0.88,
                "Drug → Protein → Gene → Risk\n\"Two graphs. One walk.\"",
                ha="center", va="center", fontsize=6.5, color=C_ANNO,
                style="italic", zorder=10,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#FFF9F0",
                          edgecolor=C_ANNO, alpha=0.9))

    # ── layer labels ─────────────────────────────────────────────────────────
    ax.text(cx, cy - 0.165, "Graph of Weights", ha="center", fontsize=5.5,
            color="#777", style="italic", zorder=8)
    ax.text(cx - 0.32, cy + 0.24, "Graph of\nDoing", ha="center", fontsize=5.5,
            color=C_DO_NODE, style="italic", zorder=8)
    ax.text(0.72, 0.72, "Graph of\nKnowing", ha="center", fontsize=5.5,
            color=C_ORIG_RING, style="italic", zorder=8)
    if bio_visible_count > 0:
        ax.text(-0.78, 0.82, "Biomedical\nLayer", ha="center", fontsize=6,
                color=C_BIO_NODE, fontweight="bold", style="italic", zorder=8,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#E8F4F8",
                          edgecolor=C_BIO_NODE, alpha=0.85))

    # ── title ────────────────────────────────────────────────────────────────
    ax.set_title("GRAPH ENGINEERING  +  BIOMEDICAL DATASET",
                 fontsize=13, fontweight="bold", color=C_TITLE, pad=12)

# ── build frames ─────────────────────────────────────────────────────────────
def fig_to_pil(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor=C_BG)
    buf.seek(0)
    return Image.open(buf).copy()

frames = []

# Frame 0: original diagram only (hold 3s)
for _ in range(6):
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor(C_BG)
    draw_frame(ax, bio_visible_count=0)
    frames.append(fig_to_pil(fig))
    plt.close(fig)

# Frames 1-10: biomedical nodes appear one at a time
for n in range(1, len(BIO_NODES) + 1):
    for _ in range(2):   # hold each node briefly
        fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
        fig.patch.set_facecolor(C_BG)
        draw_frame(ax, bio_visible_count=n, highlight=n - 1)
        frames.append(fig_to_pil(fig))
        plt.close(fig)

# Frame: all nodes, no highlight (hold)
for _ in range(3):
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor(C_BG)
    draw_frame(ax, bio_visible_count=len(BIO_NODES))
    frames.append(fig_to_pil(fig))
    plt.close(fig)

# Frame: "one walk" path highlight
for _ in range(8):
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor(C_BG)
    draw_frame(ax, bio_visible_count=len(BIO_NODES), show_walk=True)
    frames.append(fig_to_pil(fig))
    plt.close(fig)

# ── save GIF ─────────────────────────────────────────────────────────────────
out_path = r"C:\Users\Administrator\Durable_AIOperations\graph\graph_biomedical.gif"

# Convert all to palette mode for GIF
palette_frames = []
for f in frames:
    palette_frames.append(f.convert("P", palette=Image.ADAPTIVE, colors=256))

palette_frames[0].save(
    out_path,
    save_all=True,
    append_images=palette_frames[1:],
    loop=0,
    duration=500,   # ms per frame
    optimize=False,
)

print(f"GIF saved: {out_path}  ({len(frames)} frames)")

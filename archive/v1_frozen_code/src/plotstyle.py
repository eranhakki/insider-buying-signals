"""Shared figure style: recessive axes/grid, validated categorical slots 1-3
(blue, orange, aqua pass the all-pairs colour-vision checks in light mode)."""
import matplotlib.pyplot as plt

BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
COLORS = {"FB_single": BLUE, "FB_cluster": AQUA, "SB": ORANGE,
          "treated": ORANGE, "control": BLUE, "diff": "#0b0b0b"}
INK, INK2 = "#0b0b0b", "#52514e"


def apply_style():
    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb",
        "axes.edgecolor": "#c9c8c3", "axes.linewidth": 0.8, "axes.grid": True, "grid.color": "#e7e6e2",
        "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.labelsize": 9.5, "axes.labelcolor": INK2,
        "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "text.color": INK, "font.family": "DejaVu Sans", "legend.frameon": False, "lines.linewidth": 2,
    })

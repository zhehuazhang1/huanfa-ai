# -*- coding: utf-8 -*-
"""Board 3 — "Ink Bloom" (墨色绽放): a five-petal blossom in sumi ink with a vermilion bud."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from brand_lib import build_board, draw_petal, SCALE

CREAM     = (244, 237, 224)
CREAM_2   = (236, 227, 210)
INK       = (28, 28, 26)
INK_SOFT  = (135, 129, 117)
VERMILION = (184, 71, 46)
GOLD      = (201, 163, 104)

PALETTE = {
    'cream': CREAM, 'cream2': CREAM_2, 'ink': INK, 'ink_soft': INK_SOFT,
    'vermilion': VERMILION, 'gold': GOLD, 'word_color': INK,
    'reversed_bg': INK,
}


def symbol_bloom(img, d, cx, cy, R, palette, mode):
    petal_color = palette['cream'] if mode == "reversed" else palette['ink']
    accent = palette['vermilion']
    n = 5
    length = R * 0.92
    width = R * 0.34
    for i in range(n):
        angle = -90 + i * (360 / n)
        color = accent if i == 0 else petal_color
        draw_petal(d, cx, cy, length, width, angle, color)
    gr = R * 0.075
    d.ellipse([cx-gr, cy-gr, cx+gr, cy+gr], fill=palette['gold'])


SWATCHES = [
    ("SUMI INK", INK, "#1C1C1A"),
    ("VERMILION", VERMILION, "#B8472E"),
    ("GILT", GOLD, "#C9A368"),
    ("BONE", CREAM, "#F4EDE0"),
]

build_board(
    out_path=r"C:\Users\73177\Documents\美发\landing\brand\board_v3.png",
    palette=PALETTE,
    symbol_fn=symbol_bloom,
    wordmark_font_size=192,
    wordmark_tracking=int(6*SCALE),
    latin_text="H U A N F A",
    fig_en="FIG. 03 — PRIMARY MARK",
    fig_zh="焕发 · 墨色绽放",
    ref_text="PB · 03 / 04",
    swatches=SWATCHES,
)

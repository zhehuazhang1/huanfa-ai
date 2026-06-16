# -*- coding: utf-8 -*-
"""Board 4 — "Radiant Comb" (焕芒光梳): a sunburst of comb teeth around a lit center."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from brand_lib import build_board, radial_tooth, SCALE

CREAM    = (244, 237, 224)
CREAM_2  = (236, 227, 210)
CHARCOAL = (32, 35, 31)
INK_SOFT = (135, 129, 117)
BRASS    = (176, 141, 87)
ROSE     = (205, 176, 164)

PALETTE = {
    'cream': CREAM, 'cream2': CREAM_2, 'ink': CHARCOAL, 'ink_soft': INK_SOFT,
    'charcoal': CHARCOAL, 'brass': BRASS, 'rose': ROSE, 'word_color': CHARCOAL,
    'reversed_bg': CHARCOAL,
}


def symbol_comb(img, d, cx, cy, R, palette, mode):
    center_color = palette['cream'] if mode == "reversed" else palette['charcoal']
    tooth_color = palette['brass']
    rose = palette['rose']
    r0 = R * 0.46
    d.ellipse([cx-r0, cy-r0, cx+r0, cy+r0], fill=center_color)
    n = 32
    for i in range(n):
        angle = -90 + i * (360 / n)
        long_tooth = (i % 4 == 0)
        r1 = r0 + (R*0.52 if long_tooth else R*0.32)
        base_w = R*0.034 if long_tooth else R*0.020
        col = rose if i == 0 else tooth_color
        radial_tooth(d, cx, cy, angle, r0 + R*0.015, r1, base_w, col)


SWATCHES = [
    ("CHARCOAL", CHARCOAL, "#20231F"),
    ("BRASS", BRASS, "#B08D57"),
    ("ROSE", ROSE, "#CDB0A4"),
    ("BONE", CREAM, "#F4EDE0"),
]

build_board(
    out_path=r"C:\Users\73177\Documents\美发\landing\brand\board_v4.png",
    palette=PALETTE,
    symbol_fn=symbol_comb,
    wordmark_font_size=192,
    wordmark_tracking=int(6*SCALE),
    latin_text="H U A N F A",
    fig_en="FIG. 04 — PRIMARY MARK",
    fig_zh="焕发 · 焕芒光梳",
    ref_text="PB · 04 / 04",
    swatches=SWATCHES,
)

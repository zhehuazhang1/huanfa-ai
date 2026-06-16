# -*- coding: utf-8 -*-
"""Board 2 — "Lacquer Knot" (漆韵丝结): a tied silk-ribbon knot in lacquer red and gilt."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from PIL import Image, ImageDraw
from brand_lib import build_board, SCALE

CREAM    = (244, 237, 224)
CREAM_2  = (236, 227, 210)
INK      = (43, 43, 40)
INK_SOFT = (135, 129, 117)
LACQUER  = (92, 27, 27)
GOLD     = (201, 163, 104)
DUSTROSE = (197, 166, 158)

PALETTE = {
    'cream': CREAM, 'cream2': CREAM_2, 'ink': INK, 'ink_soft': INK_SOFT,
    'lacquer': LACQUER, 'gold': GOLD, 'word_color': LACQUER,
    'reversed_bg': LACQUER,
}


def draw_ring(img, cx, cy, rx, ry, thickness, angle_deg, fill):
    pad = int(max(rx, ry) * 2.4) + 2
    size = pad * 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([pad-rx, pad-ry, pad+rx, pad+ry], fill=fill)
    ld.ellipse([pad-rx+thickness, pad-ry+thickness, pad+rx-thickness, pad+ry-thickness], fill=(0, 0, 0, 0))
    layer = layer.rotate(angle_deg, resample=Image.BICUBIC, center=(pad, pad))
    img.alpha_composite(layer, (int(cx-pad), int(cy-pad)))


def symbol_lacquer(img, d, cx, cy, R, palette, mode):
    loop = palette['cream'] if mode == "reversed" else palette['lacquer']
    gold = palette['gold']
    rx, ry = R*0.58, R*0.92
    thick = R*0.17
    off = R*0.20
    draw_ring(img, cx-off, cy, rx, ry, thick, -24, (*loop, 255))
    draw_ring(img, cx+off, cy, rx, ry, thick, 24, (*loop, 255))
    # gilt edge tracing the right-hand loop
    draw_ring(img, cx+off, cy, rx+R*0.045, ry+R*0.045, R*0.022, 24, (*gold, 255))
    # knot jewel at the crossing point
    gr = R*0.075
    d.ellipse([cx-gr, cy-gr, cx+gr, cy+gr], fill=gold)


SWATCHES = [
    ("LACQUER", LACQUER, "#5C1B1B"),
    ("GILT", GOLD, "#C9A368"),
    ("DUST ROSE", DUSTROSE, "#C5A69E"),
    ("BONE", CREAM, "#F4EDE0"),
]

build_board(
    out_path=r"C:\Users\73177\Documents\美发\landing\brand\board_v2.png",
    palette=PALETTE,
    symbol_fn=symbol_lacquer,
    wordmark_font_size=192,
    wordmark_tracking=int(6*SCALE),
    latin_text="H U A N F A",
    fig_en="FIG. 02 — PRIMARY MARK",
    fig_zh="焕发 · 漆韵丝结",
    ref_text="PB · 02 / 04",
    swatches=SWATCHES,
)

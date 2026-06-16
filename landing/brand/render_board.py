# -*- coding: utf-8 -*-
"""
Patina Bloom — 焕发 brand mark presentation board.
Renders at 4x supersample, then downsamples for crisp anti-aliasing.
"""
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------------------------------------------------------- palette
CREAM      = (244, 237, 224)      # bone / ivory ground
CREAM_2    = (236, 227, 210)      # slightly deeper panel tone
EMERALD    = (15, 41, 32)         # patina deep green
GOLD       = (201, 163, 104)      # antique gilt
GOLD_LT    = (224, 197, 145)
CELADON    = (172, 197, 182)      # pale aged green
INK        = (43, 43, 40)         # fine print charcoal
INK_SOFT   = (135, 129, 117)

SCALE = 4
W, H = 2400 * SCALE, 3000 * SCALE

FONT_DIR = r"C:\Users\73177\AppData\Roaming\Claude\local-agent-mode-sessions\skills-plugin\29306f43-241c-4563-9127-1d7e231b9324\71ede80d-e8fb-4746-a277-a68089573636\skills\canvas-design\canvas-fonts"
KAI = r"C:\Windows\Fonts\simkai.ttf"
YAHEI_L = r"C:\Windows\Fonts\msyhl.ttc"

def F(name, size):
    return ImageFont.truetype(f"{FONT_DIR}\\{name}", size * SCALE)

def FK(size):
    return ImageFont.truetype(KAI, size * SCALE)

def FY(size):
    return ImageFont.truetype(YAHEI_L, size * SCALE)

img = Image.new("RGB", (W, H), CREAM)
draw = ImageDraw.Draw(img)

# ---------------------------------------------------------------- helpers
def text_w(d, s, font, tracking=0):
    w = 0
    for ch in s:
        bbox = d.textbbox((0, 0), ch, font=font)
        w += (bbox[2] - bbox[0]) + tracking
    return w - (tracking if s else 0)

def draw_tracked(d, xy, s, font, fill, tracking=0, anchor_center=None):
    x, y = xy
    if anchor_center is not None:
        total = text_w(d, s, font, tracking)
        x = anchor_center - total / 2
    for ch in s:
        d.text((x, y), ch, font=font, fill=fill)
        bbox = d.textbbox((0, 0), ch, font=font)
        x += (bbox[2] - bbox[0]) + tracking
    return x

def draw_mixed_center(d, y, parts, anchor_center):
    """parts: list of (text, font, fill, tracking)"""
    total = 0
    for s, font, fill, tracking in parts:
        total += text_w(d, s, font, tracking)
    x = anchor_center - total / 2
    for s, font, fill, tracking in parts:
        x = draw_tracked(d, (x, y), s, font, fill, tracking)
    return x

def draw_enso(d, cx, cy, radius, base_w, color, start_deg, end_deg, steps=900,
              start_taper=0.10, end_taper=0.10, start_min=0.18, end_min=0.45):
    for i in range(steps):
        t = i / (steps - 1)
        ang = math.radians(start_deg + (end_deg - start_deg) * t)
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        if t < start_taper:
            w = base_w * (start_min + (1 - start_min) * (t / start_taper))
        elif t > 1 - end_taper:
            w = base_w * (end_min + (1 - end_min) * ((1 - t) / end_taper))
        else:
            w = base_w
        r = w / 2
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)

def bezier_stroke(d, p0, p1, p2, p3, w, color, steps=700, taper=0.08, tmin=0.2):
    for i in range(steps):
        t = i / (steps - 1)
        mt = 1 - t
        x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
        y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
        if t < taper:
            ww = w * (tmin + (1-tmin)*(t/taper))
        elif t > 1-taper:
            ww = w * (tmin + (1-tmin)*((1-t)/taper))
        else:
            ww = w
        r = ww/2
        d.ellipse([x-r, y-r, x+r, y+r], fill=color)

# ================================================================== FRAME
margin = int(190 * SCALE)
frame_inset = int(70 * SCALE)
draw.rectangle([frame_inset, frame_inset, W-frame_inset, H-frame_inset],
               outline=INK_SOFT, width=int(1.2*SCALE))
# corner ticks
tick = int(18*SCALE)
for cxp, cyp, dx, dy in [(frame_inset, frame_inset, 1, 1),
                          (W-frame_inset, frame_inset, -1, 1),
                          (frame_inset, H-frame_inset, 1, -1),
                          (W-frame_inset, H-frame_inset, -1, -1)]:
    draw.line([(cxp, cyp), (cxp+dx*tick, cyp)], fill=INK_SOFT, width=int(1.2*SCALE))
    draw.line([(cxp, cyp), (cxp, cyp+dy*tick)], fill=INK_SOFT, width=int(1.2*SCALE))

# ================================================================== TOP MARK
cx, cy = W // 2, int(880 * SCALE)
R = int(420 * SCALE)

GAP_START = 314   # degrees where the stroke ends (gap begins)
GAP_END   = 360   # degrees where the stroke resumes (gap ends, == start_deg)

# the enso — open circle, gap at upper right
draw_enso(draw, cx, cy, R, base_w=36 * SCALE, color=EMERALD,
          start_deg=GAP_END, end_deg=GAP_END+316,
          start_taper=0.05, end_taper=0.16, start_min=0.35, end_min=0.10)

# a single flowing hair-strand line, thin, celadon, arcing through the lower
# field and exiting near the gap
p0 = (cx - R*0.95, cy + R*0.50)
p1 = (cx - R*0.05, cy + R*0.98)
p2 = (cx + R*0.58, cy - R*0.02)
p3 = (cx + R*0.86, cy - R*0.55)
bezier_stroke(draw, p0, p1, p2, p3, w=4.5*SCALE, color=CELADON, taper=0.14, tmin=0.32)

# gilded edge — a fine gold thread tracing just inside the main ring,
# following the same sweep, like light caught on a worn rim
draw_enso(draw, cx, cy, R - int(20*SCALE), base_w=4.5*SCALE, color=GOLD,
          start_deg=GAP_END, end_deg=GAP_END+316,
          start_taper=0.05, end_taper=0.16, start_min=0.0, end_min=0.0)

# small gilded drop at the upper terminus of the main ring
gx = cx + R * math.cos(math.radians(GAP_START))
gy = cy + R * math.sin(math.radians(GAP_START))
gr = 12 * SCALE
draw.ellipse([gx-gr, gy-gr, gx+gr, gy+gr], fill=GOLD)

# ================================================================== WORDMARK
wm_font = FK(192)
wm_y = cy + R + int(150 * SCALE)
draw_tracked(draw, (0, wm_y), "焕发", wm_font, EMERALD, tracking=int(6*SCALE), anchor_center=cx)

# latin tracked caps below
lat_font = F("Italiana-Regular.ttf", 44)
lat_y = wm_y + int(290 * SCALE)
draw_tracked(draw, (0, lat_y), "H U A N F A", lat_font, INK_SOFT, tracking=int(10*SCALE), anchor_center=cx)

# ================================================================== RULE + ANNOTATION
rule_y = lat_y + int(170 * SCALE)
draw.line([(margin, rule_y), (W - margin, rule_y)], fill=INK_SOFT, width=int(1.2*SCALE))

mono = F("DMMono-Regular.ttf", 24)
yahei_s = FY(24)
ann_y = rule_y + int(30 * SCALE)
draw_mixed_center(draw, ann_y, [
    ("FIG. 01 — PRIMARY MARK", mono, INK_SOFT, 0),
    ("   ·   ", mono, INK_SOFT, 0),
    ("焕发品牌标志系统", yahei_s, INK_SOFT, int(2*SCALE)),
], anchor_center=None) if False else None

# left/right aligned annotation (kept simple, two-script)
left_parts = [("FIG. 01 — PRIMARY MARK", mono, INK_SOFT, 0),
               ("   ", mono, INK_SOFT, 0),
               ("焕发 · 品牌标志", yahei_s, INK_SOFT, int(2*SCALE))]
x = margin
for s, font, fill, tracking in left_parts:
    x = draw_tracked(draw, (x, ann_y), s, font, fill, tracking)

ref_text = "PB · 01 / 04"
rw = text_w(draw, ref_text, mono)
draw.text((W - margin - rw, ann_y), ref_text, font=mono, fill=INK_SOFT)

# ================================================================== BOTTOM GRID
grid_top = ann_y + int(130 * SCALE)
grid_bottom = H - frame_inset - int(130 * SCALE)
col_gap = int(60 * SCALE)
col_w = (W - 2*margin - 2*col_gap) // 3

label_mono = F("DMMono-Regular.ttf", 22)
label_yahei = FY(22)

def panel(x0, y0, x1, y1):
    draw.rectangle([x0, y0, x1, y1], fill=CREAM_2)

def col_label(cx_center, y_top, en, zh):
    draw_tracked(draw, (0, y_top), en, label_mono, INK_SOFT, tracking=int(6*SCALE), anchor_center=cx_center)
    draw_tracked(draw, (0, y_top + int(40*SCALE)), zh, label_yahei, INK_SOFT, tracking=int(2*SCALE), anchor_center=cx_center)

label_h = int(110*SCALE)

# --- column 1: reversed mark on emerald disc
c1x0, c1y0 = margin, grid_top
c1x1, c1y1 = margin + col_w, grid_bottom
panel(c1x0, c1y0, c1x1, c1y1)
content_h = (c1y1 - c1y0) - label_h
disc_r = int(min(col_w, content_h) * 0.30)
ccx, ccy = (c1x0+c1x1)//2, c1y0 + content_h//2
draw.ellipse([ccx-disc_r, ccy-disc_r, ccx+disc_r, ccy+disc_r], fill=EMERALD)
inner_r = int(disc_r*0.60)
draw_enso(draw, ccx, ccy, inner_r, base_w=12*SCALE, color=CREAM,
          start_deg=GAP_END, end_deg=GAP_END+316, start_taper=0.05, end_taper=0.16,
          start_min=0.35, end_min=0.10)
gx2 = ccx + inner_r * math.cos(math.radians(GAP_START))
gy2 = ccy + inner_r * math.sin(math.radians(GAP_START))
gr2 = 5.5*SCALE
draw.ellipse([gx2-gr2, gy2-gr2, gx2+gr2, gy2+gr2], fill=GOLD)
col_label((c1x0+c1x1)//2, c1y1 - label_h + int(20*SCALE), "REVERSED", "反白标准色")

# --- column 2: horizontal lockup
c2x0, c2y0 = margin + col_w + col_gap, grid_top
c2x1, c2y1 = c2x0 + col_w, grid_bottom
panel(c2x0, c2y0, c2x1, c2y1)
content_h2 = (c2y1 - c2y0) - label_h
lock_cy = c2y0 + content_h2//2
pad2 = int(70*SCALE)
avail_w = (c2x1 - c2x0) - 2*pad2
mark_r = int(content_h2 * 0.22)
hf = FK(int(mark_r*1.65/SCALE))
hf_w = text_w(draw, "焕发", hf, tracking=int(4*SCALE))
total_w = mark_r*2 + int(34*SCALE) + hf_w
if total_w > avail_w:
    fct = avail_w / total_w
    mark_r = int(mark_r * fct)
    hf = FK(int(mark_r*1.65/SCALE))
    hf_w = text_w(draw, "焕发", hf, tracking=int(4*SCALE))
    total_w = mark_r*2 + int(34*SCALE) + hf_w
start_x = (c2x0+c2x1)//2 - total_w//2
mark_cx = start_x + mark_r
draw_enso(draw, mark_cx, lock_cy, mark_r, base_w=10*SCALE, color=EMERALD,
          start_deg=GAP_END, end_deg=GAP_END+316, start_taper=0.05, end_taper=0.16,
          start_min=0.35, end_min=0.10)
gx3 = mark_cx + mark_r*math.cos(math.radians(GAP_START))
gy3 = lock_cy + mark_r*math.sin(math.radians(GAP_START))
gr3 = 4.5*SCALE
draw.ellipse([gx3-gr3,gy3-gr3,gx3+gr3,gy3+gr3], fill=GOLD)
text_y = lock_cy - (draw.textbbox((0,0),"焕",font=hf)[3] - draw.textbbox((0,0),"焕",font=hf)[1])//2 - int(6*SCALE)
draw_tracked(draw, (mark_cx + mark_r + int(34*SCALE), text_y), "焕发", hf, EMERALD, tracking=int(4*SCALE))
col_label((c2x0+c2x1)//2, c2y1 - label_h + int(20*SCALE), "HORIZONTAL LOCKUP", "横版组合")

# --- column 3: palette
c3x0, c3y0 = margin + 2*(col_w+col_gap), grid_top
c3x1, c3y1 = c3x0 + col_w, grid_bottom
panel(c3x0, c3y0, c3x1, c3y1)
content_h3 = (c3y1 - c3y0) - label_h
swatches = [
    ("PATINA",  EMERALD, "#0F2920"),
    ("GILT",    GOLD,    "#C9A368"),
    ("CELADON", CELADON, "#ACC5B6"),
    ("BONE",    CREAM,   "#F4EDE0"),
]
pad = int(36*SCALE)
gap_v = int(14*SCALE)
sw_h = (content_h3 - gap_v*(len(swatches)-1)) // len(swatches)
for i, (name, col, hexv) in enumerate(swatches):
    y0 = c3y0 + i*(sw_h+gap_v)
    y1 = y0 + sw_h
    draw.rectangle([c3x0 + pad, y0, c3x1 - pad, y1], fill=col,
                   outline=INK_SOFT if col == CREAM else None, width=int(1*SCALE))
    txt_color = CREAM if sum(col) < 380 else INK
    draw.text((c3x0+pad+int(18*SCALE), y0 + int(18*SCALE)), name, font=F("DMMono-Regular.ttf", 22), fill=txt_color)
    tw = text_w(draw, hexv, F("DMMono-Regular.ttf", 22))
    draw.text((c3x1 - pad - int(18*SCALE) - tw, y1 - int(46*SCALE)), hexv, font=F("DMMono-Regular.ttf", 22), fill=txt_color)
col_label((c3x0+c3x1)//2, c3y1 - label_h + int(20*SCALE), "PALETTE", "色板")

# ---------------------------------------------------------------- save
img = img.resize((2400, 3000), Image.LANCZOS)
out = r"C:\Users\73177\Documents\美发\landing\brand\board_v1.png"
img.save(out)
print("saved", out)

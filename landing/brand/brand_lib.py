# -*- coding: utf-8 -*-
"""Shared helpers for 焕发 brand-mark presentation boards."""
import math
from PIL import Image, ImageDraw, ImageFont

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


def bezier_pt(p0, p1, p2, p3, t):
    mt = 1 - t
    x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
    y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
    return x, y


def quad_bezier_pt(p0, p1, p2, t):
    mt = 1 - t
    x = mt**2*p0[0] + 2*mt*t*p1[0] + t**2*p2[0]
    y = mt**2*p0[1] + 2*mt*t*p1[1] + t**2*p2[1]
    return x, y


def bezier_stroke(d, p0, p1, p2, p3, w, color, steps=700, taper=0.08, tmin=0.2):
    for i in range(steps):
        t = i / (steps - 1)
        x, y = bezier_pt(p0, p1, p2, p3, t)
        if t < taper:
            ww = w * (tmin + (1-tmin)*(t/taper))
        elif t > 1-taper:
            ww = w * (tmin + (1-tmin)*((1-t)/taper))
        else:
            ww = w
        r = ww/2
        d.ellipse([x-r, y-r, x+r, y+r], fill=color)


def rotate_pt(x, y, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return x*ca - y*sa, x*sa + y*ca


def petal_points(length, width, steps=60):
    """A symmetric teardrop/petal pointing toward -y, base at origin."""
    p_base = (0, 0)
    p_tip = (0, -length)
    cR = (width, -length*0.50)
    cL = (-width, -length*0.50)
    pts = []
    for i in range(steps):
        t = i/(steps-1)
        pts.append(quad_bezier_pt(p_base, cR, p_tip, t))
    for i in range(1, steps):
        t = i/(steps-1)
        pts.append(quad_bezier_pt(p_tip, cL, p_base, t))
    return pts


def draw_petal(d, cx, cy, length, width, angle_deg, color):
    pts = petal_points(length, width)
    out = []
    for x, y in pts:
        rx, ry = rotate_pt(x, y, angle_deg)
        out.append((cx+rx, cy+ry))
    d.polygon(out, fill=color)


def draw_rotated_ellipse(base_img, cx, cy, rx, ry, angle_deg, fill):
    """Draw a filled ellipse rotated by angle_deg, alpha-composited onto base_img."""
    pad = int(max(rx, ry) * 2.4)
    size = pad*2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([pad-rx, pad-ry, pad+rx, pad+ry], fill=fill)
    layer = layer.rotate(angle_deg, resample=Image.BICUBIC, center=(pad, pad))
    base_img.alpha_composite(layer, (int(cx-pad), int(cy-pad)))


# ---------------------------------------------------------------- board frame

def new_canvas(cream):
    img = Image.new("RGBA", (W, H), (*cream, 255))
    return img


def draw_frame(d, ink_soft):
    frame_inset = int(70 * SCALE)
    d.rectangle([frame_inset, frame_inset, W-frame_inset, H-frame_inset],
                 outline=ink_soft, width=int(1.2*SCALE))
    tick = int(18*SCALE)
    for cxp, cyp, dx, dy in [(frame_inset, frame_inset, 1, 1),
                              (W-frame_inset, frame_inset, -1, 1),
                              (frame_inset, H-frame_inset, 1, -1),
                              (W-frame_inset, H-frame_inset, -1, -1)]:
        d.line([(cxp, cyp), (cxp+dx*tick, cyp)], fill=ink_soft, width=int(1.2*SCALE))
        d.line([(cxp, cyp), (cxp, cyp+dy*tick)], fill=ink_soft, width=int(1.2*SCALE))
    return frame_inset


def col_label(d, cx_center, y_top, en, zh, ink_soft):
    draw_tracked(d, (0, y_top), en, F("DMMono-Regular.ttf", 22), ink_soft, tracking=int(6*SCALE), anchor_center=cx_center)
    draw_tracked(d, (0, y_top + int(40*SCALE)), zh, FY(22), ink_soft, tracking=int(2*SCALE), anchor_center=cx_center)


def panel(d, x0, y0, x1, y1, color):
    d.rectangle([x0, y0, x1, y1], fill=color)


def radial_tooth(d, cx, cy, angle_deg, r0, r1, base_w, color, taper_to=0.32, steps=60):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    for i in range(steps):
        t = i/(steps-1)
        r = r0 + (r1-r0)*t
        x, y = cx + r*ca, cy + r*sa
        w = base_w * (1 - (1-taper_to)*t)
        rr = w/2
        d.ellipse([x-rr, y-rr, x+rr, y+rr], fill=color)


# ---------------------------------------------------------------- generic board builder

def build_board(out_path, palette, symbol_fn, wordmark_font_size, wordmark_tracking,
                 latin_text, fig_en, fig_zh, ref_text, swatches):
    cream      = palette['cream']
    cream2     = palette['cream2']
    ink        = palette['ink']
    ink_soft   = palette['ink_soft']
    word_color = palette['word_color']

    img = new_canvas(cream)
    d = ImageDraw.Draw(img)
    frame_inset = draw_frame(d, ink_soft)

    cx, cy = W // 2, int(880 * SCALE)
    R = int(420 * SCALE)
    symbol_fn(img, d, cx, cy, R, palette, "primary")

    wm_font = FK(wordmark_font_size)
    wm_y = cy + R + int(150 * SCALE)
    draw_tracked(d, (0, wm_y), "焕发", wm_font, word_color, tracking=wordmark_tracking, anchor_center=cx)

    lat_font = F("Italiana-Regular.ttf", 44)
    lat_y = wm_y + int(290 * SCALE)
    draw_tracked(d, (0, lat_y), latin_text, lat_font, ink_soft, tracking=int(10*SCALE), anchor_center=cx)

    rule_y = lat_y + int(170 * SCALE)
    margin = int(190 * SCALE)
    d.line([(margin, rule_y), (W - margin, rule_y)], fill=ink_soft, width=int(1.2*SCALE))

    mono = F("DMMono-Regular.ttf", 24)
    yahei_s = FY(24)
    ann_y = rule_y + int(30 * SCALE)
    x = margin
    for s, font, fill, tracking in [(fig_en, mono, ink_soft, 0), ("   ", mono, ink_soft, 0),
                                     (fig_zh, yahei_s, ink_soft, int(2*SCALE))]:
        x = draw_tracked(d, (x, ann_y), s, font, fill, tracking)
    rw = text_w(d, ref_text, mono)
    d.text((W - margin - rw, ann_y), ref_text, font=mono, fill=ink_soft)

    grid_top = ann_y + int(130 * SCALE)
    grid_bottom = H - frame_inset - int(130 * SCALE)
    col_gap = int(60 * SCALE)
    col_w = (W - 2*margin - 2*col_gap) // 3
    label_h = int(110 * SCALE)

    # --- column 1: reversed mark on a brand-color disc
    c1x0, c1y0 = margin, grid_top
    c1x1, c1y1 = margin + col_w, grid_bottom
    panel(d, c1x0, c1y0, c1x1, c1y1, cream2)
    content_h = (c1y1 - c1y0) - label_h
    disc_r = int(min(col_w, content_h) * 0.30)
    ccx, ccy = (c1x0+c1x1)//2, c1y0 + content_h//2
    d.ellipse([ccx-disc_r, ccy-disc_r, ccx+disc_r, ccy+disc_r], fill=palette['reversed_bg'])
    symbol_fn(img, d, ccx, ccy, int(disc_r*0.62), palette, "reversed")
    col_label(d, (c1x0+c1x1)//2, c1y1 - label_h + int(20*SCALE), "REVERSED", "反白标准色", ink_soft)

    # --- column 2: horizontal lockup
    c2x0, c2y0 = margin + col_w + col_gap, grid_top
    c2x1, c2y1 = c2x0 + col_w, grid_bottom
    panel(d, c2x0, c2y0, c2x1, c2y1, cream2)
    content_h2 = (c2y1 - c2y0) - label_h
    lock_cy = c2y0 + content_h2//2
    pad2 = int(70*SCALE)
    avail_w = (c2x1 - c2x0) - 2*pad2
    mark_r = int(content_h2 * 0.22)
    hf = FK(int(mark_r*1.65/SCALE))
    hf_w = text_w(d, "焕发", hf, tracking=int(4*SCALE))
    total_w = mark_r*2 + int(34*SCALE) + hf_w
    if total_w > avail_w:
        fct = avail_w / total_w
        mark_r = int(mark_r * fct)
        hf = FK(int(mark_r*1.65/SCALE))
        hf_w = text_w(d, "焕发", hf, tracking=int(4*SCALE))
        total_w = mark_r*2 + int(34*SCALE) + hf_w
    start_x = (c2x0+c2x1)//2 - total_w//2
    mark_cx = start_x + mark_r
    symbol_fn(img, d, mark_cx, lock_cy, mark_r, palette, "lockup")
    bbox = d.textbbox((0, 0), "焕", font=hf)
    text_y = lock_cy - (bbox[3]-bbox[1])//2 - int(6*SCALE)
    draw_tracked(d, (mark_cx + mark_r + int(34*SCALE), text_y), "焕发", hf, word_color, tracking=int(4*SCALE))
    col_label(d, (c2x0+c2x1)//2, c2y1 - label_h + int(20*SCALE), "HORIZONTAL LOCKUP", "横版组合", ink_soft)

    # --- column 3: palette
    c3x0, c3y0 = margin + 2*(col_w+col_gap), grid_top
    c3x1, c3y1 = c3x0 + col_w, grid_bottom
    panel(d, c3x0, c3y0, c3x1, c3y1, cream2)
    content_h3 = (c3y1 - c3y0) - label_h
    pad = int(36*SCALE)
    gap_v = int(14*SCALE)
    sw_h = (content_h3 - gap_v*(len(swatches)-1)) // len(swatches)
    for i, (name, col, hexv) in enumerate(swatches):
        y0 = c3y0 + i*(sw_h+gap_v)
        y1 = y0 + sw_h
        outline = ink_soft if sum(col) > 700 else None
        d.rectangle([c3x0+pad, y0, c3x1-pad, y1], fill=col, outline=outline, width=int(1*SCALE))
        txt_color = cream if sum(col) < 380 else ink
        d.text((c3x0+pad+int(18*SCALE), y0+int(18*SCALE)), name, font=F("DMMono-Regular.ttf", 22), fill=txt_color)
        tw = text_w(d, hexv, F("DMMono-Regular.ttf", 22))
        d.text((c3x1-pad-int(18*SCALE)-tw, y1-int(46*SCALE)), hexv, font=F("DMMono-Regular.ttf", 22), fill=txt_color)
    col_label(d, (c3x0+c3x1)//2, c3y1 - label_h + int(20*SCALE), "PALETTE", "色板", ink_soft)

    img.convert("RGB").resize((2400, 3000), Image.LANCZOS).save(out_path)
    print("saved", out_path)

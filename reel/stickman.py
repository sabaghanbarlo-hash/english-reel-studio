"""Stickman explainer renderer: draws every frame with Pillow and pipes it straight into FFmpeg.

One stickman stays on screen the whole reel. Per scene it changes pose and face, a prop pops in above it
(brain, clock, phone, ...), and an optional one-to-three-word label appears. The mouth opens only while a
word is actually being spoken (word timings come from the voice), so he really "talks" the narration.

No extra dependencies beyond Pillow. Frames are drawn at 2x and averaged down for smooth, antialiased lines.
"""
import math
import multiprocessing as mp
import os
import subprocess
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 24
SS = 2

INK = (27, 27, 31)
WHITE = (255, 253, 248)
RED = (232, 72, 85)
BGS = [(245, 239, 227), (232, 243, 238), (247, 236, 230), (236, 239, 248), (246, 243, 217)]
ACCENTS = [(232, 85, 61), (46, 134, 171), (242, 177, 52), (76, 175, 130)]

CX, GROUND = 540, 1300          # figure position (feet line); captions sit just below, Instagram UI below that
PROP_X, PROP_Y = 540, 548       # centre of the prop above the head
PROP_SCALE = 1.0
LABEL_Y = 290
FIG = 1.15                      # figure scale


# ----------------------------------------------------------------------------- helpers
def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def ease_out_back(x):
    x = max(0.0, min(1.0, x))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))


_FONT_CANDIDATES = (
    "fonts/Poppins-ExtraBold.ttf",
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def font_path() -> str:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return ""


@lru_cache(maxsize=64)
def font(px: int):
    p = font_path()
    return ImageFont.truetype(p, px) if p else ImageFont.load_default()


class G:
    """Drawing context in logical 1080x1920 coordinates on a supersampled canvas."""

    def __init__(self, img):
        self.d = ImageDraw.Draw(img)
        self.s = SS

    def p(self, pt):
        return (pt[0] * self.s, pt[1] * self.s)

    def wd(self, w):
        return max(1, int(round(w * self.s)))

    def line(self, pts, w, col=INK):
        pp = [self.p(q) for q in pts]
        self.d.line(pp, fill=col, width=self.wd(w), joint="curve")
        r = w * self.s / 2
        for q in (pp[0], pp[-1]):
            self.d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=col)

    def circle(self, c, r, fill=None, outline=None, w=0):
        x, y = self.p(c)
        r *= self.s
        self.d.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline=outline, width=self.wd(w) if outline else 0)

    def ellipse(self, box, fill=None, outline=None, w=0):
        self.d.ellipse([*self.p(box[:2]), *self.p(box[2:])], fill=fill, outline=outline, width=self.wd(w) if outline else 0)

    def rrect(self, box, rad, fill=None, outline=None, w=0):
        self.d.rounded_rectangle([*self.p(box[:2]), *self.p(box[2:])], radius=rad * self.s, fill=fill,
                                 outline=outline, width=self.wd(w) if outline else 0)

    def poly(self, pts, fill=None, outline=None, w=0):
        pp = [self.p(q) for q in pts]
        if fill:
            self.d.polygon(pp, fill=fill)
        if outline:
            self.line(list(pts) + [pts[0], pts[1]], w, outline)

    def arc(self, box, a0, a1, col, w):
        self.d.arc([*self.p(box[:2]), *self.p(box[2:])], a0, a1, fill=col, width=self.wd(w))

    def text(self, xy, s, px, fill, stroke=0, stroke_fill=INK, anchor="mm"):
        self.d.text(self.p(xy), s, font=font(int(px * self.s)), fill=fill, anchor=anchor,
                    stroke_width=int(stroke * self.s), stroke_fill=stroke_fill)


class Local:
    """Prop-local coordinates (about -170..170), scaled by the pop-in factor k around (cx, cy)."""

    def __init__(self, g, cx, cy, k, bg, acc):
        self.g, self.cx, self.cy, self.k, self.bg, self.acc = g, cx, cy, k, bg, acc

    def pt(self, x, y):
        return (self.cx + x * self.k, self.cy + y * self.k)

    def line(self, pts, w=10, col=INK):
        self.g.line([self.pt(*q) for q in pts], w * self.k, col)

    def circle(self, x, y, r, fill=None, ink=True, w=9):
        self.g.circle(self.pt(x, y), r * self.k, fill, INK if ink else None, w * self.k)

    def ell(self, x0, y0, x1, y1, fill=None, ink=True, w=9):
        self.g.ellipse([*self.pt(x0, y0), *self.pt(x1, y1)], fill, INK if ink else None, w * self.k)

    def rrect(self, x0, y0, x1, y1, rad=14, fill=None, ink=True, w=9):
        self.g.rrect([*self.pt(x0, y0), *self.pt(x1, y1)], rad * self.k, fill, INK if ink else None, w * self.k)

    def poly(self, pts, fill=None, ink=True, w=9):
        self.g.poly([self.pt(*q) for q in pts], fill, INK if ink else None, w * self.k)

    def arc(self, x0, y0, x1, y1, a0, a1, w=9, col=INK):
        self.g.arc([*self.pt(x0, y0), *self.pt(x1, y1)], a0, a1, col, w * self.k)

    def text(self, x, y, s, px, fill=INK, stroke=0):
        self.g.text(self.pt(x, y), s, px * self.k, fill, stroke * self.k)


# ----------------------------------------------------------------------------- props
def p_brain(L, t, lt):
    pink = (244, 166, 183)
    blobs = [(-72, -20, 68), (0, -62, 74), (74, -16, 66), (-44, 46, 60), (42, 48, 62), (0, 4, 58)]
    for x, y, r in blobs:
        L.circle(x, y, r + 8, fill=INK, ink=False)
    for x, y, r in blobs:
        L.circle(x, y, r, fill=pink, ink=False)
    L.line([(0, -118), (-9, -62), (7, -12), (-4, 40), (0, 98)], 7)
    L.line([(-112, -26), (-82, -54), (-52, -26)], 6)
    L.line([(48, -48), (82, -72), (112, -42)], 6)
    L.line([(-78, 36), (-50, 14), (-26, 40)], 6)
    L.line([(30, 52), (62, 30), (92, 56)], 6)
    for i in range(3):  # little thought sparks
        a = t * 3 + i * 2.1
        if math.sin(a) > -0.2:
            x, y = [(-140, -110), (130, -120), (0, -150)][i]
            L.line([(x, y), (x + 14 * (1 if x >= 0 else -1), y - 14)], 7, (242, 177, 52))


def _heart_pts(scale=8.6, n=64):
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        x = 16 * math.sin(a) ** 3
        y = -(13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a))
        pts.append((x * scale, y * scale + 6))
    return pts


def p_heart(L, t, lt):
    beat = 1 + 0.07 * max(0.0, math.sin(t * 6.5)) ** 2
    pts = [(x * beat, y * beat) for x, y in _heart_pts()]
    L.poly(pts, fill=RED, w=10)
    L.line([(-70, -40), (-48, -64)], 9, (255, 190, 195))


def p_broken_heart(L, t, lt):
    pts = _heart_pts()
    L.poly(pts, fill=RED, w=10)
    crack = [(6, -112), (-26, -62), (16, -26), (-22, 22), (12, 62), (0, 108)]
    L.line(crack, 20, L.bg)
    L.line(crack, 7)
    fall = min(1.0, lt / 1.2)
    for dx, sz in ((-95, 16), (100, 13)):  # tiny falling shards
        y = 60 + 70 * fall * fall
        L.poly([(dx, y), (dx + sz, y + sz * 1.4), (dx - sz, y + sz * 1.2)], fill=RED, w=6)


def p_clock(L, t, lt):
    L.line([(-70, 118), (-96, 150)], 11)
    L.line([(70, 118), (96, 150)], 11)
    L.circle(-86, -112, 36, fill=L.acc)
    L.circle(86, -112, 36, fill=L.acc)
    L.circle(0, 0, 132, fill=WHITE, w=12)
    for i in range(12):
        a = i * math.pi / 6
        L.line([(math.sin(a) * 104, -math.cos(a) * 104), (math.sin(a) * 118, -math.cos(a) * 118)], 7)
    mi, hr = lt * 2.2, lt * 2.2 / 12
    L.line([(0, 0), (math.sin(mi) * 98, -math.cos(mi) * 98)], 8)
    L.line([(0, 0), (math.sin(hr) * 62, -math.cos(hr) * 62)], 12)
    L.circle(0, 0, 11, fill=INK, ink=False)
    if int(t * 6) % 2 == 0:  # ring marks
        L.line([(-150, -150), (-132, -168)], 7, L.acc)
        L.line([(150, -150), (132, -168)], 7, L.acc)


def p_phone(L, t, lt):
    L.cx += 3.0 * math.sin(t * 38) * L.k
    L.rrect(-86, -152, 86, 152, 26, fill=(38, 40, 50), w=11)
    L.rrect(-70, -128, 70, 122, 12, fill=(225, 235, 246), ink=False)
    for i in range(3):
        y = -108 + i * 66
        L.rrect(-60, y, 60, y + 52, 10, fill=WHITE, w=5)
        L.circle(-38, y + 26, 13, fill=L.acc, ink=False)
        L.line([(-14, y + 18), (40, y + 18)], 6)
        L.line([(-14, y + 36), (26, y + 36)], 5, (150, 150, 160))
    L.circle(78, -142, 27, fill=RED, w=7)
    L.text(78, -141, "3", 34, WHITE)
    L.line([(-30, 138), (30, 138)], 7, (110, 110, 120))


def p_bulb(L, t, lt):
    L.circle(0, -34, 102, fill=(255, 220, 90), w=11)
    L.line([(-26, 52), (-16, 80), (16, 80), (26, 52)], 7)
    L.rrect(-46, 70, 46, 100, 8, fill=(190, 190, 200), w=8)
    L.rrect(-34, 100, 34, 128, 10, fill=(150, 150, 165), w=8)
    L.line([(-16, 54), (-16, -4)], 6)
    L.line([(16, 54), (16, -4)], 6)
    L.arc(-16, -30, 16, 2, 180, 360, 6)
    for i in range(8):
        a = i * math.pi / 4 + 0.2
        f = 0.75 + 0.25 * math.sin(t * 9 + i * 1.3)
        r0, r1 = 124, 124 + 40 * f
        L.line([(math.sin(a) * r0, -34 - math.cos(a) * r0), (math.sin(a) * r1, -34 - math.cos(a) * r1)], 8, (242, 177, 52))


def p_question(L, t, lt):
    L.text(0, 8, "?", 380, L.acc, stroke=9)
    for i, (x, y, px) in enumerate(((-120, -120, 84), (125, -95, 70), (-135, 70, 60))):
        dy = 10 * math.sin(t * 2.4 + i * 2)
        L.text(x, y + dy, "?", px, INK)


def p_alert(L, t, lt):
    pulse = 1 + 0.05 * math.sin(t * 8)
    pts = [(-150 * pulse, 112 * pulse), (150 * pulse, 112 * pulse), (0, -150 * pulse)]
    L.poly(pts, fill=(255, 205, 60), w=13)
    L.text(0, 36, "!", 200, INK)


def _arrow(L, a, b, w=11, col=INK):
    L.line([a, b], w, col)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (-1, 1):
        c = ang + math.pi + s * 0.5
        L.line([b, (b[0] + math.cos(c) * 34, b[1] + math.sin(c) * 34)], w, col)


def _bars(L, t, lt, heights, col, arrow_up):
    L.line([(-140, -135), (-140, 132), (155, 132)], 9)
    for i, h in enumerate(heights):
        grow = smooth((lt - 0.12 * i) / 0.5)
        x = -100 + i * 70
        hh = h * grow
        if hh > 2:
            L.rrect(x - 24, 126 - hh, x + 24, 126, 6, fill=col, w=7)
    if arrow_up:
        _arrow(L, (-120, 40), (125, -105), 11, INK)
    else:
        _arrow(L, (-120, -95), (125, 40), 11, INK)


def p_chart_up(L, t, lt):
    _bars(L, t, lt, [60, 105, 150, 215], (76, 175, 130), True)


def p_chart_down(L, t, lt):
    _bars(L, t, lt, [215, 150, 105, 55], RED, False)


def _mini(L, x, y, mood, bob):
    y += bob
    L.circle(x, y - 118, 30, fill=WHITE, w=8)
    L.line([(x, y - 88), (x, y - 22)], 8)
    L.line([(x, y - 74), (x - 28, y - 42)], 8)
    L.line([(x, y - 74), (x + 28, y - 42)], 8)
    L.line([(x, y - 22), (x - 22, y + 30)], 8)
    L.line([(x, y - 22), (x + 22, y + 30)], 8)
    L.circle(x - 10, y - 124, 3.5, fill=INK, ink=False)
    L.circle(x + 10, y - 124, 3.5, fill=INK, ink=False)
    if mood:
        L.arc(x - 11, y - 118, x + 11, y - 100, 20, 160, 5)
    else:
        L.line([(x - 9, y - 106), (x + 9, y - 106)], 5)


def p_people(L, t, lt):
    _mini(L, -88, 70, True, 4 * math.sin(t * 2.2))
    _mini(L, 88, 70, False, 4 * math.sin(t * 2.2 + 1.6))
    L.ell(-150, -150, -20, -86, fill=WHITE, w=7)
    for i in range(3):
        L.circle(-110 + i * 30, -118, 5 + (2 if int(t * 3) % 3 == i else 0), fill=INK, ink=False)
    L.line([(-10, 100), (10, 100)], 6, L.acc)


def p_house(L, t, lt):
    L.rrect(-112, -26, 112, 122, 6, fill=(255, 238, 205), w=11)
    L.poly([(-140, -24), (0, -142), (140, -24)], fill=L.acc, w=11)
    L.rrect(-32, 30, 32, 122, 6, fill=(160, 110, 70), w=8)
    L.circle(18, 80, 5, fill=INK, ink=False)
    for x in (-88, 54):
        L.rrect(x, 0, x + 46, 46, 4, fill=(190, 225, 245), w=7)
        L.line([(x + 23, 0), (x + 23, 46)], 5)
        L.line([(x, 23), (x + 46, 23)], 5)


def p_magnifier(L, t, lt):
    ox, oy = 14 * math.sin(t * 2.0), 9 * math.cos(t * 2.3)
    L.line([(36 + ox, 40 + oy), (132 + ox, 136 + oy)], 28)
    L.circle(-30 + ox, -30 + oy, 98, fill=(205, 230, 245), w=14)
    L.arc(-100 + ox, -100 + oy, 40 + ox, 40 + oy, 200, 260, 9, WHITE)


def p_lock(L, t, lt):
    L.line([(-62, -8), (-62, -52), (-36, -100), (0, -112), (36, -100), (62, -52), (62, -8)], 18)
    L.rrect(-102, -10, 102, 132, 18, fill=(240, 180, 60), w=11)
    L.circle(0, 52, 19, fill=INK, ink=False)
    L.line([(0, 52), (0, 98)], 15)


def p_battery(L, t, lt):
    L.rrect(-132, -72, 122, 72, 16, fill=WHITE, w=12)
    L.rrect(122, -30, 152, 30, 6, fill=INK, w=4)
    if int(t * 2.2) % 2 == 0:
        L.rrect(-118, -58, -78, 58, 8, fill=RED, ink=False)
    L.line([(-30, -30), (10, -4), (-8, 6), (34, 36)], 8, (150, 150, 160))
    L.text(0, 128, "low", 44, RED)


def p_scale(L, t, lt):
    a = 0.22 * math.sin(t * 1.8)
    L.line([(0, -118), (0, 128)], 12)
    L.rrect(-72, 124, 72, 148, 8, fill=INK, w=4)
    ends = [(-130 * math.cos(a), -112 - 130 * math.sin(a)), (130 * math.cos(a), -112 + 130 * math.sin(a))]
    L.line([ends[0], ends[1]], 11)
    L.circle(0, -112, 14, fill=L.acc)
    for ex, ey in ends:
        L.line([(ex, ey), (ex - 52, ey + 100)], 5)
        L.line([(ex, ey), (ex + 52, ey + 100)], 5)
        L.rrect(ex - 62, ey + 98, ex + 62, ey + 116, 8, fill=L.acc, w=7)


def p_mask(L, t, lt):
    L.ell(-8, -78, 118, 112, fill=(140, 175, 225), w=10)
    L.line([(40, -20), (62, -30)], 6)
    L.line([(78, -30), (100, -20)], 6)
    L.arc(46, 38, 92, 74, 200, 340, 7)
    L.ell(-112, -96, 38, 98, fill=(250, 205, 90), w=11)
    L.circle(-60, -28, 11, fill=INK, ink=False)
    L.circle(-14, -28, 11, fill=INK, ink=False)
    L.arc(-82, 6, -8, 62, 15, 165, 8)


def p_target(L, t, lt):
    for r, col in ((142, WHITE), (108, L.acc), (74, WHITE), (40, L.acc)):
        L.circle(0, 0, r, fill=col, w=8)
    p = smooth(lt / 0.5)
    tip = (lerp(260, 4, p), lerp(-260, -4, p))
    tail = (tip[0] + 120, tip[1] - 120)
    L.line([tip, tail], 10)
    for s in (-1, 1):
        L.line([tail, (tail[0] + 20 + s * 18, tail[1] - 6 - s * 18)], 7)


def p_book(L, t, lt):
    L.poly([(-162, -76), (0, -46), (162, -76), (162, 112), (0, 134), (-162, 112)], fill=L.acc, w=10)
    L.poly([(-148, -88), (0, -60), (0, 108), (-148, 82)], fill=WHITE, w=9)
    L.poly([(0, -60), (148, -88), (148, 82), (0, 108)], fill=(250, 246, 235), w=9)
    for i in range(4):
        y = -42 + i * 28
        L.line([(-118, y - 6), (-26, y + 10)], 5, (150, 150, 160))
        L.line([(26, y + 10), (118, y - 6)], 5, (150, 150, 160))


def p_eyes(L, t, lt):
    px, py = 28 * math.sin(t * 1.3), 14 * math.sin(t * 0.9)
    for x in (-82, 82):
        L.ell(x - 70, -96, x + 70, 96, fill=WHITE, w=12)
        L.circle(x + px, py, 33, fill=INK, ink=False)
        L.circle(x + px + 10, py - 12, 9, fill=WHITE, ink=False)
    L.line([(-150, -118), (-30, -104)], 10)
    L.line([(30, -104), (150, -118)], 10)


PROP_DRAW = {
    "brain": p_brain, "heart": p_heart, "broken_heart": p_broken_heart, "clock": p_clock, "phone": p_phone,
    "bulb": p_bulb, "question": p_question, "alert": p_alert, "chart_up": p_chart_up, "chart_down": p_chart_down,
    "people": p_people, "house": p_house, "magnifier": p_magnifier, "lock": p_lock, "battery": p_battery,
    "scale": p_scale, "mask": p_mask, "target": p_target, "book": p_book, "eyes": p_eyes,
}


# ----------------------------------------------------------------------------- the stickman
def pose_angles(name, t):
    """(left shoulder, left forearm, right shoulder, right forearm), degrees. 0 = down, 90 = sideways, 180 = up."""
    s = math.sin
    if name == "talk":
        return (12, 22, 58 + 8 * s(t * 3.1), 118 + 22 * s(t * 4.3))
    if name == "point":
        return (12, 22, 80, 152 + 5 * s(t * 3.0))
    if name == "shrug":
        a = 50 + 4 * s(t * 2.0)
        return (a, 125, a, 125)
    if name == "think":
        return (14, 24, 28, 172 + 3 * s(t * 1.5))
    if name == "excited":
        w = s(t * 7)
        return (135 + 10 * w, 165 + 15 * w, 135 - 10 * w, 165 - 15 * w)
    if name == "sad":
        return (4, 6, 4, 6)
    if name == "stop":
        return (12, 22, 92, 92 + 3 * s(t * 3.0))
    if name == "hips":
        return (38, -22, 38, -22)
    return (10 + 3 * s(t * 1.6), 18, 10 + 3 * s(t * 1.6 + 1), 18)  # idle


def _dir(angle, side):
    a = math.radians(angle)
    return (side * math.sin(a), math.cos(a))


def draw_figure(g, t, lt, i, shot, prev_shot, openness, bg, acc):
    sc = FIG
    hop = math.sin(math.pi * min(1.0, lt / 0.32)) * 16 if i > 0 and lt < 0.32 else 0.0
    breath = 2.0 * math.sin(t * 2.2)
    gy = GROUND - hop
    pose, emo = shot["pose"], shot["emotion"]
    sad = pose == "sad" or emo == "sad"
    lean = 12 * sc if sad else 0.0
    leg, torso, r = 165 * sc, 180 * sc, 64 * sc
    hip = (CX, gy - leg)
    neck = (CX + lean, gy - leg - torso + breath * 0.4)
    head = (neck[0] + lean * 0.6, neck[1] - r - 6 * sc + (12 * sc if sad else 0) + breath * 0.3)

    # shadow + ground
    sw = 150 - hop * 2
    g.ellipse([CX - sw, GROUND - 4, CX + sw, GROUND + 22], fill=mix(bg, INK, 0.12))
    g.line([(CX - 340, GROUND + 6), (CX + 340, GROUND + 6)], 6, mix(bg, INK, 0.45))

    # legs
    for side in (-1, 1):
        foot = (CX + side * 38 * sc, gy)
        g.line([hip, (CX + side * 24 * sc, gy - leg * 0.5), foot], 13 * sc)
        g.line([foot, (foot[0] + side * 28 * sc, gy)], 13 * sc)
    # torso
    g.line([hip, neck], 14 * sc)

    # arms (blend from the previous scene's pose)
    b = smooth(lt / 0.35) if prev_shot else 1.0
    cur = pose_angles(pose, t)
    old = pose_angles(prev_shot["pose"], t) if prev_shot else cur
    ang = [lerp(o, c, b) for o, c in zip(old, cur)]
    sh_y = neck[1] + 16 * sc + (8 * sc if pose == "shrug" else 0) * -1
    for side, (a1, a2) in ((-1, ang[0:2]), (1, ang[2:4])):
        sh = (neck[0] + side * 6 * sc, sh_y)
        el = (sh[0] + _dir(a1, side)[0] * 78 * sc, sh[1] + _dir(a1, side)[1] * 78 * sc)
        hand = (el[0] + _dir(a2, side)[0] * 74 * sc, el[1] + _dir(a2, side)[1] * 74 * sc)
        g.line([sh, el, hand], 12.5 * sc)
        g.circle(hand, 9.5 * sc, fill=INK)

    # scarf (gives him an accent colour)
    g.line([(neck[0] - 26 * sc, neck[1] + 6 * sc), (neck[0] + 26 * sc, neck[1] + 6 * sc)], 17 * sc, acc)
    sway = 6 * math.sin(t * 3.0)
    g.poly([(neck[0] + 12 * sc, neck[1] + 10 * sc), (neck[0] + 36 * sc + sway, neck[1] + 60 * sc),
            (neck[0] + 6 * sc + sway, neck[1] + 56 * sc)], fill=acc, outline=None)

    # head
    g.circle(head, r, fill=WHITE, outline=INK, w=12 * sc)
    look = {"thinking": (8, -8), "worried": (-6, 2), "sad": (0, 7), "surprised": (0, -2)}.get(emo, (0, 0))
    if pose == "point":
        look = (6, -9)
    lx, ly = look[0] * sc, look[1] * sc
    ex = 20 * sc
    ey = head[1] - 5 * sc + ly
    blink = (t % 3.4) < 0.11
    for side in (-1, 1):
        cx = head[0] + side * ex + lx
        if emo == "surprised" and not blink:
            g.circle((cx, ey), 11 * sc, fill=WHITE, outline=INK, w=4 * sc)
            g.circle((cx + lx * 0.3, ey + ly * 0.3), 4.5 * sc, fill=INK)
        elif blink:
            g.line([(cx - 7 * sc, ey), (cx + 7 * sc, ey)], 4 * sc)
        else:
            g.circle((cx, ey), 6.2 * sc, fill=INK)
    # brows
    def brow(side, inner_dy, outer_dy):
        x_in, x_out = head[0] + side * 8 * sc, head[0] + side * 33 * sc
        y0 = head[1] - 22 * sc + ly
        g.line([(x_in, y0 + inner_dy * sc), (x_out, y0 + outer_dy * sc)], 4.5 * sc)
    if emo == "angry":
        brow(-1, 0, -10), brow(1, 0, -10)
        brow(-1, 2, -8), brow(1, 2, -8)
    elif emo in ("worried", "sad"):
        brow(-1, -10, 2), brow(1, -10, 2)
    elif emo == "thinking":
        brow(-1, 0, 0), brow(1, -10, -14)
    elif emo == "surprised":
        brow(-1, -8, -8), brow(1, -8, -8)
    # mouth
    mx, my = head[0] + lx * 0.5, head[1] + 26 * sc + ly * 0.5
    if openness > 0.05:
        h = (7 + 22 * openness) * sc
        wdt = (13 + 8 * openness) * sc
        if emo == "surprised":
            wdt, h = 15 * sc, (14 + 12 * openness) * sc
        g.ellipse([mx - wdt, my - h / 2, mx + wdt, my + h / 2], fill=INK)
    elif emo == "happy":
        g.arc([mx - 17 * sc, my - 14 * sc, mx + 17 * sc, my + 12 * sc], 15, 165, INK, 5 * sc)
    elif emo in ("sad", "worried"):
        g.arc([mx - 15 * sc, my + 2 * sc, mx + 15 * sc, my + 26 * sc], 200, 340, INK, 5 * sc)
    elif emo == "surprised":
        g.circle((mx, my + 3 * sc), 8 * sc, fill=INK)
    else:
        g.line([(mx - 11 * sc, my + 3 * sc), (mx + 11 * sc, my + 3 * sc)], 5 * sc)


# ----------------------------------------------------------------------------- scene composition
def draw_label(g, text, lt, acc):
    if not text:
        return
    k = ease_out_back(lt / 0.4)
    if k < 0.03:
        return
    text = text.upper()
    px = 92
    while px > 44 and font(int(px)).getlength(text) > 900:
        px -= 4
    width = font(int(px)).getlength(text) * k
    g.rrect([CX - width / 2 - 8, LABEL_Y + px * 0.12 * k, CX + width / 2 + 8, LABEL_Y + px * 0.52 * k], 10,
            fill=mix(acc, WHITE, 0.45))
    g.text((CX, LABEL_Y), text, px * k, INK)


def draw_decor(g, t, bg, acc):
    tint = mix(bg, acc, 0.22)
    for n in range(9):
        x = (n * 211 + 97) % 1000 + 40
        y = ((n * 337 + 53) % 1500) + 60
        y += 14 * math.sin(t * 0.8 + n)
        r = 7 + (n % 3) * 4
        if abs(x - PROP_X) < 230 and abs(y - PROP_Y) < 230:
            continue
        g.circle((x, y), r, fill=tint)


class State:
    shots, starts, words_s, words_e = [], [], [], []


def openness_at(t):
    ws, we = State.words_s, State.words_e
    i = bisect_right(ws, t) - 1
    if i < 0 or t > we[i] + 0.05:
        return 0.0
    phase = t - ws[i]
    edge = min(1.0, phase / 0.05, max(0.0, (we[i] + 0.05 - t) / 0.08))
    return edge * (0.5 + 0.5 * abs(math.sin(phase * 12.5)))


def draw_frame(f):
    t = f / FPS
    S = State
    i = max(0, bisect_right(S.starts, t) - 1)
    lt = t - S.starts[i]
    shot = S.shots[i]
    prev = S.shots[i - 1] if i > 0 else None
    acc = ACCENTS[i % len(ACCENTS)]
    bg = BGS[i % len(BGS)]
    if i > 0:
        bg = mix(BGS[(i - 1) % len(BGS)], bg, smooth(lt / 0.4))
    img = Image.new("RGB", (W * SS, H * SS), bg)
    g = G(img)
    draw_decor(g, t, bg, acc)

    # soft disc behind the prop
    k = ease_out_back(lt / 0.45)
    if k > 0.02:
        g.circle((PROP_X, PROP_Y), 190 * PROP_SCALE * min(1.1, k), fill=mix(bg, acc, 0.16))
    if prev and lt < 0.18 and prev["scene"] != shot["scene"]:
        PROP_DRAW[prev["scene"]](Local(g, PROP_X, PROP_Y, max(0.02, 1 - lt / 0.18) * PROP_SCALE, bg, acc), t, 5.0)
    if k > 0.02:
        PROP_DRAW[shot["scene"]](Local(g, PROP_X, PROP_Y, max(0.02, k) * PROP_SCALE, bg, acc), t, lt)
    draw_label(g, shot.get("label", ""), lt, acc)
    draw_figure(g, t, lt, i, shot, prev, openness_at(t), bg, acc)
    return img.reduce(SS).tobytes()


def render_video(plan, nar, out_path, workers=None):
    """Draw the whole reel (silent) to out_path. nar comes from narration.build()."""
    shots, durs, total, words = plan["shots"], nar["shot_durs"], nar["total"], nar["words"]
    starts = [0.0]
    for d in durs[:-1]:
        starts.append(starts[-1] + d)
    State.shots, State.starts = shots, starts
    State.words_s = [w["start"] for w in words]
    State.words_e = [w["end"] for w in words]
    frames = int(math.ceil(total * FPS))
    workers = workers or max(1, min(os.cpu_count() or 1, 8))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
           "-pix_fmt", "yuv420p", "-an", str(out_path)]
    print(f"Drawing {frames} frames with {workers} worker(s)...", flush=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        if workers == 1:
            for f in range(frames):
                proc.stdin.write(draw_frame(f))
        else:
            with mp.get_context("fork").Pool(workers) as pool:
                for n, data in enumerate(pool.imap(draw_frame, range(frames), chunksize=6)):
                    proc.stdin.write(data)
                    if n % 120 == 0:
                        print(f"  frame {n}/{frames}", flush=True)
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code:
        raise SystemExit(f"ffmpeg failed while encoding the stickman video (exit {code}).")

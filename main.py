"""THE WEDNESDAY EDITION — one image summing up the world news of
Tuesday 24 November 2026.

A broadsheet front page: navy masthead, a dateline naming the day, a
hero story (Russia's 96-drone night attack on Ukraine), seven toon
illustrations of the day's other big stories, and the full numbered
list of all 40 stories, every one with its source printed beside it.

All 40 stories are hard news (war, trade, disaster, politics) whose
events happened on 24 November 2026. All eight illustrations are
original toon scenes rendered for this entry.

Stdlib only. Deterministic: no clock, no randomness, no network.
Writes entry.png (1024x1024, <= 1 MiB) to $MAKEFUN_OUTPUT_DIR when set,
otherwise to ./output next to the working directory.
"""

import json
import os
import struct
import sys
import zlib

BASE = os.path.dirname(os.path.abspath(__file__))
W = 1024
H = 1024

PAPER = (246, 239, 220)
INK = (20, 33, 61)
NAVY = (20, 33, 61)
CRIMSON = (163, 18, 38)
GOLD = (185, 138, 30)
GREY = (110, 105, 90)
CREAM = (246, 239, 220)
WHITE = (255, 255, 255)

# ---------------------------------------------------------------- fonts
# BF3 bitmap font: magic b"BF3\\x00", uint32 LE header length, JSON header
# {"ascent","descent","glyphs": {codepoint: [advance,w,h,top,off,n]}},
# then the data blob of 8-bit coverage bytes. top = px from the baseline
# up to the top of the glyph bitmap.


class Font:
    def __init__(self, name):
        with open(os.path.join(BASE, "fonts", name + ".bf3"), "rb") as f:
            raw = f.read()
        assert raw[:4] == b"BF3\x00", name
        (hlen,) = struct.unpack("<I", raw[4:8])
        head = json.loads(raw[8:8 + hlen].decode("utf-8"))
        self.ascent = head["ascent"]
        self.descent = head["descent"]
        self.glyphs = {int(k): tuple(v) for k, v in head["glyphs"].items()}
        self.data = raw[8 + hlen:]

    def width(self, text):
        return sum(self.glyphs[ord(c)][0] for c in text)

    def glyph(self, ch):
        return self.glyphs[ord(ch)]


FONTS = {}


def font(name):
    if name not in FONTS:
        FONTS[name] = Font(name)
    return FONTS[name]


# ---------------------------------------------------------------- canvas

class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)
        self.fill(0, 0, w, h, bg)

    def fill(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        r, g, b = color
        for yy in range(y0, y1):
            base = (yy * self.w + x0) * 3
            for xx in range(x0, x1):
                i = base + (xx - x0) * 3
                self.px[i] = r
                self.px[i + 1] = g
                self.px[i + 2] = b

    def hline(self, x, y, w, color, thick=1):
        self.fill(x, y, w, thick, color)

    def vline(self, x, y, h, color, thick=1):
        self.fill(x, y, thick, h, color)

    def draw_text(self, fname, x, baseline, text, color, max_width=None):
        """Draw text with its baseline at y=baseline. Raises if it does
        not fit max_width, so a layout mistake fails loudly."""
        f = font(fname)
        if max_width is not None:
            tw = f.width(text)
            if tw > max_width:
                raise SystemExit(
                    "TEXT OVERFLOW %r (%s): %dpx > %dpx"
                    % (text, fname, tw, max_width))
        r, g, b = color
        cx = x
        for ch in text:
            adv, gw, gh, top, off, n = f.glyph(ch)
            if n:
                gy0 = baseline - top
                for row in range(gh):
                    yy = gy0 + row
                    if yy < 0 or yy >= self.h:
                        continue
                    for col in range(gw):
                        a = f.data[off + row * gw + col]
                        if not a:
                            continue
                        xx = cx + col
                        if xx < 0 or xx >= self.w:
                            continue
                        i = (yy * self.w + xx) * 3
                        self.px[i] = (self.px[i] * (255 - a) + r * a) // 255
                        self.px[i + 1] = (self.px[i + 1] * (255 - a) + g * a) // 255
                        self.px[i + 2] = (self.px[i + 2] * (255 - a) + b * a) // 255
            cx += adv
        return cx

    def text_center(self, fname, cx, baseline, text, color, max_width=None):
        f = font(fname)
        tw = f.width(text)
        if max_width is not None and tw > max_width:
            raise SystemExit(
                "TEXT OVERFLOW %r (%s): %dpx > %dpx" % (text, fname, tw, max_width))
        return self.draw_text(fname, cx - tw // 2, baseline, text, color)

    def wrap(self, fname, text, width, max_lines):
        """Greedy word wrap. Raises if a line would exceed max_lines or
        a single word is wider than the box."""
        f = font(fname)
        lines = []
        for para in text.split("\n"):
            words = para.split(" ")
            cur = ""
            for word in words:
                if f.width(word) > width:
                    raise SystemExit("WORD TOO WIDE %r (%s)" % (word, fname))
                trial = word if not cur else cur + " " + word
                if f.width(trial) <= width:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = word
            lines.append(cur)
        if len(lines) > max_lines:
            raise SystemExit(
                "WRAP OVERFLOW %r (%s): %d lines > %d"
                % (text, fname, len(lines), max_lines))
        return lines


# ---------------------------------------------------------------- stills

def load_still(name):
    with open(os.path.join(BASE, "stills", name + ".rgb"), "rb") as f:
        data = f.read()
    assert len(data) == 600 * 450 * 3, name
    return data


def blit_cover(cv, dx, dy, dw, dh, src, sw=600, sh=450):
    """Draw the still into (dx,dy,dw,dh), cover-fit: scale to cover the
    box, centre-crop the overflow, area-average downscale."""
    scale = max(dw / sw, dh / sh)
    cw = dw / scale
    ch = dh / scale
    ox = (sw - cw) / 2.0
    oy = (sh - ch) / 2.0
    # Per-target-pixel source spans, with fractional edge weights.
    def spans(n_target, off, step, limit):
        out = []
        for t in range(n_target):
            a = off + t * step
            b = a + step
            i0 = int(a)
            i1 = min(int(b) + 1, limit)
            ws = []
            for i in range(i0, i1):
                lo = max(a, float(i))
                hi = min(b, float(i + 1))
                if hi > lo:
                    ws.append((i, hi - lo))
            out.append(ws)
        return out
    xspans = spans(dw, ox, cw / dw, sw)
    yspans = spans(dh, oy, ch / dh, sh)
    for ty in range(dh):
        yy = dy + ty
        if yy < 0 or yy >= cv.h:
            continue
        for tx in range(dw):
            xx = dx + tx
            if xx < 0 or xx >= cv.w:
                continue
            rs = gs = bs = wsum = 0.0
            for sy, wy in yspans[ty]:
                srow = sy * sw * 3
                for sx, wx in xspans[tx]:
                    wgt = wx * wy
                    i = srow + sx * 3
                    rs += src[i] * wgt
                    gs += src[i + 1] * wgt
                    bs += src[i + 2] * wgt
                    wsum += wgt
            i = (yy * cv.w + xx) * 3
            cv.px[i] = int(rs / wsum + 0.5)
            cv.px[i + 1] = int(gs / wsum + 0.5)
            cv.px[i + 2] = int(bs / wsum + 0.5)


# ---------------------------------------------------------------- png

def write_png(cv, path):
    raw = bytearray()
    stride = W * 3
    for y in range(H):
        raw.append(0)
        raw += cv.px[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(kind, data):
        out = struct.pack(">I", len(data)) + kind + data
        return out + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", comp) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


# ---------------------------------------------------------------- stories
# (headline, source) — all 40, events of Tuesday 24 November 2026.

STORIES = [
    ("Russia launches 96 drones at Ukraine overnight", "Ukrinform"),
    ("Russian strike kills two in Odesa region", "Reuters"),
    ("Strike on Zaporizhzhia kills two, injures dozens", "Ukrinform"),
    ("Drone strikes on Vinnytsia injure four", "h.ua"),
    ("Russian drone briefly enters Polish airspace", "h.ua"),
    ("Zelensky: seek more US support if peace deal fails", "h.ua"),
    ("Ukraine, Norway expand joint DESNA air defence", "h.ua"),
    ("Israeli strikes kill at least six in Gaza", "Reuters"),
    ("UNRWA aid worker killed at well in Jabalia", "Al Jazeera"),
    ("Oxfam: Israeli attacks made Gaza a toxic wasteland", "BBC"),
    ("Houthi strike hits Riyadh's PIF Tower again", "The New Arab"),
    ("Houthis 60 km from Aden, army claims 697 strikes", "The New Arab"),
    ("Airstrike on Hodeidah kills at least 17", "Malabar Mirror"),
    ("Airstrikes hit Houthi positions west of Taiz", "Middle East Forum"),
    ("Katz: Iran developing chemical weapons", "Geopolitiki"),
    ("US sanctions Iran's shadow banking network", "Geopolitiki"),
    ("Two Syrian soldiers hurt in suspected IS attack", "The New Arab"),
    ("Iraq to take control of Kurdish-held oilfields", "Middle East Forum"),
    ("Iraq PM sacks officials over oil-smuggling probe", "The New Arab"),
    ("Landmine casualties hit five-year high: 6,929", "Landmine Monitor"),
    ("Israel orders demolition of homes in Area A", "The New Arab"),
    ("Colombia blames FARC dissidents for car bombing", "Al Jazeera"),
    ("Nvidia falls over 8% after Monday's record surge", "Reuters"),
    ("Nasdaq futures drop as AI stocks cool", "Reuters"),
    ("Oil touches three-month lows: Brent $88.62", "Reuters"),
    ("Indian firms plan $2.8bn in bond fundraising", "Reuters"),
    ("Magnitude 5.3 quake strikes near Lelep, Nepal", "The Hindu"),
    ("Magnitude 6.4 quake in Indian Ocean off Mauritius", "USGS"),
    ("Magnitude 5.6 quake off New Caledonia", "USGS"),
    ("Bus-truck crash in Ras Al Khaimah kills 11", "SANA"),
    ("School bus crash in Kannauj kills four students", "Malabar Mirror"),
    ("High Wind Watch as storms threaten Thanksgiving", "Nat. Weather Service"),
    ("China probes Shanghai party chief Chen Jining", "Reuters"),
    ("DNC to stage 12 presidential primary debates", "Seven Lights"),
    ("Rep. Gomez to resign after ethics finding", "Seven Lights"),
    ("Schumer: Congress will investigate Nvidia", "Seven Lights"),
    ("Preacher Uebert Angel charged, remanded in Harare", "MyZimbabwe"),
    ("UN condemns Iran flogging of singer Parastoo Ahmadi", "France 24"),
    ("Samajwadi offers Congress 26 seats for 2027 UP polls", "India Bytes"),
    ("Steube urges Senate to end the filibuster", "Newsmax"),
]

HERO_HEADLINE = ("Russia launches 96 drones at Ukraine overnight; "
                 "air defences down 73")
HERO_DECK = ("Sixty-four of them jet-powered Shaheds, with hits in 13 "
             "locations. Odesa, Zaporizhzhia and Vinnytsia were also "
             "struck overnight.")

# (story number, still name, caption headline, source)
FEATURES = [
    (11, "pif", "Houthis hit PIF Tower", "The New Arab"),
    (23, "nvda", "Nvidia falls over 8% in a day", "Reuters"),
    (25, "oil", "Oil touches three-month lows", "Reuters"),
    (27, "quake", "Magnitude 5.3 quake, Nepal", "The Hindu"),
    (33, "shanghai", "China probes Shanghai chief", "Reuters"),
    (32, "storm", "Thanksgiving travel storms", "Nat. Weather Service"),
    (9, "well", "UNRWA worker killed, Jabalia", "Al Jazeera"),
]


def build():
    assert len(STORIES) == 40
    cv = Canvas(W, H, PAPER)

    # ---- masthead: navy band, serif title, gold rule
    cv.fill(0, 0, W, 76, NAVY)
    cv.text_center("mast", W // 2, 56, "THE WEDNESDAY EDITION", CREAM,
                   max_width=1000)
    cv.hline(0, 76, W, GOLD, 3)

    # ---- dateline: the day, named large, with the story count
    cv.draw_text("kick", 16, 100, "40 STORIES", INK, max_width=200)
    cv.text_center("date", W // 2, 101, "TUESDAY 24 NOVEMBER 2026", CRIMSON,
                   max_width=700)
    cv.draw_text("kick", 1008 - font("kick").width("EVERY STORY SOURCED"),
                 100, "EVERY STORY SOURCED", INK, max_width=250)
    cv.hline(16, 110, 992, INK, 1)

    # ---- hero: story 1, illustration left, headline + deck right
    blit_cover(cv, 16, 116, 210, 158, load_still("drones"))
    cv.fill(16, 116, 210, 3, CRIMSON)
    cv.draw_text("kick", 238, 132, "WAR IN UKRAINE - 96 DRONES OVERNIGHT",
                 CRIMSON, max_width=770)
    lines = cv.wrap("hero", HERO_HEADLINE, 770, 2)
    y = 162
    for ln in lines:
        cv.draw_text("hero", 238, y, ln, INK, max_width=770)
        y += 29
    deck = cv.wrap("deck", HERO_DECK, 770, 3)
    y = 232
    for ln in deck:
        cv.draw_text("deck", 238, y, ln, INK, max_width=770)
        y += 17
    cv.draw_text("src", 238, 268, "Sources: Ukrinform / Kyiv24", GREY,
                 max_width=770)

    # ---- features: 4 across, then 3 across, each with its own scene
    cols4 = [16, 267, 518, 769]
    cols3 = [141, 392, 643]
    rows = [(280, cols4, FEATURES[:4]), (482, cols3, FEATURES[4:])]
    for rowy, cols, feats in rows:
        for colx, (num, still, cap, src) in zip(cols, feats):
            blit_cover(cv, colx + 9, rowy, 220, 150, load_still(still))
            cv.fill(colx + 9, rowy, 220, 3, CRIMSON)
            cap_lines = cv.wrap("feat", cap, 239, 2)
            cy = rowy + 168
            for ln in cap_lines:
                cv.draw_text("feat", colx, cy, ln, INK, max_width=239)
                cy += 17
            cv.draw_text("src", colx, rowy + 198,
                         "%d. %s" % (num, src), GREY, max_width=239)

    # ---- the full list: all 40 stories, numbered, source beside each
    cv.hline(16, 692, 992, INK, 1)
    for i, (headline, src) in enumerate(STORIES):
        n = i + 1
        col = 0 if n <= 20 else 1
        row = (n - 1) % 20
        x = 16 if col == 0 else 514
        baseline = 712 + row * 15
        num_txt = "%d." % n
        cv.draw_text("bodyb", x, baseline, num_txt, CRIMSON, max_width=40)
        hx = x + font("bodyb").width(num_txt) + 5
        # Headline first, then the source, on the same line.
        cv.draw_text("body", hx, baseline, headline, INK, max_width=486)
        sx = hx + font("body").width(headline) + 6
        cv.draw_text("src", sx, baseline, src, GREY, max_width=486 - (sx - x))

    # ---- footer
    cv.text_center("src", W // 2, 1016,
                   "TUESDAY 24 NOVEMBER 2026 - 40 STORIES, EVERY STORY SOURCED",
                   GREY, max_width=1000)
    return cv


def main():
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if not outdir:
        outdir = os.path.join(os.getcwd(), "output")
    os.makedirs(outdir, exist_ok=True)
    cv = build()
    path = os.path.join(outdir, "entry.png")
    nbytes = write_png(cv, path)
    print("wrote %s (%d bytes)" % (path, nbytes))
    if nbytes > 1048576:
        raise SystemExit("entry.png exceeds 1 MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

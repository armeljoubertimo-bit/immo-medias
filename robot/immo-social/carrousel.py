# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10", "pillow-heif>=0.16"]
# ///
"""Générateur de carrousels Instagram — Immo Social (Armel Joubert).

Direction artistique propre à Armel : 3 palettes (noir & or, vert sapin & jaune, ardoise & bleu ciel)
qui alternent chaque semaine ; pas de logo.
Transforme slides.txt en images JPEG 1080×1350 (01.jpg, 02.jpg…) selon ~/immo-social/charte/charte.json.

FORMAT DE slides.txt — slides séparées par une ligne « --- »

  1re slide = COUVERTURE (photo + titre en bas)
      Vendre à Marseille                ← 1re ligne : petite étiquette (facultative, commence par « # »)
      Les *4 critères* qui font         ← titre ; *étoiles* = mots sur fond rouge
      le prix de votre appartement
  (si aucune ligne ne commence par « # », l'étiquette par défaut de la charte est utilisée)

  Slides suivantes = CONSEIL
      Critère 01                        ← 1re ligne : étiquette (pastille rouge)
      ## L'emplacement                  ← « ## » : titre (serif)
      Texte d'explication…              ← texte  (« - » = puce)
      > À retenir / ma solution…        ← « > » : encadré mis en avant

  La slide finale « Estimation offerte » est ajoutée automatiquement ([sans estimation] pour l'enlever).

  Mise en page : alterne d'un post à l'autre entre « uni » (fond blanc) et « photo » (photos en
  fond, texte en bas). Forcer : [style: uni] / [style: photo].
  Photos (~/immo-social/photos/…) : [photo: apparts] / [photo: rues/x.jpg] / [sans photo].

Usage : carrousel.py <dossier du post>
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:  # photos iPhone (HEIC)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

CHARTE_DIR = Path.home() / "immo-social" / "charte"
DEFAULT = {
    "format": [1080, 1350],
    "marge": 100,
    # 3 palettes qui alternent chaque semaine (selon la date du post).
    "palettes": [
        {"nom": "Noir & or", "primaire": "#121416", "accent": "#C9A24B", "accent_texte": "#121416",
         "clair": "#FFFFFF", "fond_doux": "#F3F1EC", "texte": "#121416", "texte_doux": "#5A5A5A"},
        {"nom": "Vert sapin & jaune", "primaire": "#0F3D2E", "accent": "#F2C230", "accent_texte": "#0F3D2E",
         "clair": "#FFFFFF", "fond_doux": "#EEF3EF", "texte": "#0F3D2E", "texte_doux": "#4F6359"},
        {"nom": "Ardoise & bleu ciel", "primaire": "#1B2433", "accent": "#2F9BFF", "accent_texte": "#FFFFFF",
         "clair": "#FFFFFF", "fond_doux": "#EEF2F7", "texte": "#1B2433", "texte_doux": "#56617A"},
    ],
    "polices": {
        "titre": "Poppins-Bold.ttf",        # titres
        "titre_graisse": "Bold",
        "affiche": "Poppins-Bold.ttf",      # couverture, étiquettes, boutons
        "texte": "Inter-Regular.otf",
        "gras": "Inter-Bold.otf",
    },
    "etiquette": "Conseil immo · Marseille",
    "logo": "",
    "logo_taille": 0,
    "signature": "Armel Joubert",
    "cta": {
        "etiquette": "Vous pensez vendre ?",
        "titre": "Estimation offerte",
        "texte": "Je vous donne la valeur réelle de votre bien à Marseille, gratuitement et sans engagement.",
        "bouton": "Écrivez ESTIMATION en message privé",
    },
    "photos": {
        "dossier": "~/immo-social/photos",
        "couverture": True,
        "couverture_dossier": "apparts",
    },
    "styles": ["uni", "photo"],
}


# ------------------------------------------------------------------ outils

def load_charte() -> dict:
    c = json.loads(json.dumps(DEFAULT))
    f = CHARTE_DIR / "charte.json"
    if f.exists():
        for k, v in json.loads(f.read_text()).items():
            if isinstance(v, dict) and isinstance(c.get(k), dict):
                c[k].update(v)
            else:
                c[k] = v
    return c


def font(charte: dict, kind: str, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    name = charte["polices"][kind]
    for cand in (CHARTE_DIR / "polices" / name, Path(__file__).parent / "polices" / name, Path(name)):
        if cand.exists():
            f = ImageFont.truetype(str(cand), size)
            break
    else:
        f = ImageFont.truetype(name, size)
    try:
        f.set_variation_by_name(weight or "Regular")
    except Exception:  # noqa: BLE001  (police non variable)
        pass
    return f


def title_font(charte, size):
    return font(charte, "titre", size, charte["polices"].get("titre_graisse", "Bold"))


def clean(text: str) -> str:
    text = re.sub(r"[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F]", "", text).strip()
    # typographie française : la ponctuation haute reste collée au mot précédent
    text = re.sub(r" ([:;?!\u00bb])", "\u00a0\\1", text)
    return re.sub(r"\u00ab ", "\u00ab\u00a0", text)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[ \t\n]+", text) if w]


def wrap(draw, text: str, fnt, width: int) -> list[str]:
    words, lines, cur = _words(text), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=fnt) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def wrap_rich(draw, text: str, fnt, width: int) -> list[list[tuple[str, bool]]]:
    """Comme wrap, mais garde l'info « mot mis en avant » (*…*) mot par mot."""
    words = []
    for i, part in enumerate(re.split(r"\*", text)):
        words += [(w, i % 2 == 1) for w in _words(part)]
    lines, cur = [], []
    for w in words:
        test = " ".join(x for x, _ in cur + [w])
        if draw.textlength(test, font=fnt) <= width or not cur:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    if cur:
        lines.append(cur)
    return lines


def hexa(c: str, alpha: int) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def _charte_path(name):
    if not name:
        return None
    p = Path(name).expanduser()
    if not p.is_absolute():
        p = CHARTE_DIR / p
    return p if p.exists() else None


def paste_logo(img, charte):
    """Logo en bas à droite, sur une petite carte blanche (lisible sur tous les fonds)."""
    p = _charte_path(charte.get("logo"))
    if not p:
        return
    W, H = img.size
    lg = Image.open(p).convert("RGBA")
    s = charte.get("logo_taille", 118)
    lg.thumbnail((s, s))
    pad = 12
    x1, y1 = W - 40, H - 40
    x0, y0 = x1 - lg.width - 2 * pad, y1 - lg.height - 2 * pad
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x1, y1], radius=14, fill="#FFFFFF")
    img.paste(lg, (x0 + pad, y0 + pad), lg)


def pill(draw, x, y, text, charte, bg, fg, size=28):
    f = font(charte, "affiche", size)
    t = text.upper()
    w = draw.textlength(t, font=f) + len(t) * 1.5
    h = size * 1.9
    draw.rounded_rectangle([x, y, x + w + 2 * 26, y + h], radius=h / 2, fill=bg)
    cx = x + 26
    for ch in t:  # léger espacement des lettres
        draw.text((cx, y + h / 2), ch, font=f, fill=fg, anchor="lm")
        cx += draw.textlength(ch, font=f) + 1.5
    return h


def progress(draw, charte, W, H, idx, total, on_dark, active=None):
    """Barre de progression en bas à gauche (position dans le carrousel)."""
    col = charte["couleurs"]
    x, y, seg, gap = 48, H - 64, 46, 10
    for i in range(total):
        fill = (active or (col["clair"] if on_dark else col["accent"])) if i == idx else (hexa(col["clair"], 110) if on_dark else hexa(col["primaire"], 50))
        draw.rounded_rectangle([x, y, x + seg, y + 8], radius=4, fill=fill)
        x += seg + gap


PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
_USED: set = set()


def pick_photo(charte, spec: str | None = None, unique: bool = False) -> Path | None:
    """Photo de la bibliothèque (spec = sous-dossier ou fichier). unique=True : jamais 2× dans le post."""
    base = Path(charte["photos"]["dossier"]).expanduser()
    if not base.exists():
        return None
    root = base
    if spec:
        cand = base / spec
        if cand.is_file():
            return cand
        if cand.is_dir():
            root = cand
    photos = [p for p in root.rglob("*") if p.suffix.lower() in PHOTO_EXT and not p.name.startswith(".")]
    if not photos and root != base:
        photos = [p for p in base.rglob("*") if p.suffix.lower() in PHOTO_EXT and not p.name.startswith(".")]
    if unique:
        photos = [p for p in photos if str(p) not in _USED]
    if not photos:
        return None
    hist_f = base / ".deja-utilisees.json"
    try:
        hist = json.loads(hist_f.read_text())
    except Exception:  # noqa: BLE001
        hist = []
    fresh = [p for p in photos if str(p) not in hist and str(p) not in _USED] or \
            [p for p in photos if str(p) not in _USED] or photos
    choice = random.choice(fresh)
    _USED.add(str(choice))
    try:
        hist_f.write_text(json.dumps((hist + [str(choice)])[-max(10, len(photos) // 2):]))
    except OSError:
        pass
    return choice


def photo_canvas(path: Path, size, couleur: str, strength: float = 0.92) -> Image.Image:
    """Photo plein cadre + dégradé marine qui monte du bas (le texte se pose en bas)."""
    W, H = size
    im = ImageOps.fit(ImageOps.exif_transpose(Image.open(path)).convert("RGB"), size, Image.LANCZOS)
    grad = Image.linear_gradient("L").resize((W, H))            # 0 en haut → 255 en bas
    grad = grad.point(lambda v: int(255 * strength * min(1, max(0, (v / 255 - 0.18) / 0.62)) ** 1.1))
    base = Image.composite(Image.new("RGB", size, couleur), im, grad)
    veil = Image.new("RGB", size, couleur)
    return Image.blend(base, veil, 0.12)


# ------------------------------------------------------------------ slides

def cover(charte, lines: list[str], photo: Path | None, total: int) -> Image.Image:
    W, H = charte["format"]
    col, M = charte["couleurs"], charte["marge"]
    tag = charte["etiquette"]
    if lines and lines[0].startswith("#"):
        tag, lines = lines[0].lstrip("#").strip(), lines[1:]
    text = " ".join(lines)
    on_dark = photo is not None
    img = photo_canvas(photo, (W, H), col["primaire"]) if photo else Image.new("RGB", (W, H), col["primaire"])
    d = ImageDraw.Draw(img, "RGBA")
    width = W - 2 * M
    size = 108
    while size > 60:
        f = font(charte, "affiche", size)
        rich = wrap_rich(d, text, f, width)
        lh = size * 1.16
        if len(rich) * lh <= H * 0.44:
            break
        size -= 4
    block = len(rich) * lh
    y = H - 215 - block
    ph = pill(d, M, y - 110, tag, charte, col["accent"], col["accent_texte"])
    asc, desc = f.getmetrics()
    for ln in rich:
        x, i = M, 0
        while i < len(ln):
            j = i
            while j < len(ln) and ln[j][1] == ln[i][1]:
                j += 1
            run = " ".join(w for w, _ in ln[i:j])
            w_run = d.textlength(run, font=f)
            if ln[i][1]:   # mots-clés : bloc rouge, texte blanc
                d.rectangle([x - 14, y + asc * 0.16, x + w_run + 14, y + asc + desc * 0.55], fill=col["accent"])
            d.text((x, y), run, font=f, fill=col["accent_texte"] if ln[i][1] else col["clair"])
            x += w_run + d.textlength(" ", font=f)
            i = j
        y += lh
    # « Glissez → »
    fs = font(charte, "affiche", 28)
    ay = H - 60
    end = W - 48 - charte.get("logo_taille", 110) - 36
    ax = end - 60 - d.textlength("Glissez", font=fs)
    d.text((ax, ay), "Glissez", font=fs, fill=col["clair"], anchor="lm")
    x0 = ax + d.textlength("Glissez", font=fs) + 14
    d.line([x0, ay, x0 + 40, ay], fill=col["clair"], width=4)
    d.polygon([(x0 + 46, ay), (x0 + 32, ay - 10), (x0 + 32, ay + 10)], fill=col["clair"])
    progress(d, charte, W, H, 0, total, True)
    paste_logo(img, charte)
    return img


def advice(charte, lines: list[str], idx: int, total: int, bg_photo: Path | None = None,
           band_photo: Path | None = None, cta_mode: bool = False) -> Image.Image:
    W, H = charte["format"]
    col, M = charte["couleurs"], charte["marge"]
    on_dark = bg_photo is not None or cta_mode
    if cta_mode:
        img = Image.new("RGB", (W, H), col["accent"])
    elif bg_photo:
        img = photo_canvas(bg_photo, (W, H), col["primaire"], 0.95)
    else:
        img = Image.new("RGB", (W, H), col["clair"])
    top = 0
    if band_photo and not on_dark:
        bh = int(H * 0.33)
        img.paste(ImageOps.fit(ImageOps.exif_transpose(Image.open(band_photo)).convert("RGB"), (W, bh),
                               Image.LANCZOS), (0, 0))
        top = bh
    d = ImageDraw.Draw(img, "RGBA")
    if not on_dark and not top:      # bandeau de couleur en haut des slides blanches
        d.rectangle([0, 0, W, 22], fill=col["accent"])
    txt = col["accent_texte"] if cta_mode else (col["clair"] if on_dark else col["texte"])
    width = W - 2 * M
    tag, body = lines[0], lines[1:]

    def layout(sc):
        out = []
        for ln in body:
            if ln.startswith("##"):
                s = int(70 * sc)
                f = title_font(charte, s)
                out.append(("titre", wrap(d, ln.lstrip("#").strip(), f, width), f, s, 1.14, int(34 * sc)))
            elif ln.startswith(">"):
                s = int(38 * sc)
                f = font(charte, "gras", s)
                out.append(("encadre", wrap(d, ln[1:].strip(), f, width - 70), f, s, 1.42, int(26 * sc)))
            elif ln.startswith(("-", "•")):
                s = int(39 * sc)
                f = font(charte, "texte", s)
                out.append(("puce", wrap(d, ln.lstrip("-• ").strip(), f, width - 46), f, s, 1.42, int(12 * sc)))
            else:
                s = int(39 * sc)
                f = font(charte, "texte", s)
                out.append(("texte", wrap(d, ln, f, width), f, s, 1.45, int(26 * sc)))
        h = 0
        for k, ls, f, s, sp, g in out:
            h += len(ls) * s * sp + g + (44 if k == "encadre" else 0)
        return out, h - (out[-1][5] if out else 0)

    pill_h = 28 * 1.9 + 40
    avail = H - top - 2 * M - pill_h - 60
    sc = 1.0
    while True:
        blocks, h = layout(sc)
        if h <= avail or sc < 0.6:
            break
        sc -= 0.05
    total_h = pill_h + h
    if bg_photo:                       # texte posé en bas, sur le dégradé
        y = H - 225 - total_h
    elif top:
        y = top + 60
    else:
        y = (H - total_h) / 2 - 20
    pill(d, M, y, tag, charte, col["primaire"] if cta_mode else col["accent"],
         col["clair"] if cta_mode else col["accent_texte"])
    y += pill_h
    for kind, ls, f, s, sp, gap in blocks:
        if kind == "encadre":
            bh = len(ls) * s * sp + 44
            fill = hexa(col["primaire"], 150) if on_dark else col["fond_doux"]
            d.rounded_rectangle([M, y, W - M, y + bh], radius=18, fill=fill)
            d.rectangle([M, y, M + 10, y + bh], fill=col["primaire"] if cta_mode else col["accent"])
            yy = y + 22
            for ln in ls:
                d.text((M + 42, yy), ln, font=f, fill=col["clair"] if on_dark else col["primaire"])
                yy += s * sp
            y += bh + gap
            continue
        for ln in ls:
            if kind == "puce":
                r = s * 0.16
                cy = y + s * 0.62
                d.ellipse([M + 4, cy - r, M + 4 + 2 * r, cy + r], fill=col["accent"] if not cta_mode else col["clair"])
                d.text((M + 46, y), ln, font=f, fill=txt)
            else:
                d.text((M, y), ln, font=f, fill=txt)
            y += s * sp
        y += gap
    if charte.get("signature") and not bg_photo:
        fs = font(charte, "texte", 24)
        d.text((W - 48 - charte.get("logo_taille", 110) - 20, H - 60), charte["signature"], font=fs,
               fill=hexa(txt, 170), anchor="rm")
    progress(d, charte, W, H, idx, total, on_dark, col["primaire"] if cta_mode else None)
    paste_logo(img, charte)
    return img


def cta(charte, idx, total) -> Image.Image:
    c = charte["cta"]
    W, H = charte["format"]
    col = charte["couleurs"]
    img = advice(charte, [c["etiquette"], "## " + c["titre"], c["texte"]], idx, total, cta_mode=True)
    d = ImageDraw.Draw(img, "RGBA")
    # bouton
    f = font(charte, "affiche", 34)
    M = charte["marge"]
    bw = d.textlength(c["bouton"], font=f) + 100
    y = H - 300
    d.rounded_rectangle([M, y, M + bw, y + 104], radius=52, fill=col["primaire"])
    d.text((M + 50, y + 52), c["bouton"], font=f, fill=col["clair"], anchor="lm")
    return img


# ------------------------------------------------------------------ lecture de slides.txt

TAG_RE = re.compile(r"^\[(photo(?:\s*:\s*([^\]]+))?|sans photo)\]$", re.I)
STYLE_RE = re.compile(r"(?im)^\[style\s*:\s*(\w+)\]\s*$")


def next_style(charte) -> str:
    styles = charte.get("styles") or ["uni"]
    f = CHARTE_DIR / ".compteur-style"
    try:
        n = int(f.read_text())
    except Exception:  # noqa: BLE001
        n = 0
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(n + 1))
    except OSError:
        pass
    return styles[n % len(styles)]


def parse(text: str):
    with_cta = "[sans estimation]" not in text.lower()
    text = re.sub(r"(?im)^\[sans estimation\]\s*$", "", text)
    slides = []
    for chunk in re.split(r"(?m)^\s*---+\s*$", text):
        photo, lines = None, []
        for raw in chunk.strip().splitlines():
            m = TAG_RE.match(raw.strip())
            if m:
                photo = "-" if m.group(1).lower() == "sans photo" else (m.group(2) or "").strip()
                continue
            ln = clean(raw)
            if ln:
                lines.append(ln)
        if lines:
            slides.append((lines, photo))
    return slides, with_cta


def palette_for(charte: dict, folder: Path) -> dict:
    """Palette de la semaine : dépend de la date du dossier (AAAA-MM-JJ…), sinon de la date du jour."""
    import datetime
    pals = charte.get("palettes") or []
    if not pals:
        return charte["couleurs"]
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", folder.name)
    try:
        day = datetime.date(*map(int, m.groups())) if m else datetime.date.today()
    except ValueError:
        day = datetime.date.today()
    return pals[(day.isocalendar()[1] + 1) % len(pals)]


def render(folder: Path) -> list[Path]:
    folder = Path(folder).expanduser()
    charte = load_charte()
    charte["couleurs"] = palette_for(charte, folder)
    raw = (folder / "slides.txt").read_text()
    m = STYLE_RE.search(raw)
    style = m.group(1).lower() if m else next_style(charte)
    slides, with_cta = parse(STYLE_RE.sub("", raw))
    if not slides:
        raise ValueError("slides.txt est vide.")
    total = len(slides) + (1 if with_cta else 0)
    if total > 10:
        raise ValueError(f"{total} slides : Instagram accepte 10 maximum.")
    _USED.clear()
    lines0, p0 = slides[0]
    if p0 == "-" or (p0 is None and not charte["photos"].get("couverture")):
        cover_photo = None
    else:
        cover_photo = pick_photo(charte, p0 or charte["photos"].get("couverture_dossier"))
    imgs = [cover(charte, lines0, cover_photo, total)]
    for i, (lines, p) in enumerate(slides[1:], start=1):
        if style == "photo" and p != "-":
            bg = pick_photo(charte, p or None, unique=True)   # pas assez de photos → fond uni
            imgs.append(advice(charte, lines, i, total, bg_photo=bg))
        else:
            band = pick_photo(charte, p or None) if p is not None and p != "-" else None
            imgs.append(advice(charte, lines, i, total, band_photo=band))
    if with_cta:
        imgs.append(cta(charte, total - 1, total))
    out = []
    for old in folder.glob("[0-9][0-9].jpg"):
        old.unlink()
    for i, im in enumerate(imgs, start=1):
        p = folder / f"{i:02d}.jpg"
        im.convert("RGB").save(p, "JPEG", quality=93, optimize=True)
        out.append(p)
    return out


if __name__ == "__main__":
    for p in render(Path(sys.argv[1])):
        print(p)

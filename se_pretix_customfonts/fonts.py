# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 the sE-pretix authors
"""Schrift-Verarbeitung ohne Django-Abhängigkeit (testbar ohne pretix).

Pipeline pro Upload-Datei (TTF/OTF/WOFF/WOFF2, oder ZIP mit solchen):
  analysieren (Familie, Gewicht, kursiv) -> TrueType-Fassung für PDFs (reportlab kann kein CFF/OTF)
  -> WOFF2/WOFF für das Web -> ablegen unter <root>/<slug>/<stil>.{ttf,woff2|woff} -> registry.json

pretix kennt pro Familie nur vier Stile: regular, bold, italic, bolditalic. Gewichte außer 400/700 werden deshalb
zu eigenen Familien („Titillium Light“, „Titillium Semibold“ …), jeweils mit regular/italic.
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError, newTable

STYLES = ("regular", "bold", "italic", "bolditalic")
FONT_EXTENSIONS = (".ttf", ".otf", ".woff", ".woff2")
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_FILES = 80
MAX_ZIP_UNCOMPRESSED = 120 * 1024 * 1024
RESERVED_FAMILIES = {"open sans"}

WEIGHT_NAMES = {
    100: "Thin", 200: "ExtraLight", 250: "Thin", 300: "Light", 350: "Light", 500: "Medium",
    600: "Semibold", 800: "ExtraBold", 900: "Black",
}


class FontError(ValueError):
    pass


@dataclass
class Analysis:
    filename: str
    base_family: str
    weight: int
    italic: bool
    upright_marker: bool
    is_cff: bool
    embeddable: bool
    family: str = ""      # endgültiger pretix-Familienname
    style: str = ""       # regular|bold|italic|bolditalic


@dataclass
class Result:
    filename: str
    ok: bool
    family: str = ""
    style: str = ""
    message: str = ""


@dataclass
class Registry:
    families: dict = field(default_factory=dict)   # name -> {"slug", "styles": {style: {...}}, "added"}
    version: int = 0


# ----------------------------------------------------------------------------------------------
# Analyse
# ----------------------------------------------------------------------------------------------
def _name(font: TTFont, *ids: int) -> str | None:
    n = font["name"]
    for i in ids:
        s = n.getDebugName(i)
        if s:
            return s.strip()
    return None


def nearest_weight(w: int) -> int:
    known = (100, 200, 250, 300, 350, 400, 500, 600, 700, 800, 900)
    return min(known, key=lambda k: abs(k - w))


def analyze(filename: str, font: TTFont, family_override: str | None = None) -> Analysis:
    stem = Path(filename).stem.lower()
    typo_sub = (_name(font, 17, 2) or "").lower()
    os2 = font["OS/2"] if "OS/2" in font else None
    weight = nearest_weight(int(getattr(os2, "usWeightClass", 400) or 400))

    upright = "upright" in stem or "upright" in typo_sub
    if upright:
        italic = False
    elif "italic" in stem or "oblique" in stem or "italic" in typo_sub or "oblique" in typo_sub:
        italic = True
    else:
        italic = bool(os2 is not None and os2.fsSelection & 0b1) or (
            "post" in font and getattr(font["post"], "italicAngle", 0) != 0)

    base = (family_override or "").strip() or _name(font, 16, 1) or Path(filename).stem.split("-")[0]
    fs_type = int(getattr(os2, "fsType", 0) or 0)
    embeddable = not (fs_type & 0x0002)   # Bit 1 = "Restricted License embedding"

    a = Analysis(filename=filename, base_family=_clean_family(base), weight=weight, italic=italic,
                 upright_marker=upright, is_cff="CFF " in font or "CFF2" in font, embeddable=embeddable)
    if weight == 400:
        a.family, a.style = a.base_family, "italic" if italic else "regular"
    elif weight == 700:
        a.family, a.style = a.base_family, "bolditalic" if italic else "bold"
    else:
        label = WEIGHT_NAMES.get(weight, str(weight))
        a.family = f"{a.base_family} {label}"
        a.style = "italic" if italic else "regular"
    return a


def _clean_family(s: str) -> str:
    s = re.sub(r"[^\w .\-]", "", s, flags=re.UNICODE).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        raise FontError("Familienname leer")
    return s[:60]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not s:
        raise FontError("Ungültiger Familienname")
    return s[:60]


# ----------------------------------------------------------------------------------------------
# Konvertierung
# ----------------------------------------------------------------------------------------------
def otf_to_ttf(font: TTFont, max_err: float = 1.0) -> None:
    """CFF-Kontur (OTF) -> TrueType-Kontur in place (nach fontTools' otf2ttf-Beispiel)."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    if "CFF " not in font:
        raise FontError("CFF2/Variable-Fonts werden nicht unterstützt (bitte statische Schnitte hochladen).")
    glyph_order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    quad = {}
    for name in glyph_order:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, max_err, reverse_direction=True))
        quad[name] = pen.glyph()

    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = glyph_order
    glyf.glyphs = quad
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)

    hmtx = font["hmtx"]
    for name, glyph in glyf.glyphs.items():
        if hasattr(glyph, "xMin"):
            hmtx[name] = (hmtx[name][0], glyph.xMin)

    font["maxp"] = maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.maxZones = 1
    maxp.maxTwilightPoints = 0
    maxp.maxStorage = 0
    maxp.maxFunctionDefs = 0
    maxp.maxInstructionDefs = 0
    maxp.maxStackElements = 0
    maxp.maxSizeOfInstructions = 0
    maxp.maxComponentElements = max(len(getattr(g, "components", []) or []) for g in glyf.glyphs.values())
    maxp.compile(font)

    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = glyph_order
    font.sfntVersion = "\000\001\000\000"


def _save(font: TTFont, flavor: str | None) -> bytes:
    buf = io.BytesIO()
    font.flavor = flavor
    font.save(buf)
    return buf.getvalue()


def _reload(data: bytes) -> TTFont:
    return TTFont(io.BytesIO(data), recalcBBoxes=True)


def convert(data: bytes) -> tuple[bytes, bytes, str]:
    """Rohdaten -> (ttf_bytes, web_bytes, web_ext). Web = woff2 (brotli) oder woff."""
    try:
        font = _reload(data)
    except (TTLibError, Exception) as e:   # fontTools wirft diverse Typen bei kaputten Dateien
        raise FontError(f"Datei ist keine lesbare Schrift ({type(e).__name__}).")
    if "glyf" not in font:
        otf_to_ttf(font)
    font.flavor = None
    ttf = _save(font, None)

    for flavor, ext in (("woff2", ".woff2"), ("woff", ".woff")):
        try:
            return ttf, _save(_reload(ttf), flavor), ext
        except ImportError:        # brotli fehlt -> WOFF
            continue
    return ttf, ttf, ".ttf"


# ----------------------------------------------------------------------------------------------
# Registry / Ablage
# ----------------------------------------------------------------------------------------------
class FontStore:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        self.registry_file = self.root / "registry.json"

    # -- Lesen ----------------------------------------------------------------------------
    def load(self) -> Registry:
        try:
            d = json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Registry()
        return Registry(families=d.get("families", {}), version=int(d.get("version", 0)))

    def mtime(self) -> float:
        try:
            return self.registry_file.stat().st_mtime
        except OSError:
            return 0.0

    def _write(self, reg: Registry) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        reg.version += 1
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"version": reg.version, "families": reg.families}, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, self.registry_file)

    # -- Upload ---------------------------------------------------------------------------
    def install(self, uploads: list[tuple[str, bytes]], family_override: str | None = None) -> list[Result]:
        """uploads: [(dateiname, bytes)] (ZIPs werden entpackt). Gibt ein Ergebnis pro Datei zurück."""
        files = self._expand(uploads)
        results: list[Result] = []
        analyses: list[tuple[Analysis, bytes]] = []
        for name, data in files:
            try:
                font = _reload(data)
                a = analyze(name, font, family_override)
                if not a.embeddable:
                    raise FontError("Lizenz erlaubt keine Einbettung (OS/2 fsType: restricted).")
                if a.family.lower() in RESERVED_FAMILIES:
                    raise FontError(f"„{a.family}“ ist in pretix fest eingebaut.")
                analyses.append((a, data))
            except FontError as e:
                results.append(Result(name, False, message=str(e)))
            except Exception as e:
                results.append(Result(name, False, message=f"Keine lesbare Schrift ({type(e).__name__})."))

        # Doppelte (Familie, Stil): "Upright"-Duplikate verlieren
        best: dict[tuple[str, str], tuple[Analysis, bytes]] = {}
        for a, data in analyses:
            key = (a.family, a.style)
            cur = best.get(key)
            if cur is None or (cur[0].upright_marker and not a.upright_marker):
                if cur is not None:
                    results.append(Result(cur[0].filename, False, a.family, a.style, "doppelt, übersprungen"))
                best[key] = (a, data)
            else:
                results.append(Result(a.filename, False, a.family, a.style, "doppelt, übersprungen"))

        reg = self.load()
        for (family, style), (a, data) in sorted(best.items()):
            try:
                ttf, web, ext = convert(data)
            except FontError as e:
                results.append(Result(a.filename, False, family, style, str(e)))
                continue
            slug = slugify(family)
            fam = reg.families.setdefault(family, {"slug": slug, "styles": {}, "added": _now()})
            d = self.root / fam["slug"]
            d.mkdir(parents=True, exist_ok=True)
            for old in d.glob(f"{style}.*"):
                old.unlink()
            (d / f"{style}.ttf").write_bytes(ttf)
            (d / f"{style}{ext}").write_bytes(web) if ext != ".ttf" else None
            fam["styles"][style] = {"source": a.filename, "web": ext, "cff_converted": a.is_cff, "weight": a.weight}
            note = "von OTF/CFF nach TrueType konvertiert" if a.is_cff else "installiert"
            results.append(Result(a.filename, True, family, style, note))
        if best:
            self._write(reg)
        return results

    def delete_family(self, family: str) -> bool:
        reg = self.load()
        fam = reg.families.pop(family, None)
        if not fam:
            return False
        d = self.root / fam["slug"]
        if d.is_dir() and d.resolve().parent == self.root.resolve():
            for p in d.iterdir():
                p.unlink()
            d.rmdir()
        self._write(reg)
        return True

    def delete_style(self, family: str, style: str) -> bool:
        reg = self.load()
        fam = reg.families.get(family)
        if not fam or style not in fam["styles"]:
            return False
        for p in (self.root / fam["slug"]).glob(f"{style}.*"):
            p.unlink()
        del fam["styles"][style]
        if not fam["styles"]:
            return self.delete_family(family)
        self._write(reg)
        return True

    # -- Für pretix -------------------------------------------------------------------------
    def payload(self, rel_prefix: str = "customfonts") -> dict:
        """Dictionary für das pretix-Signal register_fonts (nur vollständige Familien mit Regular)."""
        out = {}
        for family, fam in self.load().families.items():
            styles = fam.get("styles", {})
            if "regular" not in styles:
                continue
            entry = {}
            ok = True
            for style, meta in styles.items():
                base = f"{rel_prefix}/{fam['slug']}/{style}"
                if not (self.root / fam["slug"] / f"{style}.ttf").is_file():
                    ok = False
                    break
                formats = {"truetype": base + ".ttf"}
                if meta.get("web") in (".woff2", ".woff"):
                    formats[meta["web"].lstrip(".")] = base + meta["web"]
                entry[style] = formats
            if ok:
                out[family] = entry
        return out

    # -- Hilfen -----------------------------------------------------------------------------
    @staticmethod
    def _expand(uploads: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = []
        for name, data in uploads:
            base = os.path.basename(name or "")
            if base.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        infos = [i for i in zf.infolist()
                                 if not i.is_dir() and i.filename.lower().endswith(FONT_EXTENSIONS)
                                 and "__macosx" not in i.filename.lower()
                                 and not os.path.basename(i.filename).startswith(".")]
                        if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED:
                            raise FontError("ZIP ist entpackt zu groß.")
                        for i in infos:
                            if i.file_size > MAX_FILE_BYTES:
                                continue
                            out.append((os.path.basename(i.filename), zf.read(i)))
                except zipfile.BadZipFile:
                    raise FontError(f"{base}: keine gültige ZIP-Datei.")
            elif base.lower().endswith(FONT_EXTENSIONS):
                if len(data) > MAX_FILE_BYTES:
                    raise FontError(f"{base}: größer als {MAX_FILE_BYTES // 1024 // 1024} MB.")
                out.append((base, data))
            else:
                raise FontError(f"{base}: Dateityp nicht unterstützt (erlaubt: TTF, OTF, WOFF, WOFF2, ZIP).")
        if len(out) > MAX_FILES:
            raise FontError(f"Zu viele Dateien (max. {MAX_FILES}).")
        if not out:
            raise FontError("Keine Schriftdateien gefunden.")
        return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

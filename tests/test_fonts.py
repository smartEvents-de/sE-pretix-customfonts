# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 the sE-pretix authors
"""Tests der reinen Font-Pipeline (ohne pretix). Echte Schrift optional via TITILLIUM_ZIP=/pfad/Titillium.zip."""
import io
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from se_pretix_customfonts.fonts import FontError, FontStore, analyze  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402


def make_font(family="Testfont", sub="Regular", weight=400, cff=False, fs_type=0, typo_family=None):
    fb = FontBuilder(1000, isTTF=not cff)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    if cff:
        def glyph():
            pen = T2CharStringPen(600, None)
            pen.moveTo((0, 0)); pen.curveTo((100, 0), (200, 400), (300, 700)); pen.lineTo((500, 0)); pen.closePath()
            return pen.getCharString()
        fb.setupCFF("Test-" + sub, {"FullName": family}, {".notdef": glyph(), "A": glyph()}, {})
        fb.setupHorizontalMetrics({".notdef": (600, 0), "A": (600, 0)})
    else:
        def glyph():
            pen = TTGlyphPen(None)
            pen.moveTo((0, 0)); pen.lineTo((300, 700)); pen.lineTo((500, 0)); pen.closePath()
            return pen.glyph()
        fb.setupGlyf({".notdef": glyph(), "A": glyph()})
        fb.setupHorizontalMetrics({".notdef": (600, 0), "A": (600, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    names = {"familyName": family, "styleName": sub}
    if typo_family:
        names["typographicFamily"] = typo_family
        names["typographicSubfamily"] = sub
    fb.setupNameTable(names)
    fb.setupOS2(usWeightClass=weight, fsType=fs_type)
    fb.setupPost()
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def test_cff_converted_and_registrable(tmp_path):
    store = FontStore(tmp_path)
    res = store.install([("Test-Regular.otf", make_font(cff=True))])
    assert res[0].ok and "konvertiert" in res[0].message
    ttf = tmp_path / "testfont" / "regular.ttf"
    assert "glyf" in TTFont(str(ttf)) and "CFF " not in TTFont(str(ttf))
    from reportlab.pdfbase.ttfonts import TTFont as RLFont
    RLFont("x", str(ttf))   # darf nicht werfen
    assert store.payload()["Testfont"]["regular"]["truetype"] == "customfonts/testfont/regular.ttf"


def test_weights_become_families_and_upright_duplicates_dropped(tmp_path):
    store = FontStore(tmp_path)
    ups = [
        ("T-Regular.ttf", make_font(sub="Regular")),
        ("T-Bold.ttf", make_font(sub="Bold", weight=700)),
        ("T-BoldItalic.ttf", make_font(sub="Bold Italic", weight=700)),
        ("T-RegularUpright.ttf", make_font(sub="Regular Upright")),
        ("T-Light.ttf", make_font(sub="Light", weight=300)),
    ]
    res = store.install(ups)
    fams = store.load().families
    assert set(fams) == {"Testfont", "Testfont Light"}
    assert set(fams["Testfont"]["styles"]) == {"regular", "bold", "bolditalic"}
    assert any("doppelt" in r.message for r in res)
    # Upright-Duplikat verliert gegen die Datei ohne Marker
    assert fams["Testfont"]["styles"]["regular"]["source"] == "T-Regular.ttf"


def test_zip_and_family_override(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a/Regular.ttf", make_font(family="Kaputt Bd"))
        z.writestr("__MACOSX/a/._Regular.ttf", b"junk")
    store = FontStore(tmp_path)
    res = store.install([("pack.zip", buf.getvalue())], family_override="Mein Font")
    assert [r.family for r in res if r.ok] == ["Mein Font"]


def test_rejects_restricted_license_reserved_and_garbage(tmp_path):
    store = FontStore(tmp_path)
    res = store.install([("a.ttf", make_font(fs_type=2)), ("b.ttf", make_font(family="Open Sans")),
                         ("c.ttf", b"not a font")])
    assert not any(r.ok for r in res)
    assert not store.load().families
    with pytest.raises(FontError):
        store.install([("x.exe", b"MZ")])
    with pytest.raises(FontError):
        store.install([("x.zip", b"nope")])


def test_reinstall_replaces_and_delete(tmp_path):
    store = FontStore(tmp_path)
    store.install([("a.ttf", make_font())])
    v1 = store.load().version
    store.install([("a.ttf", make_font())])
    assert store.load().version == v1 + 1
    assert store.delete_family("Testfont")
    assert not (tmp_path / "testfont").exists() and store.payload() == {}


def test_payload_requires_regular_and_existing_files(tmp_path):
    store = FontStore(tmp_path)
    store.install([("b.ttf", make_font(sub="Bold", weight=700))])
    assert store.payload() == {}     # ohne Regular unbrauchbar für pretix


def test_analyze_italic_from_flags():
    f = TTFont(io.BytesIO(make_font(sub="Regular")))
    f["OS/2"].fsSelection |= 1
    assert analyze("Plain.ttf", f).style == "italic"
    assert analyze("Plain-Upright.ttf", f).style == "regular"


@pytest.mark.skipif(not os.environ.get("TITILLIUM_ZIP"), reason="echte Schrift nicht verfügbar")
def test_titillium(tmp_path):
    store = FontStore(tmp_path)
    store.install([("t.zip", Path(os.environ["TITILLIUM_ZIP"]).read_bytes())])
    fams = store.load().families
    assert set(fams) == {"Titillium", "Titillium Thin", "Titillium Light", "Titillium Semibold", "Titillium Black"}
    assert set(fams["Titillium"]["styles"]) == {"regular", "bold", "italic", "bolditalic"}

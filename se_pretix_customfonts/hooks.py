# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 the sE-pretix authors
"""Einhängen in pretix: Static-Finder (PDF), Static-URL (Web), PDF-Registrierungs-Cache."""
import logging
import os

from django.conf import settings
from django.contrib.staticfiles.finders import BaseFinder
from django.utils.functional import empty

from .storage import REL_PREFIX, get_store

logger = logging.getLogger(__name__)
FINDER_PATH = "se_pretix_customfonts.hooks.CustomFontsFinder"
_installed = False
_seen_version = [None]


class CustomFontsFinder(BaseFinder):
    """Findet Dateien unter 'customfonts/…' im MEDIA_ROOT (damit finders.find() sie für PDFs auflöst)."""

    def find(self, path, find_all=False, **kwargs):
        find_all = find_all or kwargs.get("all", False)
        norm = os.path.normpath(path or "")
        if not norm.startswith(REL_PREFIX + os.sep) or ".." in norm.split(os.sep):
            return [] if find_all else None
        full = os.path.join(settings.MEDIA_ROOT, norm)
        if os.path.isfile(full):
            return [full] if find_all else full
        return [] if find_all else None

    def list(self, ignore_patterns):
        return []   # nicht in collectstatic aufnehmen


def _patch_static_url():
    from django.contrib.staticfiles.storage import staticfiles_storage

    if staticfiles_storage._wrapped is empty:
        staticfiles_storage._setup()
    storage = staticfiles_storage._wrapped
    original = storage.url

    def url(name, *args, **kwargs):
        if name and name.startswith(REL_PREFIX + "/"):
            version = int(get_store().mtime())
            return f"{settings.MEDIA_URL.rstrip('/')}/{name}?v={version}"
        return original(name, *args, **kwargs)

    storage.url = url


def _patch_pdf_renderer():
    from pretix.base.pdf import Renderer

    original = Renderer.__dict__["_register_fonts"].__func__

    def _register_fonts(cls, event=None):
        version = get_store().mtime()
        if _seen_version[0] != version:
            if _seen_version[0] is not None:
                _reset_pdf_fonts(cls)
            _seen_version[0] = version
        return original(cls, event)

    _register_fonts._se_customfonts = True
    Renderer._register_fonts = classmethod(_register_fonts)


def _reset_pdf_fonts(cls):
    """Schriften wurden geändert: reportlab-Registrierung und pretix-Cache dieses Prozesses verwerfen."""
    try:
        from reportlab.pdfbase import pdfmetrics

        for family in get_store().load().families:
            for suffix in ("", " B", " I", " B I"):
                pdfmetrics._fonts.pop(family + suffix, None)
        for k in cls.__mro__:
            if "_fonts_registered" in k.__dict__:
                delattr(k, "_fonts_registered")
    except Exception:  # pragma: no cover
        logger.exception("Konnte PDF-Schriftcache nicht zurücksetzen")


def install():
    global _installed
    if _installed:
        return
    _installed = True
    if FINDER_PATH not in settings.STATICFILES_FINDERS:
        settings.STATICFILES_FINDERS = [*settings.STATICFILES_FINDERS, FINDER_PATH]
    for patch in (_patch_static_url, _patch_pdf_renderer):
        try:
            patch()
        except Exception:   # ein Fehler hier darf pretix nicht am Start hindern
            logger.exception("se_pretix_customfonts: %s fehlgeschlagen", patch.__name__)


def status() -> list[str]:
    """Selbstprüfung der Eingriffe in pretix. Rückgabe: Warnungen (leer = alles wie erwartet)."""
    w = []
    try:
        from django.contrib.staticfiles.storage import staticfiles_storage
        from pretix.base.pdf import Renderer
        from reportlab.pdfbase import pdfmetrics

        if FINDER_PATH not in settings.STATICFILES_FINDERS:
            w.append("Static-Finder ist nicht registriert: PDFs finden die Schriften nicht.")
        if not getattr(Renderer.__dict__.get("_register_fonts", None), "__func__", None) or \
                not getattr(Renderer.__dict__["_register_fonts"].__func__, "_se_customfonts", False):
            w.append("Der PDF-Schriftcache-Hook ist nicht aktiv: neu hochgeladene Schriften erscheinen in PDFs erst nach Neustart.")
        if not staticfiles_storage.url(f"{REL_PREFIX}/x/regular.ttf").startswith(settings.MEDIA_URL.rstrip("/")):
            w.append("Der Static-URL-Hook ist nicht aktiv: Web-Schriften werden nicht ausgeliefert.")
        if not isinstance(getattr(pdfmetrics, "_fonts", None), dict):
            w.append("reportlab hat die interne Schriftregistratur verändert: Austausch gleichnamiger Schriften braucht einen Neustart.")
    except Exception as e:   # pragma: no cover
        w.append(f"Prüfung fehlgeschlagen: {type(e).__name__}: {e}")
    return w

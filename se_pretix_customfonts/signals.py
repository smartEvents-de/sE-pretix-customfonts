# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 the sE-pretix authors
import logging

from django.contrib.staticfiles import finders
from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _

from pretix.control.signals import nav_global
from pretix.presale.style import register_fonts

from .storage import get_store

logger = logging.getLogger(__name__)
_cache = {"mtime": None, "data": {}}


@receiver(register_fonts, dispatch_uid="pretix_customfonts_register_fonts")
def register(sender, **kwargs):
    store = get_store()
    mtime = store.mtime()
    if _cache["mtime"] != mtime or _cache["mtime"] is None:
        data = {}
        for family, styles in store.payload().items():
            # Schutz: pretix bricht die PDF-Erzeugung ab, wenn ein Pfad nicht auffindbar ist.
            if all(finders.find(f["truetype"]) for f in styles.values()):
                data[family] = styles
            else:
                logger.error("Schrift %s nicht über die Static-Finder auffindbar, wird übersprungen", family)
        _cache.update(mtime=mtime, data=data)
    return _cache["data"]


@receiver(nav_global, dispatch_uid="pretix_customfonts_nav")
def nav(sender, request=None, **kwargs):
    if not request or not request.user.is_authenticated or not request.user.has_active_staff_session(
            request.session.session_key):
        return []
    url = reverse("plugins:se_pretix_customfonts:index")
    return [{
        "label": _("Schriften"),
        "url": url,
        "active": request.path.startswith(url),
        "icon": "font",
    }]

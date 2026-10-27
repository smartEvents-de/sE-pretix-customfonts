# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 the sE-pretix authors
from django.utils.translation import gettext_lazy as _

from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:  # pragma: no cover
    raise RuntimeError("Dieses Plugin braucht pretix (>= 2026.8).")


class PluginApp(PluginConfig):
    default = True
    name = "se_pretix_customfonts"
    verbose_name = _("Eigene Schriften")

    class PretixPluginMeta:
        name = _("Eigene Schriften (global)")
        author = "sE-pretix"
        version = __version__
        category = "CUSTOMIZATION"
        visible = False   # wirkt global (Admin-Menü „Schriften“), kein Schalter pro Event nötig
        description = _(
            "Schriften (TTF, OTF, WOFF, WOFF2 oder ZIP) im Admin-Bereich hochladen. Sie stehen danach in allen "
            "Events für Shop, Tickets, Badges und Rechnungen zur Verfügung. OTF wird für PDFs automatisch "
            "nach TrueType konvertiert."
        )
        compatibility = "pretix>=2026.8.0,<2027.0.0"

    def ready(self):
        from . import hooks, signals  # noqa
        hooks.install()

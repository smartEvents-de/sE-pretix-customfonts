# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 the sE-pretix authors
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from pretix.control.permissions import AdministratorPermissionRequiredMixin

from .hooks import status
from .fonts import STYLES, FontError
from .storage import get_store

STYLE_LABELS = {"regular": "Regular", "bold": "Bold", "italic": "Italic", "bolditalic": "Bold Italic"}


class IndexView(AdministratorPermissionRequiredMixin, TemplateView):
    template_name = "se_pretix_customfonts/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        store = get_store()
        reg = store.load()
        fams = []
        for name, fam in sorted(reg.families.items(), key=lambda kv: kv[0].lower()):
            fams.append({
                "name": name,
                "styles": [{"key": s, "label": STYLE_LABELS[s], "present": s in fam["styles"]} for s in STYLES],
                "missing": [STYLE_LABELS[s] for s in STYLES if s not in fam["styles"]],
                "added": fam.get("added", ""),
            })
        ctx["families"] = fams
        ctx["warnings"] = status()
        ctx["results"] = self.request.session.pop("customfonts_results", None)
        return ctx

    def post(self, request, *args, **kwargs):
        store = get_store()
        action = request.POST.get("action", "upload")
        if action == "delete":
            if store.delete_family(request.POST.get("family", "")):
                messages.success(request, "Schriftfamilie gelöscht. Events, die sie nutzen, fallen auf Open Sans zurück.")
            else:
                messages.error(request, "Familie nicht gefunden.")
            return redirect(reverse("plugins:se_pretix_customfonts:index"))

        uploads = [(f.name, f.read()) for f in request.FILES.getlist("fonts")]
        if not uploads:
            messages.error(request, "Bitte mindestens eine Datei auswählen.")
            return redirect(reverse("plugins:se_pretix_customfonts:index"))
        try:
            results = store.install(uploads, request.POST.get("family_override") or None)
        except FontError as e:
            messages.error(request, str(e))
            return redirect(reverse("plugins:se_pretix_customfonts:index"))
        ok = sum(1 for r in results if r.ok)
        if ok:
            messages.success(request, f"{ok} Schriftschnitt(e) installiert.")
        else:
            messages.error(request, "Es wurde nichts installiert.")
        request.session["customfonts_results"] = [
            {"filename": r.filename, "ok": r.ok, "family": r.family, "style": r.style, "message": r.message}
            for r in results]
        return redirect(reverse("plugins:se_pretix_customfonts:index"))

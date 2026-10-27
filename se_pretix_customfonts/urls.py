# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 the sE-pretix authors
from django.urls import path

from . import views

urlpatterns = [
    path("control/global/customfonts/", views.IndexView.as_view(), name="index"),
]

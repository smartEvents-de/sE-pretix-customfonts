# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 the sE-pretix authors
from django.conf import settings

from .fonts import FontStore

REL_PREFIX = "customfonts"


def get_store() -> FontStore:
    return FontStore(settings.MEDIA_ROOT + "/" + REL_PREFIX)

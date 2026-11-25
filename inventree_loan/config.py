"""Configuration helpers for the loan plugin.

Plugin settings are stored by InvenTree.  These helpers avoid importing the
plugin registry at module import time, which is important because migrations
and Django app loading can happen before the plugin registry is ready.
"""

from __future__ import annotations

from typing import Any

PLUGIN_SLUG = "loan"

#: Name used to filter the native plugin list to this plugin.
ADMIN_SEARCH_TERM = "InvenTreeLoan"


def get_admin_console_url() -> str:
    """Return the native InvenTree page which hosts the loan console.

    InvenTree 1.5.x does not expose a full-page plugin route. The native plugin
    administration page is the standard host for plugin configuration UIs, so
    the navigation item links to that page filtered to this plugin. Opening the
    InvenTreeLoan row shows the standard plugin drawer, including the
    ``Plugin Configuration`` panel rendered by ``admin.js``.
    """
    from django.conf import settings

    base = getattr(settings, "FRONTEND_URL_BASE", "web")
    return f"/{base}/settings/admin/plugin?search={ADMIN_SEARCH_TERM}"


def get_plugin():
    """Return the active loan plugin instance, if available."""
    try:
        from plugin import registry

        return registry.get_plugin(PLUGIN_SLUG)
    except Exception:  # pragma: no cover - registry may not be ready
        return None


def get_setting(key: str, default: Any = None) -> Any:
    """Read a plugin setting without raising during startup/migrations."""
    plugin = get_plugin()
    if plugin is None:
        return default
    try:
        return plugin.get_setting(key, backup_value=default)
    except Exception:  # pragma: no cover - settings table may not exist yet
        return default


def set_setting(key: str, value: Any) -> None:
    """Write a plugin setting."""
    plugin = get_plugin()
    if plugin is not None:
        plugin.set_setting(key, value)


def get_model_setting(key: str):
    """Return a model-valued setting as an instance or numeric primary key."""
    return get_setting(key, None)


def get_loanable_category():
    """Return the configured loanable PartCategory, if any."""
    value = get_setting("LOANABLE_CATEGORY", None)
    if not value:
        return None
    if hasattr(value, "pk"):
        return value
    from part.models import PartCategory

    return PartCategory.objects.filter(pk=value).first()


def get_request_group():
    """Return the configured request Group, if any."""
    value = get_setting("REQUEST_GROUP", None)
    if not value:
        return None
    if hasattr(value, "pk"):
        return value
    from django.contrib.auth.models import Group

    return Group.objects.filter(pk=value).first()

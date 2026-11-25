"""Configuration helpers for the loan plugin.

Plugin settings are stored by InvenTree.  These helpers avoid importing the
plugin registry at module import time, which is important because migrations
and Django app loading can happen before the plugin registry is ready.
"""

from __future__ import annotations

from typing import Any

PLUGIN_SLUG = "loan"

#: Path of the native plugin route declared by ``get_ui_routes``.
MANAGEMENT_ROUTE = "management"


def get_frontend_base() -> str:
    """Return the frontend base path, without leading/trailing slashes."""
    from django.conf import settings

    base = getattr(settings, "FRONTEND_URL_BASE", "web") or "web"
    if isinstance(base, (list, tuple)):
        base = base[0] if base else "web"
    return str(base).strip("/")


def get_native_management_path() -> str:
    """Return the frontend router path of the loan management page.

    This is the path *inside* the InvenTree single-page application, i.e. the
    value passed to React Router (without the ``/web`` frontend base).
    """
    return f"/plugin/{PLUGIN_SLUG}/{MANAGEMENT_ROUTE}"


def get_native_management_url(relative: bool = False) -> str:
    """Return a link to the native InvenTree loan management page.

    Args:
        relative: When True, return the form expected by the InvenTree header
            navigation (``plugin/loan/management``, no leading slash - this is
            the same format used by InvenTree's own sample plugin).  When
            False, return a full browser URL including the frontend base
            (``/web/plugin/loan/management``).
    """
    path = get_native_management_path()
    if relative:
        return path.lstrip("/")
    return f"/{get_frontend_base()}{path}"


def get_native_request_url(pk: int, relative: bool = False) -> str:
    """Return the native request detail page URL."""
    path = f"/plugin/{PLUGIN_SLUG}/requests/{pk}"
    if relative:
        return path.lstrip("/")
    return f"/{get_frontend_base()}{path}"


def get_admin_console_url() -> str:
    """Backwards-compatible alias for the management page URL."""
    return get_native_management_url()


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

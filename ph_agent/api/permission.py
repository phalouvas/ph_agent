"""
Permission helper for the PH Agent app.

Provides the ``has_app_permission`` function referenced in the app's
``hooks.py`` for render-time gating of the app icon on the Frappe
desktop / apps screen.
"""

import frappe


def has_app_permission() -> bool:
    """Return True if the current user may see/access the PH Agent app.

    Access is granted to:
    - Users with the ``System Manager`` role.
    - Users with the ``PH Agent User`` role.
    """
    if "System Manager" in frappe.get_roles():
        return True
    return "PH Agent User" in frappe.get_roles()

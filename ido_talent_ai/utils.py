"""Shared helpers: settings, audit log, roles, Arabic labels, data hashing."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import frappe
from frappe.utils import now_datetime

HR_ROLES = ("HR Manager", "HR User", "System Manager")
DISCLAIMER_AR = "الدرجة ترتيب مقابل معايير معتمدة، وليست احتمال نجاح في الوظيفة."
DISCLAIMER_EN = "The score is a ranking against approved criteria, not a probability of success in the job."
STATUS_FROM_ENGINE = {
	"queued": "Processing",
	"processing": "Processing",
	"completed": "Completed",
	"needs_review": "Needs Review",
	"failed": "Failed",
}


def get_settings():
	return frappe.get_cached_doc("AI Recruitment Settings")


def is_hr(user: str | None = None) -> bool:
	roles = set(frappe.get_roles(user or frappe.session.user))
	return bool(roles & set(HR_ROLES)) or (user or frappe.session.user) == "Administrator"


def require_hr() -> None:
	if not is_hr():
		frappe.throw(frappe._("Only HR Manager or HR User can do this."), frappe.PermissionError)


def require_settings_access() -> None:
	"""The engine settings (provider, model, callback URL, prompt) are read by the same users who may
	open «AI Recruitment Settings»: HR Manager and System Manager, never HR User (final QA, Q5)."""
	if not frappe.has_permission("AI Recruitment Settings", "read"):
		frappe.throw(frappe._("Only HR Manager or System Manager can read the AI settings."), frappe.PermissionError)


def audit(
	action: str,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	job_opening: str | None = None,
	reason: str | None = None,
	profile_version: int | None = None,
	details: dict | None = None,
	actor: str | None = None,
) -> None:
	"""Append-only audit entry. Never stores names or IDs in `details` (references only)."""
	frappe.get_doc(
		{
			"doctype": "AI Recruitment Audit Log",
			"timestamp": now_datetime(),
			"action": action,
			"actor": actor or (frappe.session.user if frappe.session else "system"),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"job_opening": job_opening,
			"reason": reason,
			"profile_version": profile_version,
			"details": json.dumps(details or {}, ensure_ascii=False, default=str),
		}
	).insert(ignore_permissions=True)


def id_token(national_id: str | None) -> str | None:
	"""HMAC-SHA256 of the national ID with a secret that never leaves the site (duplicate detection)."""
	if not national_id or not str(national_id).strip():
		return None
	secret = get_settings().get_password("id_token_secret", raise_exception=False) or ""
	if not secret:
		return None
	value = "".join(str(national_id).split())
	return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def arabic(text: str | None) -> str:
	"""Arabic display label of a value (Country names etc.) from the framework translations."""
	if not text:
		return ""
	try:
		from frappe.translate import get_all_translations

		return get_all_translations("ar").get(text) or text
	except Exception:
		return text


def to_json(value: Any) -> str:
	return json.dumps(value, ensure_ascii=False, default=str)


def from_json(value: str | None, default: Any = None) -> Any:
	if not value:
		return default
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


HOME_ROUTE = "/desk/ai-recruitment"


def on_session_creation(login_manager=None) -> None:
	"""HR users land on «التوظيف الذكي» after login, in Arabic unless they chose another language.
	Uses Frappe's own per-request home page flag; nothing is stored on roles or settings."""
	try:
		user = frappe.session.user
		if user in ("Administrator", "Guest") or not (set(frappe.get_roles(user)) & {"HR Manager", "HR User"}):
			return
		frappe.local.flags.home_page = HOME_ROUTE
		if not frappe.db.get_value("User", user, "language"):
			frappe.db.set_value("User", user, "language", "ar", update_modified=False)
			frappe.local.lang = "ar"
	except Exception:
		pass  # a landing preference must never block a login

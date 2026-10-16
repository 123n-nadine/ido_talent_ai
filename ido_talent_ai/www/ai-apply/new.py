"""Public application form for openings with an approved AI Job Profile: /ai-apply/new?job_title=<opening>.

The HRMS job page links here because `on_opening_validate` sets the opening's job_application_route
to "ai-apply". Questions come from the last approved profile version; height and weight are asked
only when the opening has a rule on them. Posting goes to `ido_talent_ai.api.apply`."""

import frappe
from frappe import _

from ido_talent_ai.api import _form_context
from ido_talent_ai.utils import arabic, get_settings

no_cache = 1
FIRST_COUNTRIES = ("Saudi Arabia", "Egypt", "Yemen", "Sudan", "Jordan", "Pakistan", "India", "Bangladesh", "Philippines")


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True
	job = frappe.form_dict.get("job_title")
	context.title = "نموذج التقديم"
	try:
		op, snap = _form_context(job)
	except Exception as e:
		context.error = str(e) if job else _("No job selected.")
		return context
	facts = {r["fact"] for r in snap.get("rules", [])}
	countries = frappe.get_all("Country", pluck="name", order_by="name asc")
	ordered = [c for c in FIRST_COUNTRIES if c in countries] + [c for c in countries if c not in FIRST_COUNTRIES]
	s = get_settings()
	context.update(
		{
			"opening": op,
			"company": op.company,
			"questions": snap.get("questions", []),
			"requirements": snap.get("requirements", []),
			"needs_height": "height_cm" in facts,
			"needs_weight": "weight_kg" in facts,
			"countries_json": _js([{"value": c, "label": arabic(c)} for c in ordered]),
			"requirements_json": _js(snap.get("requirements", [])),
			"meta_json": _js({"text": s.consent_text, "version": s.consent_version or "v1", "title": op.job_title, "company": op.company}),
			"form_config": _js(
				{
					"job_title": op.name,
					"questions": snap.get("questions", []),
					"needs_height": "height_cm" in facts,
					"needs_weight": "weight_kg" in facts,
				}
			),
		}
	)
	return context


def _js(value) -> str:
	"""JSON safe to embed in a <script type="application/json"> block."""
	return frappe.as_json(value).replace("</", "<\\/")

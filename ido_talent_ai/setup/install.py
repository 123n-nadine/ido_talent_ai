"""Custom fields, permissions and defaults. Everything here is undone by before_uninstall.

The AI section and the identity fields on Job Applicant use permission level 1, which only HR
Manager, HR User and System Manager can read. Other roles that may read Job Applicant (for
example Support Read Only) never see them."""

from __future__ import annotations

import secrets

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

AI_LEVEL = 1
AI_ROLES = ("HR Manager", "HR User", "System Manager")


def _f(fieldname, fieldtype, label, **kw):
	d = {"fieldname": fieldname, "fieldtype": fieldtype, "label": label, "module": "Talent AI"}
	d.update(kw)
	return d


def custom_fields() -> dict:
	ro = {"read_only": 1, "no_copy": 1, "permlevel": AI_LEVEL}
	hidden = {"hidden": 1, "read_only": 1, "no_copy": 1, "permlevel": AI_LEVEL}
	return {
		"Job Opening": [
			_f("ai_section", "Section Break", "Talent AI", insert_after="description", collapsible=0),
			_f("ai_enabled", "Check", "AI screening enabled", insert_after="ai_section"),
			_f("ai_profile", "Link", "AI Job Profile", options="AI Job Profile", insert_after="ai_enabled", depends_on="ai_enabled"),
			_f("ai_column", "Column Break", "", insert_after="ai_profile"),
			_f("ai_profile_approved", "Check", "AI profile approved", read_only=1, insert_after="ai_column", depends_on="ai_enabled"),
			_f("ai_links", "HTML", "AI links", insert_after="ai_profile_approved", depends_on="ai_enabled"),
		],
		"Job Applicant": [
			# facts the hard rules need, collected by the AI application form (identity at permlevel 1)
			_f("ai_facts_section", "Section Break", "Eligibility facts", insert_after="country", collapsible=1),
			_f("nationality", "Link", "Nationality", options="Country", insert_after="ai_facts_section"),
			_f("date_of_birth", "Date", "Date of Birth", insert_after="nationality"),
			_f("id_type", "Select", "ID type", options="\nهوية وطنية\nإقامة", insert_after="date_of_birth", permlevel=AI_LEVEL),
			_f("national_id", "Data", "National ID / Iqama", insert_after="id_type", permlevel=AI_LEVEL,
			   description="Never sent to the AI engine; only an HMAC token is sent for duplicate detection."),
			_f("ai_facts_column", "Column Break", "", insert_after="national_id"),
			_f("height_cm", "Int", "Height (cm)", insert_after="ai_facts_column"),
			_f("weight_kg", "Int", "Weight (kg)", insert_after="height_cm"),
			_f("ai_consent", "Check", "Consent to AI processing", insert_after="weight_kg", read_only=1),
			_f("ai_consent_version", "Data", "Consent version", insert_after="ai_consent", read_only=1),
			_f("ai_consent_on", "Datetime", "Consent given on", insert_after="ai_consent_version", read_only=1),
			_f("ai_consent_withdrawn_on", "Datetime", "Consent withdrawn on", insert_after="ai_consent_on", read_only=1,
			   depends_on="ai_consent_withdrawn_on"),
			_f("ai_answers_section", "Section Break", "Screening answers", insert_after="ai_consent_withdrawn_on"),
			_f("ai_answers", "Table", "Screening answers", options="AI Applicant Answer", insert_after="ai_answers_section"),
			# AI section (HR only)
			_f("ai_section", "Section Break", "AI assessment", insert_after="ai_answers", permlevel=AI_LEVEL),
			_f("ai_html", "HTML", "AI assessment", insert_after="ai_section", permlevel=AI_LEVEL),
			_f("ai_fields_section", "Section Break", "AI fields", insert_after="ai_html", collapsible=1, permlevel=AI_LEVEL),
			_f("ai_status", "Select", "AI status", options="\nProcessing\nCompleted\nNeeds Review\nFailed",
			   insert_after="ai_fields_section", in_list_view=1, in_standard_filter=1, **ro),
			_f("ai_score", "Float", "AI score", precision="1", insert_after="ai_status", in_list_view=1, **ro),
			_f("ai_band", "Select", "AI band", options="\nhigh\nmedium\nlow", insert_after="ai_score", in_standard_filter=1, **ro),
			_f("ai_eligibility", "Select", "AI eligibility", options="\neligible\nnot_eligible\nneeds_review",
			   insert_after="ai_band", in_standard_filter=1, **ro),
			_f("ai_coverage", "Percent", "AI coverage", insert_after="ai_eligibility", **ro),
			_f("ai_rank", "Int", "AI rank", insert_after="ai_coverage", **ro),
			_f("ai_fields_column", "Column Break", "", insert_after="ai_rank", permlevel=AI_LEVEL),
			_f("ai_assessment", "Link", "AI assessment", options="AI Candidate Assessment", insert_after="ai_fields_column", **ro),
			_f("ai_evaluated_on", "Datetime", "AI evaluated on", insert_after="ai_assessment", **ro),
			_f("ai_stale", "Check", "AI result is stale", insert_after="ai_evaluated_on", in_standard_filter=1, **ro),
			_f("ai_duplicate_of", "Link", "Duplicate of", options="Job Applicant", insert_after="ai_stale", **ro),
			_f("ai_cv_note", "Small Text", "CV note", insert_after="ai_duplicate_of", **ro),
			_f("ai_flags", "Small Text", "AI flags", insert_after="ai_cv_note", **hidden),
			_f("ai_candidate_ref", "Data", "AI candidate reference", insert_after="ai_flags", **hidden),
			_f("ai_data_hash", "Data", "AI data hash", insert_after="ai_candidate_ref", **hidden),
			_f("ai_cv_sha", "Data", "AI CV hash", insert_after="ai_data_hash", **hidden),
			_f("ai_decision_section", "Section Break", "HR decision", insert_after="ai_cv_sha", permlevel=AI_LEVEL),
			_f("ai_decision_reason", "Small Text", "Decision reason", insert_after="ai_decision_section", **ro),
			_f("ai_decided_by", "Link", "Decided by", options="User", insert_after="ai_decision_reason", **ro),
			_f("ai_decided_on", "Datetime", "Decided on", insert_after="ai_decided_by", **ro),
		],
	}


def _permissions() -> None:
	"""Give the HR roles read (and write for the decision fields) at the AI permission level."""
	from frappe.permissions import add_permission, update_permission_property

	for role in AI_ROLES:
		add_permission("Job Applicant", role, AI_LEVEL)
		update_permission_property("Job Applicant", role, AI_LEVEL, "read", 1)
		update_permission_property("Job Applicant", role, AI_LEVEL, "write", 1)


def _defaults() -> None:
	s = frappe.get_single("AI Recruitment Settings")
	changed = False
	if not s.get_password("callback_secret", raise_exception=False):
		s.callback_secret = secrets.token_urlsafe(32)
		changed = True
	if not s.get_password("id_token_secret", raise_exception=False):
		s.id_token_secret = secrets.token_urlsafe(32)
		changed = True
	if changed:
		s.flags.ignore_mandatory = True
		s.flags.talent_ai_local_only = True
		s.save(ignore_permissions=True)


def after_install() -> None:
	create_custom_fields(custom_fields(), update=True)
	_permissions()
	_defaults()
	frappe.db.commit()


def after_migrate() -> None:
	create_custom_fields(custom_fields(), update=True)


def before_uninstall() -> None:
	"""Leave the platform as it was: remove our custom fields and permission rows."""
	for dt, fields in custom_fields().items():
		for f in fields:
			name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": f["fieldname"]})
			if name:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	for role in AI_ROLES:
		frappe.db.delete("Custom DocPerm", {"parent": "Job Applicant", "role": role, "permlevel": AI_LEVEL})
	frappe.clear_cache(doctype="Job Applicant")
	frappe.clear_cache(doctype="Job Opening")

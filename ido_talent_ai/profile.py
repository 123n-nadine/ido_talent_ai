"""AI Job Profile <-> engine job. The engine stores every approved version; Frappe keeps the
editable draft, the version history and the snapshot the public form renders."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from ido_talent_ai import engine
from ido_talent_ai.utils import arabic, audit, require_hr, to_json

LEVELS = (0, 25, 50, 75, 100)
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
NUMERIC_FACTS = {"height_cm", "weight_kg", "age"}
FACT_LABELS = {"nationality": "الجنسية", "height_cm": "الطول", "weight_kg": "الوزن", "age": "العمر", "gender": "الجنس"}
UNITS = {"height_cm": "سم", "weight_kg": "كجم", "age": "سنة"}


def lines(text: str | None) -> list[str]:
	return [x.strip() for x in (text or "").replace("\r", "").split("\n") if x.strip()]


def parse_hint(hint: str | None, qtype: str) -> dict:
	h = (hint or "").strip()
	if not h:
		return {}
	if qtype == "number":
		m = re.fullmatch(r"(>=|>)\s*(-?\d+(?:\.\d+)?)", h)
		if not m:
			return {}
		return {"gte" if m.group(1) == ">=" else "gt": float(m.group(2))}
	return {"answers": [x.strip() for x in h.split("|") if x.strip()]}


def hint_text(r: dict) -> str:
	if r.get("gte") is not None:
		return f">= {r['gte']:g}"
	if r.get("gt") is not None:
		return f"> {r['gt']:g}"
	if r.get("answers"):
		return " | ".join(r["answers"])
	return ""


def rule_value(rule) -> Any:
	raw = (rule.value or "").strip()
	parts = [x.strip() for x in raw.replace("،", ",").split(",") if x.strip()]
	if rule.fact == "nationality":
		parts = [arabic(x) for x in parts]  # Country names are sent with their Arabic label, like the facts
	if rule.operator in ("in", "not_in"):
		return parts
	if rule.operator == "between":
		return [float(x) for x in parts[:2]]
	if rule.fact in NUMERIC_FACTS:
		return float(parts[0]) if parts else 0
	return parts[0] if parts else ""


def requirement_text(rule) -> str:
	label = FACT_LABELS.get(rule.fact, rule.fact)
	unit = UNITS.get(rule.fact, "")
	raw = (rule.value or "").strip()
	parts = [x.strip() for x in raw.replace("،", ",").split(",") if x.strip()]
	shown = "، ".join(arabic(x) for x in parts) if rule.fact == "nationality" else "، ".join(parts)
	op = rule.operator
	if op == "in":
		return f"{label}: {shown}"
	if op == "not_in":
		return f"{label}: ليس {shown}"
	if op == ">=":
		return f"{label} {shown} {unit} أو أكثر".replace("  ", " ")
	if op == "<=":
		return f"{label} {shown} {unit} أو أقل".replace("  ", " ")
	if op == ">":
		return f"{label} أكثر من {shown} {unit}".strip()
	if op == "<":
		return f"{label} أقل من {shown} {unit}".strip()
	if op == "between" and len(parts) >= 2:
		return f"{label} من {parts[0]} إلى {parts[1]} {unit}".strip()
	return f"{label} {op} {shown}"


def engine_payload(doc) -> dict:
	qtypes = {q.question_key: q.question_type for q in doc.questions}
	criteria = []
	for c in doc.criteria:
		qtype = qtypes.get(c.question or "", "text")
		criteria.append(
			{
				"key": c.criterion_key,
				"text": c.criterion,
				"weight": flt(c.weight),
				"mandatory": bool(c.mandatory),
				"question": c.question or None,
				"rubric": [
					{"level": L, "text": (c.get(f"rubric_{L}") or "—").strip() or "—", **parse_hint(c.get(f"hint_{L}"), qtype)}
					for L in LEVELS
				],
			}
		)
	return {
		"title": doc.title,
		"description": doc.description or "",
		"criteria": criteria,
		"rules": [{"fact": r.fact, "operator": r.operator, "value": rule_value(r), "if_missing": "review"} for r in doc.rules],
		"questions": [
			{
				"key": q.question_key,
				"label": q.label,
				"label_en": q.label_en or None,
				"type": q.question_type,
				"options": lines(q.options) or None,
				"required": bool(q.required),
				"hint": q.hint or None,
			}
			for q in doc.questions
		],
	}


def content_hash(doc) -> str:
	return hashlib.sha256(json.dumps(engine_payload(doc), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_profile(doc, for_approval: bool = False) -> None:
	doc.weights_total = round(sum(flt(c.weight) for c in doc.criteria), 1)
	for r in doc.rules:
		r.if_missing = "review"
		r.requirement_text = requirement_text(r)
	if not for_approval:
		return
	errors = []
	if not doc.criteria:
		errors.append(_("Add at least one criterion."))
	if abs(flt(doc.weights_total) - 100) > 0.001:
		errors.append(_("The weights must total 100% (now {0}%).").format(doc.weights_total))
	keys = [c.criterion_key for c in doc.criteria]
	if len(keys) != len(set(keys)):
		errors.append(_("Criterion keys must be unique."))
	for k in keys:
		if not KEY_RE.match(k or ""):
			errors.append(_("Criterion key '{0}' must be lowercase letters, digits or _.").format(k))
	qkeys = {q.question_key for q in doc.questions}
	for q in doc.questions:
		if not KEY_RE.match(q.question_key or ""):
			errors.append(_("Question key '{0}' must be lowercase letters, digits or _.").format(q.question_key))
		if q.question_type in ("select", "multiselect") and not lines(q.options):
			errors.append(_("Question '{0}' needs options.").format(q.label))
	for c in doc.criteria:
		if c.question and c.question not in qkeys:
			errors.append(_("Criterion '{0}' points to an unknown question '{1}'.").format(c.criterion, c.question))
	for r in doc.rules:
		try:
			rule_value(r)
		except ValueError:
			errors.append(_("Rule value '{0}' is not valid for {1}.").format(r.value, r.fact))
	if errors:
		frappe.throw("<br>".join(errors), title=_("Cannot approve"))


@frappe.whitelist()
def approve(name: str) -> dict:
	require_hr()
	doc = frappe.get_doc("AI Job Profile", name)
	doc.check_permission("write")
	validate_profile(doc, for_approval=True)
	payload = engine_payload(doc)
	payload["approved_by"] = frappe.session.user
	old_version = cint(doc.version)
	new_version = old_version + 1
	stale = 0
	if doc.job_opening:
		res = engine.put(f"/v1/jobs/{doc.job_opening}", json=payload)
		new_version = cint(res["version"]["version"])
		created = bool(res.get("new_version"))
	else:
		created = True  # a template lives only in Frappe
	if not created and old_version == new_version and doc.status == "Approved":
		return {"version": new_version, "new_version": False, "stale": 0}
	doc.version = new_version
	doc.status = "Approved"
	doc.is_ai_draft = 0
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.append(
		"versions",
		{
			"version": new_version,
			"approved_by": frappe.session.user,
			"approved_on": doc.approved_on,
			"weights": " / ".join(f"{flt(c.weight):g}" for c in doc.criteria),
			"content_hash": content_hash(doc),
			# the public form renders this snapshot: the engine payload plus the Arabic rule sentences
			"snapshot": to_json({**payload, "requirements": [r.requirement_text for r in doc.rules]}),
		},
	)
	doc.flags.talent_ai_approving = True
	doc.save()
	if doc.job_opening:
		op = frappe.get_doc("Job Opening", doc.job_opening)
		op.ai_profile = doc.name
		op.flags.ignore_permissions = True
		op.save()
		if old_version:
			stale = mark_stale(doc.job_opening, new_version)
	audit(
		"profile.approved", "AI Job Profile", doc.name, doc.job_opening, profile_version=new_version,
		details={"weights": [flt(c.weight) for c in doc.criteria], "stale_assessments": stale},
	)
	return {"version": new_version, "new_version": True, "stale": stale}


def mark_stale(opening: str, version: int) -> int:
	names = frappe.get_all(
		"AI Candidate Assessment",
		filters={"job_opening": opening, "profile_version": ["<", version], "status": ["in", ["Completed", "Needs Review"]]},
		fields=["name", "job_applicant"],
	)
	for a in names:
		frappe.db.set_value("AI Candidate Assessment", a.name, {"stale": 1, "stale_reason": "stale"}, update_modified=False)
		frappe.db.set_value("Job Applicant", a.job_applicant, "ai_stale", 1, update_modified=False)
	frappe.publish_realtime("talent_ai_batch", {"job_opening": opening, "stale": len(names)}, after_commit=True)
	return len(names)


@frappe.whitelist()
def impact_preview(name: str, draft: str | None = None) -> dict:
	"""Who moves if this draft is approved: new score, band and rank per current applicant."""
	require_hr()
	doc = frappe.get_doc("AI Job Profile", name)
	if draft:
		d = json.loads(draft)
		doc.set("criteria", [])
		for c in d.get("criteria", []):
			doc.append("criteria", c)
	if not doc.job_opening:
		return {"rows": [], "note": _("A template has no applicants.")}
	payload = engine_payload(doc)
	res = engine.post(f"/v1/jobs/{doc.job_opening}/impact", json={"criteria": payload["criteria"]})
	names = dict(
		frappe.get_all(
			"Job Applicant", filters={"job_title": doc.job_opening}, fields=["ai_candidate_ref", "applicant_name"], as_list=True
		)
	)
	for r in res.get("rows", []):
		r["applicant_name"] = names.get(r["candidate_ref"], r["candidate_ref"])
		r["applicant"] = frappe.db.get_value("Job Applicant", {"ai_candidate_ref": r["candidate_ref"]}, "name")
	res["weights_total"] = round(sum(flt(c["weight"]) for c in payload["criteria"]), 1)
	return res


@frappe.whitelist()
def draft_criteria(name: str) -> dict:
	"""«اقتراح معايير AI»: fill the profile with a draft. Nothing is used before approval."""
	require_hr()
	doc = frappe.get_doc("AI Job Profile", name)
	doc.check_permission("write")
	title = doc.title or (frappe.db.get_value("Job Opening", doc.job_opening, "job_title") if doc.job_opening else "")
	desc = doc.description or (frappe.db.get_value("Job Opening", doc.job_opening, "description") if doc.job_opening else "")
	res = engine.post("/v1/jobs/draft-criteria", json={"title": title, "description": frappe.utils.strip_html(desc or "")}, timeout=300)
	doc.description = doc.description or res.get("description")
	doc.set("criteria", [])
	for c in res.get("criteria", []):
		row = {"criterion_key": c["key"], "criterion": c["text"], "weight": c["weight"], "mandatory": c.get("mandatory"), "question": c.get("question")}
		for r in c.get("rubric", []):
			row[f"rubric_{r['level']}"] = r.get("text")
			row[f"hint_{r['level']}"] = hint_text(r)
		doc.append("criteria", row)
	if res.get("questions"):
		doc.set("questions", [])
		for q in res["questions"]:
			doc.append(
				"questions",
				{"question_key": q["key"], "label": q["label"], "label_en": q.get("label_en"), "question_type": q.get("type", "text"),
				 "options": "\n".join(q.get("options") or []), "required": 1 if q.get("required", True) else 0, "hint": q.get("hint")},
			)
	doc.is_ai_draft = 1
	doc.status = "Draft"
	doc.flags.talent_ai_keep_status = True
	doc.save()
	audit("profile.ai_draft", "AI Job Profile", doc.name, doc.job_opening, details={"criteria": len(doc.criteria)})
	return {"criteria": len(doc.criteria), "questions": len(doc.questions)}


@frappe.whitelist()
def templates_for(name: str) -> list[dict]:
	doc = frappe.get_doc("AI Job Profile", name)
	filters = {"is_template": 1, "name": ["!=", name], "status": "Approved"}
	if doc.designation:
		filters["designation"] = doc.designation
	return frappe.get_all("AI Job Profile", filters=filters, fields=["name", "title", "designation", "version"])


@frappe.whitelist()
def copy_from_template(name: str, template: str) -> dict:
	"""«نسخ من قالب المسمى الوظيفي»: copy criteria, rules and questions as a draft."""
	require_hr()
	doc = frappe.get_doc("AI Job Profile", name)
	doc.check_permission("write")
	src = frappe.get_doc("AI Job Profile", template)
	for table in ("criteria", "rules", "questions"):
		doc.set(table, [])
		for row in src.get(table):
			d = row.as_dict()
			for k in ("name", "parent", "parentfield", "parenttype", "idx", "creation", "modified", "owner", "modified_by", "docstatus"):
				d.pop(k, None)
			doc.append(table, d)
	doc.description = doc.description or src.description
	doc.designation = doc.designation or src.designation
	doc.copied_from = src.name
	doc.status = "Draft"
	doc.flags.talent_ai_keep_status = True
	doc.save()
	audit("profile.copied_from_template", "AI Job Profile", doc.name, doc.job_opening, details={"template": src.name})
	return {"criteria": len(doc.criteria)}

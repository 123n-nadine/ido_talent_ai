"""The automatic path: Job Applicant saved -> AI Recruitment Job -> engine -> result -> assessment.

Rules enforced here:
- an application is never blocked by the AI (every hook swallows its own errors);
- the AI never writes Job Applicant.status (only `api.decide` does, for HR users);
- personal data stays in Frappe: the engine gets an opaque candidate reference, allowed facts,
  answers, the CV file and an HMAC of the national ID."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from typing import Any

import frappe
from frappe.utils import add_to_date, cint, date_diff, flt, getdate, now_datetime, nowdate

from ido_talent_ai import engine
from ido_talent_ai.countries import country_ar
from ido_talent_ai.utils import (
	STATUS_FROM_ENGINE,
	audit,
	from_json,
	get_settings,
	id_token,
	to_json,
)

TRANSIENT_DB_ERRORS = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)
FACT_FIELDS = ("nationality", "date_of_birth", "height_cm", "weight_kg", "national_id", "id_type")
APPLY_ROUTE = "ai-apply"


# ----------------------------------------------------------------------------- helpers
def opening_ai(opening: str | None) -> dict | None:
	if not opening:
		return None
	return frappe.db.get_value(
		"Job Opening", opening, ["name", "ai_enabled", "ai_profile", "ai_profile_approved", "job_title"], as_dict=True
	)


def ai_ready(opening: str | None) -> bool:
	s = get_settings()
	op = opening_ai(opening)
	return bool(s.enabled and op and op.ai_enabled and op.ai_profile_approved and op.ai_profile)


def approved_snapshot(profile: str) -> dict | None:
	"""The last approved version of a profile (what the engine and the public form use)."""
	rows = frappe.get_all(
		"AI Job Profile Version", filters={"parent": profile, "parenttype": "AI Job Profile"},
		fields=["version", "snapshot"], order_by="version desc", limit=1,
	)
	return from_json(rows[0].snapshot) if rows else None


def ensure_candidate_ref(applicant) -> str:
	"""Opaque reference sent to the engine instead of the applicant's name (which is the e-mail).
	Deterministic per application (keyed HMAC of name + creation time), so a retried job can never
	create a second engine candidate for the same application."""
	if not applicant.get("ai_candidate_ref"):
		secret = get_settings().get_password("id_token_secret", raise_exception=False) or frappe.local.site
		base = f"{applicant.name}|{applicant.creation}"
		ref = "JA-" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()[:20].upper()
		frappe.db.set_value("Job Applicant", applicant.name, "ai_candidate_ref", ref, update_modified=False)
		applicant.ai_candidate_ref = ref
	return applicant.ai_candidate_ref


def age_years(dob) -> int | None:
	if not dob:
		return None
	d = getdate(dob)
	t = getdate(nowdate())
	return t.year - d.year - ((t.month, t.day) < (d.month, d.day))


def question_types(opening: str) -> dict[str, str]:
	op = opening_ai(opening)
	snap = approved_snapshot(op.ai_profile) if op and op.ai_profile else None
	return {q["key"]: q.get("type", "text") for q in (snap or {}).get("questions", [])}


def parse_answer(raw: str | None, qtype: str) -> Any:
	if raw is None or str(raw).strip() == "":
		return ""  # blank = not answered (never 0)
	text = str(raw).strip()
	if qtype == "number":
		try:
			n = float(text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).replace("٫", "."))
			return int(n) if n.is_integer() else n
		except ValueError:
			return text
	if qtype == "multiselect":
		return [x.strip() for x in text.replace("،", "\n").replace(",", "\n").split("\n") if x.strip()]
	return text


def candidate_payload(applicant) -> dict:
	s = get_settings()
	allowed = {x.strip() for x in (s.allowed_facts or "").splitlines() if x.strip()}
	facts: dict[str, Any] = {}
	if "nationality" in allowed:
		facts["nationality"] = country_ar(applicant.get("nationality")) or None
	if "age" in allowed:
		facts["age"] = age_years(applicant.get("date_of_birth"))
	if "height_cm" in allowed:
		facts["height_cm"] = cint(applicant.get("height_cm")) or None  # 0 = not declared
	if "weight_kg" in allowed:
		facts["weight_kg"] = cint(applicant.get("weight_kg")) or None
	types = question_types(applicant.job_title)
	answers = {
		row.question_key: parse_answer(row.answer, types.get(row.question_key, "text"))
		for row in applicant.get("ai_answers") or []
	}
	return {
		"id_token": id_token(applicant.get("national_id")),
		"facts": facts,
		"answers": answers,
		"consent": bool(applicant.get("ai_consent")),
		"retention_days": cint(s.retention_days) or None,
		"applied_at": utc_iso(applicant.get("creation")),
	}


def utc_iso(value) -> str | None:
	"""Frappe stores datetimes in the system time zone; the engine stores UTC (decision 15)."""
	if not value:
		return None
	from zoneinfo import ZoneInfo

	from frappe.utils import get_datetime, get_system_timezone

	dt = get_datetime(value)
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return dt.astimezone(ZoneInfo("UTC")).isoformat()


def data_signature(applicant) -> str:
	base = {f: str(applicant.get(f) or "") for f in FACT_FIELDS}
	base["answers"] = {r.question_key: (r.answer or "") for r in applicant.get("ai_answers") or []}
	base["cv"] = applicant.get("resume_attachment") or ""
	return hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _file_bytes(file_url: str) -> tuple[str, bytes] | None:
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return None
	f = frappe.get_doc("File", name)
	# File.get_content() decodes text-like files (RTF) to str; the engine needs the raw bytes
	with open(f.get_full_path(), "rb") as fh:
		return f.file_name or "cv", fh.read()


def push_cv(applicant, ref: str) -> None:
	"""Send the CV (once per file content). Extraction, OCR and redaction run in the engine now."""
	url = applicant.get("resume_attachment")
	if not url:
		if applicant.get("ai_cv_sha"):
			try:
				engine.delete(f"/v1/candidates/{ref}/cv")
			except engine.EngineError:
				pass
			frappe.db.set_value("Job Applicant", applicant.name, "ai_cv_sha", "", update_modified=False)
		return
	# a CV that cannot be read or is refused never fails the screening (decision 14): the
	# applicant is assessed from the answers and HR sees why in «ملاحظة عن السيرة الذاتية»
	try:
		got = _file_bytes(url)
	except Exception as e:
		safe_log("Talent AI: CV file could not be read")
		_cv_note(applicant, f"تعذّرت قراءة ملف السيرة من النظام ({type(e).__name__}) — التقييم من الإجابات فقط")
		return
	if not got:
		return
	fname, content = got
	sha = hashlib.sha256(content).hexdigest()
	if sha == applicant.get("ai_cv_sha"):
		return
	try:
		engine.put(
			f"/v1/candidates/{ref}/cv",
			files={"file": (fname, content)},
			data={"name_hint": applicant.applicant_name or ""},
			timeout=600,
		)
	except engine.EngineUnavailable:
		raise  # the engine is down: the whole job is retried
	except engine.EngineError as e:
		_cv_note(applicant, f"المحرك رفض ملف السيرة ({e.status or ''}) — التقييم من الإجابات فقط")
		return
	frappe.db.set_value("Job Applicant", applicant.name, "ai_cv_sha", sha, update_modified=False)


def _cv_note(applicant, note: str) -> None:
	frappe.db.set_value("Job Applicant", applicant.name, "ai_cv_note", note[:240], update_modified=False)


def publish(applicant: str, opening: str | None, status: str | None) -> None:
	data = {"applicant": applicant, "ai_status": status, "job_opening": opening}
	frappe.publish_realtime("talent_ai_update", data, doctype="Job Applicant", docname=applicant, after_commit=True)
	frappe.publish_realtime("talent_ai_batch", data, after_commit=True)


# ----------------------------------------------------------------------------- queueing
def queue_screening(applicant_name: str, job_type: str = "Screening", force: bool = False) -> str:
	if not frappe.db.get_value("Job Applicant", applicant_name, "ai_consent"):
		frappe.throw(frappe._("The applicant withdrew consent to AI processing."))
	s = get_settings()
	opening = frappe.db.get_value("Job Applicant", applicant_name, "job_title")
	job = frappe.get_doc(
		{
			"doctype": "AI Recruitment Job",
			"job_type": job_type,
			"status": "Queued",
			"reference_doctype": "Job Applicant",
			"reference_name": applicant_name,
			"job_opening": opening,
			"attempts": 0,
			"max_attempts": cint(s.max_retries) or 3,
			"queued_on": now_datetime(),
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Job Applicant", applicant_name, "ai_status", "Processing", update_modified=False)
	assessment = frappe.db.get_value("Job Applicant", applicant_name, "ai_assessment")
	if assessment:
		frappe.db.set_value("AI Candidate Assessment", assessment, "status", "Processing", update_modified=False)
	frappe.enqueue(
		"ido_talent_ai.screening.run_job",
		queue="long",
		timeout=1800,
		enqueue_after_commit=True,
		ai_job=job.name,  # not `job_name`: frappe.enqueue reserves that keyword
		force=force,
	)
	publish(applicant_name, opening, "Processing")
	audit("ai_job.queued", "Job Applicant", applicant_name, opening, details={"job": job.name, "type": job_type})
	return job.name


def db_retry(fn, *args, attempts: int = 4, **kwargs):
	"""Run `fn` and commit; on a database conflict (MariaDB snapshot isolation, deadlock) roll back
	and try again. Used by background jobs and HR actions that write AI records concurrently."""
	for i in range(attempts):
		try:
			out = fn(*args, **kwargs)
			frappe.db.commit()
			return out
		except TRANSIENT_DB_ERRORS:
			frappe.db.rollback()
			if i == attempts - 1:
				raise
			time.sleep(0.2 * (i + 1) + random.random() * 0.4)


def on_applicant_insert(doc, method=None):
	"""Always succeeds: the AI must never block an application (acceptance criterion 6).
	Only the applicant's own row is written here; the AI Recruitment Job is created by a background
	job, so a conflict on shared tables can never roll back the application itself."""
	try:
		s = get_settings()
		ready = s.enabled and s.auto_screen_on_apply and ai_ready(doc.job_title) and doc.get("ai_consent")
		values = {"ai_data_hash": data_signature(doc)}
		if ready:
			values["ai_status"] = "Processing"
		frappe.db.set_value("Job Applicant", doc.name, values, update_modified=False)
		if ready:
			# after the commit and guarded: a queue that is down must not turn a saved application into
			# an error page (the 2-minute safety net `queue_missing` picks it up later)
			frappe.db.after_commit.add(lambda name=doc.name: safe_enqueue("ido_talent_ai.screening.start_screening", queue="short", applicant=name))
	except TRANSIENT_DB_ERRORS:
		raise  # the caller retries the whole application; never swallow a rolled-back transaction
	except Exception:
		safe_log("Talent AI: could not queue the screening")


def safe_enqueue(method: str, **kwargs) -> None:
	try:
		frappe.enqueue(method, **kwargs)
	except Exception:
		safe_log(f"Talent AI: could not enqueue {method}")


def safe_log(title: str) -> None:
	try:
		frappe.log_error(title=title)
	except Exception:
		pass


def start_screening(applicant: str) -> None:
	"""Background: create the AI Recruitment Job of a new application (retried on conflicts)."""
	if not frappe.db.get_value("Job Applicant", applicant, "ai_consent"):
		return
	if frappe.db.exists("AI Recruitment Job", {"reference_name": applicant, "status": ["in", ["Queued", "Running"]]}):
		return
	db_retry(queue_screening, applicant, "Screening")


def queue_missing() -> None:
	"""Safety net (every 2 minutes): applications marked Processing without an active AI job, e.g.
	when the queue was unavailable at submission time."""
	rows = frappe.db.sql(
		"""select ja.name from `tabJob Applicant` ja
		where ja.ai_status='Processing' and ja.creation < (now() - interval 2 minute)
		and not exists (select 1 from `tabAI Recruitment Job` j where j.reference_name=ja.name
			and j.status in ('Queued','Running'))""",
		pluck=True,
	)
	for name in rows:
		start_screening(name)


# ----------------------------------------------------------------------------- the job
def _assessment_for(applicant) -> Any:
	name = applicant.get("ai_assessment") or frappe.db.get_value(
		"AI Candidate Assessment", {"job_applicant": applicant.name}, "name"
	)
	if name:
		return frappe.get_doc("AI Candidate Assessment", name)
	op = opening_ai(applicant.job_title) or {}
	doc = frappe.get_doc(
		{
			"doctype": "AI Candidate Assessment",
			"job_applicant": applicant.name,
			"job_opening": applicant.job_title,
			"ai_profile": op.get("ai_profile"),
			"status": "Processing",
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Job Applicant", applicant.name, "ai_assessment", doc.name, update_modified=False)
	return doc


def fail(job, applicant_name: str, message: str) -> None:
	job.reload()
	job.status = "Failed"
	job.error_message = message[:1000]
	job.finished_on = now_datetime()
	if job.started_on:
		job.duration_s = (job.finished_on - job.started_on).total_seconds()
	job.save(ignore_permissions=True)
	frappe.db.set_value("Job Applicant", applicant_name, "ai_status", "Failed", update_modified=False)
	applicant = frappe.get_doc("Job Applicant", applicant_name)
	a = _assessment_for(applicant)
	a.status = "Failed"
	a.save(ignore_permissions=True)
	audit("screening.failed", "Job Applicant", applicant_name, job.job_opening, reason=message[:300],
		  details={"job": job.name, "attempts": job.attempts})
	frappe.db.commit()
	publish(applicant_name, job.job_opening, "Failed")


def _retry_or_fail(job_name: str, applicant_name: str, message: str, force: bool) -> None:
	job = frappe.get_doc("AI Recruitment Job", job_name)
	if cint(job.attempts) < cint(job.max_attempts or 3):
		job.status = "Queued"
		job.error_message = f"{message} — {frappe._('retrying')}"
		job.save(ignore_permissions=True)
		frappe.db.commit()
		time.sleep(min(5 * cint(job.attempts), 20))
		frappe.enqueue("ido_talent_ai.screening.run_job", queue="long", timeout=1800, ai_job=job.name, force=force)
	else:
		fail(job, applicant_name, message)


def run_job(ai_job: str, force: bool = False) -> None:
	"""Send one applicant to the engine. No database transaction is held open during an HTTP call
	(long transactions collide with other workers on the naming series under MariaDB snapshot
	isolation); engine outages and database conflicts are retried, other engine errors fail."""
	job = frappe.get_doc("AI Recruitment Job", ai_job)
	if job.status in ("Completed",):
		return
	applicant = frappe.get_doc("Job Applicant", job.reference_name)
	job.status = "Running"
	job.attempts = cint(job.attempts) + 1
	job.started_on = job.started_on or now_datetime()
	job.error_message = None
	job.save(ignore_permissions=True)
	frappe.db.commit()
	try:
		ref = ensure_candidate_ref(applicant)
		a = _assessment_for(applicant)  # exists before the engine can call back
		payload = candidate_payload(applicant)
		signature = data_signature(applicant)
		frappe.db.commit()
		engine.put(f"/v1/candidates/{ref}", json=payload)
		push_cv(applicant, ref)
		frappe.db.commit()
		res = engine.post(
			"/v1/screenings",
			json={"job_ref": applicant.job_title, "candidate_ref": ref, "force": bool(force or job.job_type == "Rescreen")},
		)
		sid = res["screening_id"]
		frappe.db.set_value("AI Recruitment Job", job.name, "engine_screening_id", sid, update_modified=False)
		if frappe.db.get_value("AI Candidate Assessment", a.name, "engine_screening_id") != sid:
			frappe.db.set_value(
				"AI Candidate Assessment", a.name, {"engine_screening_id": sid, "candidate_ref": ref, "status": "Processing"},
				update_modified=False,
			)
		frappe.db.set_value(
			"Job Applicant", applicant.name, {"ai_data_hash": signature, "ai_assessment": a.name, "ai_stale": 0},
			update_modified=False,
		)
		frappe.db.commit()
		# an identical input was already screened, or the callback raced this commit: read it now
		current = engine.get(f"/v1/screenings/{sid}")
		if current.get("status") in ("completed", "needs_review", "failed"):
			db_retry(apply_result, current)
	except engine.EngineUnavailable as e:
		frappe.db.rollback()
		_retry_or_fail(job.name, applicant.name, str(e), force)
	except TRANSIENT_DB_ERRORS as e:
		frappe.db.rollback()
		_retry_or_fail(job.name, applicant.name, f"{type(e).__name__}: {e}", force)
	except engine.EngineError as e:
		frappe.db.rollback()
		fail(frappe.get_doc("AI Recruitment Job", job.name), applicant.name, f"{e}")
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(title="Talent AI: screening job crashed")
		fail(frappe.get_doc("AI Recruitment Job", job.name), applicant.name, f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------------------- results
def apply_result(payload: dict) -> str | None:
	"""Write the engine result (callback or sync) into AI Candidate Assessment and Job Applicant."""
	ref = payload.get("candidate_ref")
	applicant_name = frappe.db.get_value("Job Applicant", {"ai_candidate_ref": ref}, "name")
	if not applicant_name:
		return None
	applicant = frappe.get_doc("Job Applicant", applicant_name)
	a = _assessment_for(applicant)
	if a.engine_screening_id and a.engine_screening_id != payload.get("screening_id"):
		return None  # an older screening answered late; the newer one wins
	status = STATUS_FROM_ENGINE.get(payload.get("status"), "Processing")
	if status == "Processing":
		return a.name
	dup = payload.get("duplicate_of")
	dup_name = frappe.db.get_value("Job Applicant", {"ai_candidate_ref": dup}, "name") if dup else None
	op = opening_ai(applicant.job_title) or {}
	a.update(
		{
			"status": status,
			"engine_screening_id": payload.get("screening_id"),
			"candidate_ref": ref,
			"ai_profile": op.get("ai_profile"),
			"profile_version": payload.get("job_version"),
			"eligibility": payload.get("eligibility") or "",
			"score": payload.get("score"),
			"coverage": flt(payload.get("coverage")) * 100,
			"band": payload.get("band") or "",
			"rank": payload.get("rank"),
			"ranked_total": payload.get("ranked_total"),
			"flags": ", ".join(payload.get("flags") or []),
			"summary": payload.get("summary"),
			"stale": 0 if payload.get("current", True) else 1,
			"stale_reason": payload.get("stale_reason") or "",
			"duplicate_of": dup_name,
			"evaluated_on": now_datetime(),
			"model": (payload.get("versions") or {}).get("model"),
			"prompt_version": (payload.get("versions") or {}).get("prompt"),
			"input_hash": payload.get("input_hash"),
			"total_ms": (payload.get("versions") or {}).get("total_ms"),
			"raw_result": to_json(payload),
		}
	)
	a.set("evidence", [])
	for c in payload.get("criteria") or []:
		a.append(
			"evidence",
			{
				"criterion_key": c.get("key"),
				"criterion": c.get("text"),
				"weight": c.get("weight"),
				"mandatory": c.get("mandatory"),
				"score": c.get("level"),
				"effective_level": c.get("effective_level"),
				"source": c.get("source") or "",
				"field": c.get("field"),
				"evidence_text": c.get("evidence"),
				"missing_data": c.get("missing_evidence"),
				"contradiction": c.get("contradiction"),
				"confirmed_by_cv": c.get("confirmed_by_cv"),
				"cv_quote": c.get("cv_quote"),
				"cv_level": c.get("cv_level"),
				"form_level": c.get("form_level"),
				"overridden_level": c.get("overridden_level"),
				"override_reason": c.get("override_reason"),
				"override_by": c.get("override_by"),
			},
		)
	a.save(ignore_permissions=True)
	frappe.db.set_value(
		"Job Applicant",
		applicant_name,
		{
			"ai_status": status,
			"ai_score": payload.get("score") if status != "Failed" else None,
			"ai_band": payload.get("band") or "",
			"ai_eligibility": payload.get("eligibility") or "",
			"ai_coverage": flt(payload.get("coverage")) * 100,
			"ai_rank": payload.get("rank") or 0,
			"ai_evaluated_on": now_datetime(),
			"ai_assessment": a.name,
			"ai_stale": 0 if payload.get("current", True) else 1,
			"ai_duplicate_of": dup_name,
			"ai_flags": ", ".join(payload.get("flags") or []),
		},
		update_modified=False,
	)
	jobs = frappe.get_all(
		"AI Recruitment Job",
		filters={"engine_screening_id": payload.get("screening_id"), "status": ["in", ["Running", "Queued"]]},
		pluck="name",
	)
	for jn in jobs:
		job = frappe.get_doc("AI Recruitment Job", jn)
		job.status = "Failed" if status == "Failed" else "Completed"
		job.error_message = payload.get("error") if status == "Failed" else None
		job.finished_on = now_datetime()
		if job.started_on:
			job.duration_s = (job.finished_on - job.started_on).total_seconds()
		job.save(ignore_permissions=True)
	audit(
		"screening." + (payload.get("status") or ""),
		"Job Applicant",
		applicant_name,
		applicant.job_title,
		profile_version=payload.get("job_version"),
		actor="system",
		details={"score": payload.get("score"), "band": payload.get("band"), "eligibility": payload.get("eligibility"),
				 "flags": payload.get("flags"), "screening_id": payload.get("screening_id")},
	)
	frappe.enqueue(
		"ido_talent_ai.screening.refresh_ranks", queue="short", job_id=f"talent_ai_ranks::{applicant.job_title}",
		deduplicate=True, enqueue_after_commit=True, opening=applicant.job_title,
	)
	publish(applicant_name, applicant.job_title, status)
	return a.name


def refresh_ranks(opening: str) -> None:
	"""Ranks move when anyone completes: copy the engine ranking onto the applicants of the opening."""
	try:
		rk = engine.get(f"/v1/jobs/{opening}/ranking")
	except engine.EngineError:
		return
	db_retry(_write_ranks, opening, rk)
	frappe.publish_realtime("talent_ai_batch", {"job_opening": opening, "ranks": True})


def _write_ranks(opening: str, rk: dict) -> None:
	by_ref = {x["candidate_ref"]: x for x in rk.get("ranked", [])}
	for name, ref, rank in frappe.get_all(
		"Job Applicant", filters={"job_title": opening, "ai_candidate_ref": ["is", "set"]},
		fields=["name", "ai_candidate_ref", "ai_rank"], as_list=True,
	):
		new = (by_ref.get(ref) or {}).get("rank") or 0
		if cint(rank) != new:
			frappe.db.set_value("Job Applicant", name, "ai_rank", new, update_modified=False)
	total = rk.get("ranked_total") or 0
	for a in frappe.get_all(
		"AI Candidate Assessment", filters={"job_opening": opening}, fields=["name", "candidate_ref", "rank", "ranked_total"]
	):
		new = (by_ref.get(a.candidate_ref) or {}).get("rank") or 0
		if cint(a.rank) != new or cint(a.ranked_total) != total:
			frappe.db.set_value("AI Candidate Assessment", a.name, {"rank": new, "ranked_total": total}, update_modified=False)


# ----------------------------------------------------------------------------- edits, deletes, openings
def on_applicant_update(doc, method=None):
	"""Editing answers/facts/CV after evaluation makes the result stale until it is re-scored.
	A status change made outside the HR decision buttons (form field, Kanban) is still audited."""
	try:
		before = doc.get_doc_before_save()
		if before and before.status != doc.status and not doc.flags.get("talent_ai_internal"):
			audit("hr.status_changed", "Job Applicant", doc.name, doc.job_title, reason=None,
				  details={"from": before.status, "to": doc.status, "via": "form or board, no reason recorded"})
	except Exception:
		frappe.log_error(title="Talent AI: status audit failed")
	try:
		if doc.flags.get("talent_ai_internal") or not doc.get("ai_assessment"):
			return
		sig = data_signature(doc)
		if sig == (doc.get("ai_data_hash") or ""):
			return
		frappe.db.set_value("Job Applicant", doc.name, {"ai_stale": 1, "ai_data_hash": sig}, update_modified=False)
		frappe.db.set_value(
			"AI Candidate Assessment", doc.ai_assessment, {"stale": 1, "stale_reason": "data_changed"}, update_modified=False
		)
		audit("applicant.edited_after_evaluation", "Job Applicant", doc.name, doc.job_title,
			  details={"assessment": doc.ai_assessment})
		frappe.enqueue("ido_talent_ai.screening.sync_candidate", queue="short", enqueue_after_commit=True, applicant=doc.name)
		publish(doc.name, doc.job_title, doc.get("ai_status"))
	except Exception:
		frappe.log_error(title="Talent AI: stale detection failed")


def sync_candidate(applicant: str) -> None:
	"""Push edited data to the engine so its ranking also treats the old result as stale."""
	doc = frappe.get_doc("Job Applicant", applicant)
	if not doc.get("ai_candidate_ref"):
		return
	try:
		engine.put(f"/v1/candidates/{doc.ai_candidate_ref}", json=candidate_payload(doc))
		push_cv(doc, doc.ai_candidate_ref)
	except engine.EngineError:
		frappe.log_error(title="Talent AI: could not sync the edited applicant")


def on_applicant_trash(doc, method=None):
	"""Full erasure in the engine, and remove the AI records that point to the applicant."""
	if doc.get("ai_candidate_ref"):
		try:
			engine.delete(f"/v1/candidates/{doc.ai_candidate_ref}")
		except engine.EngineError:
			frappe.log_error(title="Talent AI: engine erasure failed")
	frappe.db.set_value("Job Applicant", doc.name, "ai_assessment", None, update_modified=False)
	for name in frappe.get_all("AI Candidate Assessment", filters={"job_applicant": doc.name}, pluck="name"):
		frappe.delete_doc("AI Candidate Assessment", name, ignore_permissions=True, force=True)
	for name in frappe.get_all("AI Candidate Assessment", filters={"duplicate_of": doc.name}, pluck="name"):
		frappe.db.set_value("AI Candidate Assessment", name, "duplicate_of", None)
	frappe.db.sql(
		"update `tabJob Applicant` set ai_duplicate_of=NULL where ai_duplicate_of=%s", (doc.name,)
	)
	for name in frappe.get_all("AI Recruitment Job", filters={"reference_doctype": "Job Applicant", "reference_name": doc.name}, pluck="name"):
		frappe.delete_doc("AI Recruitment Job", name, ignore_permissions=True, force=True)
	# the audit trail stays, de-identified: its rows no longer point to the erased applicant
	marker = "erased:" + hashlib.sha256(doc.name.encode()).hexdigest()[:12]
	frappe.db.sql(
		"""update `tabAI Recruitment Audit Log` set reference_name=%s
		where reference_doctype='Job Applicant' and reference_name=%s""",
		(marker, doc.name),
	)
	audit("applicant.deleted", None, None, doc.job_title, details={"applicant": marker, "candidate_ref": doc.get("ai_candidate_ref")})


def on_opening_trash(doc, method=None):
	"""The opening is deleted: remove its job (versions and screenings) from the engine too."""
	if not doc.get("ai_enabled") and not doc.get("ai_profile"):
		return
	try:
		engine.delete(f"/v1/jobs/{doc.name}")
	except engine.EngineError as e:
		if getattr(e, "status", None) != 404:
			frappe.log_error(title="Talent AI: engine job deletion failed")
	audit("job.deleted", "Job Opening", doc.name, None)


def on_opening_validate(doc, method=None):
	"""Keep ai_profile_approved and the application route in step with the profile."""
	approved = 0
	if doc.get("ai_profile"):
		p = frappe.db.get_value("AI Job Profile", doc.ai_profile, ["version", "job_opening"], as_dict=True)
		approved = 1 if p and cint(p.version) > 0 and p.job_opening == doc.name else 0
	doc.ai_profile_approved = approved
	if doc.get("ai_enabled") and approved:
		if not doc.get("job_application_route"):
			doc.job_application_route = APPLY_ROUTE
	elif doc.get("job_application_route") == APPLY_ROUTE:
		doc.job_application_route = None


# ----------------------------------------------------------------------------- scheduler
def sync_running_jobs() -> None:
	"""Safety net when a callback is missed: fetch finished screenings and time out stuck ones."""
	timeout_min = 30
	# a worker died (restart, crash) before the engine accepted the screening: run the job again
	for job in frappe.get_all(
		"AI Recruitment Job",
		filters={"status": "Running", "engine_screening_id": ["is", "not set"], "modified": ["<", add_to_date(now_datetime(), minutes=-10)]},
		fields=["name", "reference_name", "attempts", "max_attempts"],
	):
		if cint(job.attempts) >= cint(job.max_attempts or 3):
			fail(frappe.get_doc("AI Recruitment Job", job.name), job.reference_name, "worker stopped before the engine accepted the job")
			continue
		frappe.db.set_value("AI Recruitment Job", job.name, "status", "Queued", update_modified=True)
		frappe.db.commit()
		frappe.enqueue("ido_talent_ai.screening.run_job", queue="long", timeout=1800, ai_job=job.name)
	for job in frappe.get_all(
		"AI Recruitment Job", filters={"status": "Running", "engine_screening_id": ["is", "set"]},
		fields=["name", "engine_screening_id", "started_on", "reference_name"],
	):
		try:
			res = engine.get(f"/v1/screenings/{job.engine_screening_id}")
		except engine.EngineError:
			continue
		if res.get("status") in ("completed", "needs_review", "failed"):
			db_retry(apply_result, res)
		elif job.started_on and job.started_on < add_to_date(now_datetime(), minutes=-timeout_min):
			fail(frappe.get_doc("AI Recruitment Job", job.name), job.reference_name, "timeout")


def retry_failed_jobs() -> None:
	"""Hourly: retry jobs that failed because the engine was unreachable (at most once per hour each)."""
	for job in frappe.get_all(
		"AI Recruitment Job",
		filters={"status": "Failed", "modified": [">", add_to_date(now_datetime(), days=-1)]},
		fields=["name", "reference_name", "error_message", "job_type"],
	):
		msg = job.error_message or ""
		if "reach" in msg or "timeout" in msg or "AI engine error" in msg:
			db_retry(queue_screening, job.reference_name, "Rescreen")
	frappe.db.commit()


def opening_stats(opening: str) -> dict:
	rows = frappe.db.sql(
		"""select status, count(*) n from `tabAI Recruitment Job` where job_opening=%s group by status""",
		(opening,), as_dict=True,
	)
	jobs = {r.status: r.n for r in rows}
	ai = frappe.db.sql(
		"""select ifnull(ai_status,'') s, count(*) n from `tabJob Applicant` where job_title=%s group by ai_status""",
		(opening,), as_dict=True,
	)
	return {"jobs": jobs, "applicants": {r.s: r.n for r in ai}}

"""Whitelisted endpoints: the public application, the engine callback and the HR actions."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import time

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import add_to_date, cint, now_datetime, validate_email_address

from ido_talent_ai import engine
from ido_talent_ai.screening import apply_result, approved_snapshot, db_retry, publish, queue_screening
from ido_talent_ai.utils import (
	DISCLAIMER_AR,
	DISCLAIMER_EN,
	audit,
	from_json,
	get_settings,
	is_hr,
	require_hr,
)

MAX_CV_BYTES = 10 * 1024 * 1024
CV_EXT = (".pdf", ".docx", ".doc", ".rtf", ".jpg", ".jpeg", ".png")
DECISIONS = ("Shortlisted", "Hold", "Rejected", "Open", "Replied", "Accepted")


# ----------------------------------------------------------------------------- public form
def _form_context(job_title: str) -> tuple[dict, dict]:
	op = frappe.db.get_value(
		"Job Opening",
		job_title,
		["name", "job_title", "status", "ai_enabled", "ai_profile", "ai_profile_approved", "company", "designation"],
		as_dict=True,
	)
	if not op or op.status != "Open":
		frappe.throw(_("This job is not open for applications."), frappe.DoesNotExistError)
	if not (op.ai_enabled and op.ai_profile_approved and op.ai_profile):
		frappe.throw(_("This job does not accept applications through this form."))
	snap = approved_snapshot(op.ai_profile) or {}
	return op, snap


def _apply_limit() -> int:
	"""Applications per IP per 10 minutes (site config `talent_ai_apply_limit`, default 20)."""
	return cint(frappe.conf.get("talent_ai_apply_limit")) or 20


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=_apply_limit, seconds=60 * 10)
def apply():
	"""Create the Job Applicant from the public Arabic form. Always saves, even if the engine is down."""
	form = frappe.form_dict
	op, snap = _form_context(form.get("job_title"))
	errors = []
	name = (form.get("applicant_name") or "").strip()
	email = (form.get("email_id") or "").strip()
	if not name:
		errors.append("الاسم الكامل مطلوب")
	if not email or not validate_email_address(email):
		errors.append("البريد الإلكتروني غير صحيح")
	if cint(form.get("ai_consent")) != 1:
		errors.append("الموافقة على معالجة البيانات مطلوبة")
	facts_needed = {r["fact"] for r in snap.get("rules", [])}
	if "nationality" in facts_needed and not form.get("nationality"):
		errors.append("الجنسية مطلوبة")
	if "age" in facts_needed and not form.get("date_of_birth"):
		errors.append("تاريخ الميلاد مطلوب")
	answers = from_json(form.get("answers"), {}) or {}
	for q in snap.get("questions", []):
		v = answers.get(q["key"])
		if q.get("required", True) and (v is None or v == "" or v == []):
			errors.append(f"السؤال «{q['label']}» مطلوب")
	cv = frappe.request.files.get("cv") if frappe.request and frappe.request.files else None
	cv_bytes = None
	if cv and cv.filename:
		if not cv.filename.lower().endswith(CV_EXT):
			errors.append("نوع ملف السيرة غير مدعوم (PDF أو Word أو صورة)")
		else:
			cv_bytes = cv.stream.read()
			if len(cv_bytes) > MAX_CV_BYTES:
				errors.append("حجم ملف السيرة أكبر من 10 ميجابايت")
	if errors:
		frappe.local.response.http_status_code = 422
		return {"ok": False, "errors": errors}

	# The application must always be saved (acceptance criterion 6). Database conflicts are retried,
	# and nothing that belongs to the AI side (queue, audit, CV file) can undo the insert.
	for attempt in range(3):
		try:
			doc = _save_application(op, snap, form, name, email, answers, cv, cv_bytes)
			if not frappe.db.exists("Job Applicant", doc.name):
				raise frappe.QueryDeadlockError("the application row was rolled back")
			break
		except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			frappe.db.rollback()
			if attempt == 2:
				raise
			time.sleep(0.3 * (attempt + 1))
	return {"ok": True, "reference": doc.name}


def _safe_audit(*args, **kwargs) -> None:
	try:
		audit(*args, **kwargs)
	except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
		raise
	except Exception:
		try:
			frappe.log_error(title="Talent AI: audit entry not written")
		except Exception:
			pass


def _save_application(op, snap, form, name, email, answers, cv, cv_bytes):
	s = get_settings()
	doc = frappe.get_doc(
		{
			"doctype": "Job Applicant",
			"applicant_name": name,
			"email_id": email,
			"phone_number": form.get("phone_number"),
			"job_title": op.name,
			"designation": op.designation,
			"nationality": form.get("nationality") or None,
			"id_type": form.get("id_type") or None,
			"national_id": (form.get("national_id") or "").strip() or None,
			"date_of_birth": form.get("date_of_birth") or None,
			"height_cm": cint(form.get("height_cm")) or None,
			"weight_kg": cint(form.get("weight_kg")) or None,
			"ai_consent": 1,
			"ai_consent_version": s.consent_version or "v1",
			"ai_consent_on": now_datetime(),
			"status": "Open",
		}
	)
	for q in snap.get("questions", []):
		v = answers.get(q["key"])
		text = "\n".join(v) if isinstance(v, list) else ("" if v is None else str(v).strip())
		doc.append("ai_answers", {"question_key": q["key"], "question": q["label"], "answer": text, "answered": 1 if text != "" else 0})
	doc.flags.ignore_permissions = True
	doc.insert()
	cv_note = None
	if cv_bytes:
		# A damaged or unsafe file must never cost the applicant the application: the platform
		# refuses to store it (Frappe parses every PDF), so the application is kept without it and
		# the AI assesses from the answers only (decision 14).
		frappe.db.savepoint("talent_ai_cv")
		try:
			f = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": cv.filename,
					"attached_to_doctype": "Job Applicant",
					"attached_to_name": doc.name,
					"attached_to_field": "resume_attachment",
					"is_private": 1,
					"content": cv_bytes,
				}
			).insert(ignore_permissions=True)
			# the screening job runs after commit, so the attachment is in place before it starts
			frappe.db.set_value("Job Applicant", doc.name, "resume_attachment", f.file_url, update_modified=False)
		except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			raise  # the whole application is retried by apply()
		except Exception as e:
			frappe.db.rollback(save_point="talent_ai_cv")
			frappe.clear_last_message()
			cv_note = f"ملف السيرة «{cv.filename}» تالف أو غير آمن ولم يُحفظ ({type(e).__name__}). التقييم من الإجابات فقط."
			frappe.db.set_value("Job Applicant", doc.name, "ai_cv_note", cv_note, update_modified=False)
			_safe_audit("cv.rejected", "Job Applicant", doc.name, op.name, actor="Guest", details={"error": type(e).__name__})
	_safe_audit("application.submitted", "Job Applicant", doc.name, op.name, actor="Guest",
		  details={"answers": len(doc.ai_answers), "cv": bool(cv_bytes) and not cv_note, "consent_version": doc.ai_consent_version})
	return doc


@frappe.whitelist(allow_guest=True, methods=["GET"])
def job_requirements(job_title: str) -> dict:
	"""Arabic eligibility sentences for the public job page (HRMS template is not modified)."""
	op = frappe.db.get_value(
		"Job Opening", job_title, ["status", "publish", "ai_enabled", "ai_profile", "ai_profile_approved"], as_dict=True
	)
	if not op or op.status != "Open" or not op.publish or not (op.ai_enabled and op.ai_profile_approved and op.ai_profile):
		return {}
	snap = approved_snapshot(op.ai_profile) or {}
	return {"requirements": snap.get("requirements", []), "questions": len(snap.get("questions", []))}


# ----------------------------------------------------------------------------- engine callback
@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_result():
	"""HMAC-signed result from the engine: X-Talent-Signature = sha256(secret, "<ts>.<body>")."""
	body = frappe.request.get_data() or b""
	ts = frappe.get_request_header("X-Talent-Timestamp") or ""
	sig = frappe.get_request_header("X-Talent-Signature") or ""
	secret = get_settings().get_password("callback_secret", raise_exception=False) or ""
	try:
		fresh = abs(time.time() - int(ts)) <= 300
	except ValueError:
		fresh = False
	expected = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
	if not secret or not fresh or not hmac.compare_digest(expected, sig):
		frappe.local.response.http_status_code = 401
		return {"ok": False}
	payload = json.loads(body)
	frappe.set_user("Administrator")
	for attempt in range(3):  # concurrent results may collide on the naming series: retry
		try:
			name = apply_result(payload)
			frappe.db.commit()
			return {"ok": True, "assessment": name}
		except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			frappe.db.rollback()
			if attempt == 2:
				raise
			time.sleep(0.3 * (attempt + 1))


# ----------------------------------------------------------------------------- applicant (HR)
def _applicant(name: str):
	require_hr()
	doc = frappe.get_doc("Job Applicant", name)
	doc.check_permission("read")
	return doc


@frappe.whitelist()
def get_assessment(applicant: str) -> dict:
	doc = _applicant(applicant)
	out = {
		"applicant": doc.name,
		"applicant_name": doc.applicant_name,
		"status": doc.status,
		"ai_status": doc.get("ai_status"),
		"ai_stale": doc.get("ai_stale"),
		"cv_note": doc.get("ai_cv_note"),
		"decision": {"reason": doc.get("ai_decision_reason"), "by": doc.get("ai_decided_by"), "on": doc.get("ai_decided_on")},
		"consent": {
			"given": cint(doc.get("ai_consent")), "on": doc.get("ai_consent_on"), "source": doc.get("ai_consent_source"),
			"recorded_by": doc.get("ai_consent_recorded_by"), "withdrawn_on": doc.get("ai_consent_withdrawn_on"),
			"erased_on": doc.get("ai_erased_on"),
		},
		"disclaimer": {"ar": DISCLAIMER_AR, "en": DISCLAIMER_EN},
		"jobs": frappe.get_all(
			"AI Recruitment Job",
			filters={"reference_doctype": "Job Applicant", "reference_name": doc.name},
			fields=["name", "job_type", "status", "attempts", "max_attempts", "error_message", "creation", "duration_s"],
			order_by="creation desc", limit=5,
		),
		"result": None,
		"questions": [],
		"criteria": [],
	}
	if doc.get("ai_assessment"):
		a = frappe.get_doc("AI Candidate Assessment", doc.ai_assessment)
		out["assessment"] = a.name
		out["result"] = from_json(a.raw_result)
		out["stale"] = a.stale
		out["stale_reason"] = a.stale_reason
		out["duplicate_of"] = a.duplicate_of
		if a.duplicate_of:
			out["duplicate_of_name"] = frappe.db.get_value("Job Applicant", a.duplicate_of, "applicant_name")
		# the engine is the source of truth for the current rank and the CV quote boxes
		if a.engine_screening_id:
			try:
				out["result"] = engine.get(f"/v1/screenings/{a.engine_screening_id}")
			except engine.EngineError:
				out["engine_offline"] = True
	op = frappe.db.get_value("Job Opening", doc.job_title, ["ai_profile"], as_dict=True) if doc.job_title else None
	if op and op.ai_profile:
		snap = approved_snapshot(op.ai_profile) or {}
		out["questions"] = snap.get("questions", [])
		out["criteria"] = snap.get("criteria", [])
	return out


@frappe.whitelist()
def decide(applicant: str, status: str, reason: str) -> dict:
	"""HR decision. The only place in the app that changes Job Applicant.status."""
	doc = _applicant(applicant)
	doc.check_permission("write")
	if status not in DECISIONS:
		frappe.throw(_("Unknown status"))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required."))
	old = doc.status
	doc.status = status
	doc.ai_decision_reason = reason
	doc.ai_decided_by = frappe.session.user
	doc.ai_decided_on = now_datetime()
	doc.flags.talent_ai_internal = True
	doc.save()
	audit("hr.decision", "Job Applicant", doc.name, doc.job_title, reason=reason,
		  details={"from": old, "to": status})
	return {"status": doc.status}


@frappe.whitelist()
def override(applicant: str, criterion_key: str, level: int, reason: str) -> dict:
	doc = _applicant(applicant)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required."))
	a = frappe.get_doc("AI Candidate Assessment", doc.ai_assessment)
	res = engine.post(
		f"/v1/screenings/{a.engine_screening_id}/override",
		json={"criterion_key": criterion_key, "level": cint(level), "reason": reason, "by": frappe.session.user},
	)
	apply_result(res)
	audit("hr.override", "Job Applicant", doc.name, doc.job_title, reason=reason,
		  profile_version=res.get("job_version"), details={"criterion": criterion_key, "level": cint(level), "score": res.get("score")})
	return {"score": res.get("score")}


@frappe.whitelist()
def rescreen(applicant: str) -> dict:
	doc = _applicant(applicant)
	job = db_retry(queue_screening, doc.name, "Rescreen", force=True)
	return {"job": job}


@frappe.whitelist()
def retry_job(job: str) -> dict:
	require_hr()
	j = frappe.get_doc("AI Recruitment Job", job)
	new = db_retry(queue_screening, j.reference_name, "Rescreen", force=True)
	audit("ai_job.retry", "Job Applicant", j.reference_name, j.job_opening, details={"failed_job": job, "new_job": new})
	return {"job": new}


@frappe.whitelist()
def rescreen_all(job_opening: str) -> dict:
	"""«إعادة تقييم الكل»: re-score every applicant whose result is stale, failed or missing."""
	require_hr()
	rows = frappe.get_all(
		"Job Applicant",
		filters={"job_title": job_opening},
		fields=["name", "ai_status", "ai_stale", "ai_consent"],
	)
	queued, skipped = 0, []
	for r in rows:
		if not (r.ai_stale or r.ai_status in (None, "", "Failed")):
			continue
		if not r.ai_consent:  # consent withdrawn (or never given): no new processing, the others go on
			skipped.append(r.name)
			continue
		try:
			db_retry(queue_screening, r.name, "Rescreen", force=True)
			queued += 1
		except frappe.ValidationError:
			frappe.clear_messages()
			skipped.append(r.name)
	audit("job.rescreen_all", "Job Opening", job_opening, job_opening, details={"queued": queued, "skipped": skipped})
	return {"queued": queued, "skipped": len(skipped), "total": len(rows)}


# ----------------------------------------------------------------------------- ranking, CSV, compare, batch
AWAITING_AR = "بانتظار الموافقة على المعالجة — تُسجَّل الموافقة من صفحة الطلب"
AWAITING_EN = "Awaiting consent to processing — record it on the application"
WITHDRAWN_AR = "مستبعد: سحب الموافقة — حُذفت بيانات الذكاء الاصطناعي الخاصة به"
WITHDRAWN_EN = "Excluded: consent withdrawn — the AI data was erased"


def _consent_item(r, status: str, at) -> dict:
	"""A row of the consent groups: the applicant and a date, no score and no details."""
	ar, en = (AWAITING_AR, AWAITING_EN) if status == "awaiting_consent" else (WITHDRAWN_AR, WITHDRAWN_EN)
	return {"applicant": r.name, "applicant_name": r.applicant_name, "candidate_ref": r.ai_candidate_ref, "status": status,
			"score": None, "band": None, "eligibility": None, "flags": [], "reason_ar": ar, "reason_en": en,
			"at": str(at) if at else None, "hr_status": r.status}


@frappe.whitelist()
def ranking(job_opening: str) -> dict:
	"""The engine ranking with the platform's view of consent: an application without consent never
	reached the AI («بانتظار الموافقة»), one whose consent was withdrawn is out of the ranking at once
	(«مستبعد: سحب الموافقة», OPEN_QUESTIONS #20 and #21)."""
	require_hr()
	rk = engine.get(f"/v1/jobs/{job_opening}/ranking")
	rows = frappe.get_all(
		"Job Applicant", filters={"job_title": job_opening},
		fields=["name", "applicant_name", "status", "ai_candidate_ref", "ai_consent", "ai_consent_withdrawn_on", "creation"],
	)
	by_ref = {r.ai_candidate_ref: r for r in rows if r.ai_candidate_ref}
	withdrawn = {r.name for r in rows if r.ai_consent_withdrawn_on}

	def enrich(x):
		n = by_ref.get(x["candidate_ref"]) or {}
		x["applicant"] = n.get("name")
		x["applicant_name"] = n.get("applicant_name") or x["candidate_ref"]
		x["hr_status"] = n.get("status")
		return x

	# the platform is the source of truth for consent: a withdrawal whose erasure in the engine is
	# still pending (engine was down) is already out of the ranking here
	rk["ranked"] = [x for x in map(enrich, rk["ranked"]) if x["applicant"] not in withdrawn]
	for i, x in enumerate(rk["ranked"]):
		x["rank"] = i + 1
	rk["ranked_total"] = len(rk["ranked"])
	for g in list(rk["groups"]):
		rk["groups"][g] = [x for x in map(enrich, rk["groups"][g]) if g == "consent_withdrawn" or x["applicant"] not in withdrawn]
	known = {x["candidate_ref"] for x in rk["ranked"]} | {x["candidate_ref"] for g in rk["groups"].values() for x in g}
	listed = {x["applicant"] for x in rk["groups"].get("consent_withdrawn", [])}
	awaiting, gone, queued = [], [], []
	for r in rows:
		if r.ai_consent_withdrawn_on:
			if r.name not in listed:
				gone.append(_consent_item(r, "consent_withdrawn", r.ai_consent_withdrawn_on))
		elif not r.ai_consent:
			awaiting.append(_consent_item(r, "awaiting_consent", r.creation))
		elif not r.ai_candidate_ref or r.ai_candidate_ref not in known:  # not yet known to the engine
			queued.append({"applicant": r.name, "applicant_name": r.applicant_name, "status": "queued", "reason_ar": "في الانتظار",
						   "reason_en": "Queued", "score": None})
	for x in rk["groups"].get("consent_withdrawn", []):
		r = next((y for y in rows if y.name == x.get("applicant")), None)
		if r:
			x.update(_consent_item(r, "consent_withdrawn", r.ai_consent_withdrawn_on))
	rk["groups"]["processing"] = rk["groups"].get("processing", []) + queued
	rk["groups"]["consent_withdrawn"] = [x for x in rk["groups"].get("consent_withdrawn", []) if x.get("applicant")] + gone
	rk["groups"]["awaiting_consent"] = awaiting
	rk["applicants_total"] = len(rows)
	op = frappe.db.get_value("Job Opening", job_opening, ["job_title", "ai_profile"], as_dict=True)
	snap = approved_snapshot(op.ai_profile) if op and op.ai_profile else None
	rk["criteria"] = (snap or {}).get("criteria", [])
	rk["opening_title"] = op.job_title if op else job_opening
	rk["disclaimer"] = {"ar": DISCLAIMER_AR, "en": DISCLAIMER_EN}
	return rk


@frappe.whitelist()
def export_ranking_csv(job_opening: str) -> None:
	"""CSV (UTF-8 with BOM so Excel shows Arabic correctly)."""
	rk = ranking(job_opening)
	buf = io.StringIO()
	w = csv.writer(buf)
	w.writerow(["الترتيب", "المتقدم", "الاسم", "الدرجة", "الفئة", "التغطية", "حالة المعالجة", "نسخة المعايير", "نقاط القوة", "حالة الطلب"])
	band_ar = {"high": "مرتفعة", "medium": "متوسطة", "low": "منخفضة"}
	ai_ar = {"completed": "مكتمل", "needs_review": "يحتاج مراجعة"}
	for x in rk["ranked"]:
		w.writerow([x["rank"], x.get("applicant"), x.get("applicant_name"), x["score"], band_ar.get(x["band"], x["band"]),
					f"{round((x['coverage'] or 0) * 100)}%", ai_ar.get(x["status"], x["status"]), f"v{x['job_version']}",
					" | ".join(x.get("strengths") or []), x.get("hr_status")])
	w.writerow([])
	w.writerow([DISCLAIMER_AR])
	frappe.response["type"] = "download"
	frappe.response["filename"] = f"ranking_{job_opening}.csv"
	frappe.response["filecontent"] = ("﻿" + buf.getvalue()).encode("utf-8")
	frappe.response["content_type"] = "text/csv; charset=utf-8"
	audit("ranking.exported", "Job Opening", job_opening, job_opening, details={"ranked": len(rk["ranked"])})


@frappe.whitelist()
def compare(applicants: str) -> dict:
	"""Feature 10: 2–3 applicants side by side, criterion by criterion, with evidence."""
	require_hr()
	names = from_json(applicants, []) if isinstance(applicants, str) else applicants
	if not 2 <= len(names) <= 3:
		frappe.throw(_("Select 2 or 3 applicants."))
	out = []
	opening = None
	for n in names:
		doc = frappe.get_doc("Job Applicant", n)
		doc.check_permission("read")
		if opening and doc.job_title != opening:
			frappe.throw(_("Compare applicants of the same opening only."))
		opening = doc.job_title
		res = None
		if doc.get("ai_assessment"):
			a = frappe.get_doc("AI Candidate Assessment", doc.ai_assessment)
			res = from_json(a.raw_result)
			if a.engine_screening_id:
				try:
					res = engine.get(f"/v1/screenings/{a.engine_screening_id}")
				except engine.EngineError:
					pass
		out.append({"applicant": doc.name, "applicant_name": doc.applicant_name, "ai_status": doc.get("ai_status"), "result": res})
	op = frappe.db.get_value("Job Opening", opening, ["ai_profile"], as_dict=True)
	snap = approved_snapshot(op.ai_profile) if op and op.ai_profile else None
	audit("ranking.compared", "Job Opening", opening, opening, details={"applicants": names})
	return {"opening": opening, "applicants": out, "criteria": (snap or {}).get("criteria", []),
			"disclaimer": {"ar": DISCLAIMER_AR, "en": DISCLAIMER_EN}}


@frappe.whitelist()
def batch_status(job_opening: str) -> dict:
	require_hr()
	from ido_talent_ai.screening import opening_stats

	st = opening_stats(job_opening)
	recent = frappe.db.sql(  # the site's clock, like `finished_on` (the database clock may be UTC)
		"""select count(*) from `tabAI Recruitment Job` where job_opening=%s and status in ('Completed','Failed')
		and finished_on > %s""",
		(job_opening, add_to_date(now_datetime(), minutes=-10)),
	)[0][0]
	avg = frappe.db.sql(
		"""select avg(duration_s) from `tabAI Recruitment Job` where job_opening=%s and status='Completed'""", (job_opening,)
	)[0][0]
	jobs = frappe.get_all(
		"AI Recruitment Job", filters={"job_opening": job_opening}, order_by="creation desc", limit=12,
		fields=["name", "reference_name", "job_type", "status", "attempts", "max_attempts", "error_message", "duration_s", "creation"],
	)
	for j in jobs:
		j["applicant_name"] = frappe.db.get_value("Job Applicant", j.reference_name, "applicant_name")
	return {**st, "finished_last_10_min": recent, "avg_duration_s": avg, "recent_jobs": jobs,
			"title": frappe.db.get_value("Job Opening", job_opening, "job_title")}


@frappe.whitelist()
def home_counts() -> dict:
	"""Live counts for the «التوظيف الذكي» home page (HR only)."""
	require_hr()
	rows = frappe.db.sql(
		"""select ifnull(ai_status, '') s, count(*) n from `tabJob Applicant` group by ai_status""", as_dict=True
	)
	by = {r.s: r.n for r in rows}
	return {
		"openings": frappe.db.count("Job Opening", {"ai_enabled": 1, "status": "Open"}),
		"applicants": sum(by.values()),
		"processing": by.get("Processing", 0),
		"needs_review": by.get("Needs Review", 0),
		"failed": by.get("Failed", 0),
	}


@frappe.whitelist()
def openings() -> list[dict]:
	require_hr()
	return frappe.get_all(
		"Job Opening", filters={"ai_enabled": 1}, fields=["name", "job_title", "status", "ai_profile", "ai_profile_approved"],
		order_by="creation desc",
	)


# ----------------------------------------------------------------------------- talent pool (feature 13)
@frappe.whitelist()
def talent_pool(job_opening: str, limit: int = 20) -> dict:
	"""Past applicants suggested for this opening: hard rules first, then similarity. Suggestions
	only: nothing is moved and no status changes."""
	require_hr()
	frappe.get_doc("Job Opening", job_opening).check_permission("read")
	# the engine tenant may also hold other systems' candidates: keep this site's applicants only
	res = engine.post("/v1/talent-pool/search", json={"job_ref": job_opening, "limit": 200}, timeout=180)
	rows = frappe.get_all(
		"Job Applicant", filters={"ai_candidate_ref": ["is", "set"]},
		fields=["name", "applicant_name", "status", "job_title", "ai_candidate_ref", "creation"],
	)
	by_ref = {r.ai_candidate_ref: r for r in rows}
	res["suggestions"] = [x for x in res.get("suggestions", []) if x["candidate_ref"] in by_ref][: cint(limit) or 20]
	res["excluded"] = [x for x in res.get("excluded", []) if x["candidate_ref"] in by_ref]
	res["counts"] = {"suggested": len(res["suggestions"]), "excluded": len(res["excluded"])}
	titles = dict(frappe.get_all("Job Opening", fields=["name", "job_title"], as_list=True))

	def enrich(x):
		r = by_ref.get(x["candidate_ref"]) or {}
		x["applicant"] = r.get("name")
		x["applicant_name"] = r.get("applicant_name") or x["candidate_ref"]
		x["hr_status"] = r.get("status")
		x["previous_opening"] = r.get("job_title")
		x["previous_opening_title"] = titles.get(r.get("job_title"), r.get("job_title"))
		return x

	res["suggestions"] = [enrich(x) for x in res.get("suggestions", [])]
	res["excluded"] = [enrich(x) for x in res.get("excluded", [])]
	res["opening_title"] = titles.get(job_opening, job_opening)
	res["disclaimer"] = {"ar": DISCLAIMER_AR, "en": DISCLAIMER_EN}
	audit("talent_pool.searched", "Job Opening", job_opening, job_opening,
		  details={"suggested": len(res["suggestions"]), "excluded": len(res["excluded"])})
	return res


@frappe.whitelist()
def withdraw_consent(applicant: str, reason: str) -> dict:
	"""The applicant withdrew consent to the AI processing of their data (recorded by HR with a
	reason). The application leaves the ranking at once and shows in «مستبعد: سحب الموافقة» with no
	score and no details; what the AI made of it is erased here and in the engine (documents,
	structured profile, talent-pool index, results); the application itself stays in Frappe.
	OPEN_QUESTIONS #21: default decided by Nadine on 2026-10-16, until the client confirms."""
	from ido_talent_ai.screening import NO_CONSENT_JOB, cancel_jobs, erase_in_engine, forget_ai_results

	doc = _applicant(applicant)
	doc.check_permission("write")
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required."))
	if not doc.get("ai_consent"):
		frappe.throw(_("This application has no consent to AI processing to withdraw."))

	def record():
		frappe.db.set_value("Job Applicant", doc.name, {"ai_consent": 0, "ai_consent_withdrawn_on": now_datetime()}, update_modified=False)
		cancelled = cancel_jobs(doc.name, NO_CONSENT_JOB)
		forget_ai_results(doc.name)
		audit("applicant.consent_withdrawn", "Job Applicant", doc.name, doc.job_title, reason=reason, details={"cancelled_jobs": cancelled})

	db_retry(record)  # committed first: a result arriving now is already refused
	erased = erase_in_engine(doc.name)  # the engine down: `erase_pending` retries every two minutes
	frappe.db.commit()
	publish(doc.name, doc.job_title, "Consent Withdrawn")
	return {"ok": True, "erased": erased}


@frappe.whitelist()
def record_consent(applicant: str, source: str) -> dict:
	"""A paper application (or any application saved without the consent box) is kept but never
	screened. When the applicant's consent exists outside the system, HR records it with its source
	(for example «ورقة موقّعة»); who recorded it and when are kept, and the screening starts by itself.
	OPEN_QUESTIONS #20: default decided by Nadine on 2026-10-16, until the client confirms."""
	from ido_talent_ai.screening import ai_ready, safe_enqueue

	doc = _applicant(applicant)
	doc.check_permission("write")
	source = (source or "").strip()
	if not source:
		frappe.throw(_("The source of the consent is required, for example: a signed paper form."))
	if doc.get("ai_consent"):
		frappe.throw(_("This application already has consent to AI processing."))
	if doc.get("ai_consent_withdrawn_on"):
		frappe.throw(_("The applicant withdrew consent to AI processing; a withdrawal is final for this application."))
	s = get_settings()
	ready = bool(s.enabled and s.auto_screen_on_apply and ai_ready(doc.job_title))
	version = s.consent_version or "v1"
	frappe.db.set_value(
		"Job Applicant", doc.name,
		{"ai_consent": 1, "ai_consent_version": version, "ai_consent_on": now_datetime(), "ai_consent_source": source[:500],
		 "ai_consent_recorded_by": frappe.session.user, "ai_status": "Processing" if ready else ""},
		update_modified=False,
	)
	audit("applicant.consent_recorded", "Job Applicant", doc.name, doc.job_title, reason=source[:500],
		  details={"consent_version": version, "screening_started": ready})
	if ready:
		frappe.db.after_commit.add(
			lambda name=doc.name: safe_enqueue("ido_talent_ai.screening.start_screening", queue="short", applicant=name)
		)
	publish(doc.name, doc.job_title, "Processing" if ready else None)
	return {"ok": True, "screening_started": ready}


# ----------------------------------------------------------------------------- CV analysis (proxy to the engine)
@frappe.whitelist()
def cv_analysis(applicant: str) -> dict:
	doc = _applicant(applicant)
	ref = doc.get("ai_candidate_ref")
	if not ref:
		frappe.throw(_("This applicant has not been sent to the AI engine yet."))
	d = engine.get(f"/v1/candidates/{ref}/cv", params={"include_raw": "true"})["document"]
	d["page_images"] = [
		f"/api/method/ido_talent_ai.api.cv_page?applicant={doc.name}&page={i}" for i in range(len((d.get("layout") or {}).get("pages", [])))
	]
	if doc.get("ai_assessment"):
		a = frappe.db.get_value("AI Candidate Assessment", doc.ai_assessment, "engine_screening_id")
		if a:
			try:
				s = engine.get(f"/v1/screenings/{a}")
				d["quote_boxes"] = (s.get("cv") or {}).get("quote_boxes", {})
				d["criteria"] = s.get("criteria", [])
				d["stages"] = s.get("stages", [])
			except engine.EngineError:
				pass
	audit("cv.viewed", "Job Applicant", doc.name, doc.job_title)
	return d


@frappe.whitelist()
def cv_page(applicant: str, page: int = 0):
	doc = _applicant(applicant)
	r = engine.call("GET", f"/v1/candidates/{doc.ai_candidate_ref}/cv/pages/{cint(page)}", raw=True)
	frappe.response["type"] = "binary"
	frappe.response["filename"] = f"cv-page-{cint(page) + 1}.png"
	frappe.response["filecontent"] = r.content
	frappe.response["content_type"] = r.headers.get("content-type", "image/png")
	frappe.response["display_content_as"] = "inline"


# ----------------------------------------------------------------------------- settings
@frappe.whitelist()
def engine_settings() -> dict:
	require_hr()
	return {"health": engine.health(), "settings": engine.get("/v1/settings")}


@frappe.whitelist()
def i_am_hr() -> bool:
	return is_hr()

"""Integration tests on a local bench (no engine needed: engine calls are mocked).

	bench --site talent.localhost run-tests --app ido_talent_ai

Covers the client's acceptance criteria that live in Frappe: A1 (application with all answers),
A2 (statuses), A4 (stale after an edit), A5 (AI never changes the status, HR-only fields),
A6 (engine down never blocks an application) and the profile approval rules."""

from __future__ import annotations

import hashlib
import io
import hmac
import json
import time
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ido_talent_ai import api, engine, profile, screening
from ido_talent_ai.utils import get_settings

DESIGNATION = "_Test Talent Designation"
TITLE = "_Test Talent Opening"


def _company() -> str:
	name = frappe.db.get_value("Company", {}, "name")
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "Company", "company_name": "_Test Talent Co", "abbr": "_TTC", "default_currency": "SAR", "country": "Saudi Arabia"}
	).insert().name


EMP_USER = "talentai.employee.test@example.com"


def _employee_user() -> str:
	"""A user that really holds the Employee role. ERPNext strips that role from a user without an
	Employee record (validate_employee_role), so the test user gets a synthetic one."""
	from ido_talent_ai.scripts.seed_demo import ensure_employee

	_company()
	if not frappe.db.exists("Gender", "Male"):
		frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
	if not frappe.db.exists("User", EMP_USER):
		frappe.get_doc({"doctype": "User", "email": EMP_USER, "first_name": "Emp", "send_welcome_email": 0}).insert()
	ensure_employee(EMP_USER, "Emp")
	frappe.get_doc("User", EMP_USER).add_roles("Employee")
	assert "Employee" in frappe.get_roles(EMP_USER), "the test user must hold the Employee role"
	return EMP_USER


def _criteria():
	rows = []
	for key, text, w, q in (("supervision", "الإشراف", 60, "years_sup"), ("licence", "الرخصة", 40, "licence")):
		r = {"criterion_key": key, "criterion": text, "weight": w, "mandatory": 1 if key == "supervision" else 0, "question": q}
		for lvl in (0, 25, 50, 75, 100):
			r[f"rubric_{lvl}"] = f"level {lvl}"
		if q == "years_sup":
			r.update({"hint_25": "> 0", "hint_50": ">= 1", "hint_75": "> 2", "hint_100": "> 5"})
		else:
			r.update({"hint_0": "لا", "hint_50": "منتهية", "hint_100": "سارية"})
		rows.append(r)
	return rows


def _questions():
	return [
		{"question_key": "years_sup", "label": "سنوات الإشراف", "question_type": "number", "required": 1},
		{"question_key": "licence", "label": "الرخصة", "question_type": "select", "options": "لا\nمنتهية\nسارية", "required": 1},
		{"question_key": "last_job", "label": "آخر عمل", "question_type": "text", "required": 0},
	]


def _engine_ok(method, path, **kw):
	if method == "PUT" and path.startswith("/v1/jobs/"):
		return {"version": {"version": 1}, "new_version": True}
	if method == "PUT" and path.startswith("/v1/candidates/"):
		return {"ok": True}
	if method == "POST" and path == "/v1/screenings":
		return {"screening_id": "scr_test_4242", "created": True}
	if method == "PUT" and path == "/v1/settings":
		return {}
	return {}


class TestTalentAI(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		s = frappe.get_single("AI Recruitment Settings")
		s.enabled = 1
		s.auto_screen_on_apply = 1
		s.engine_url = "http://127.0.0.1:9"  # nothing listens: the engine is "down" unless mocked
		s.allowed_facts = "nationality\nage\nheight_cm\nweight_kg"
		s.max_retries = 3
		s.flags.talent_ai_local_only = True
		s.save()
		if not frappe.db.exists("Designation", DESIGNATION):
			frappe.get_doc({"doctype": "Designation", "designation_name": DESIGNATION}).insert()
		cls.opening = frappe.db.get_value("Job Opening", {"job_title": TITLE})
		if not cls.opening:
			cls.opening = frappe.get_doc(
				{"doctype": "Job Opening", "job_title": TITLE, "company": _company(), "designation": DESIGNATION,
				 "status": "Open", "publish": 1, "ai_enabled": 1, "route": "jobs/test/talent-ai-test"}
			).insert().name
		cls.profile = frappe.db.get_value("AI Job Profile", {"job_opening": cls.opening})
		if not cls.profile:
			doc = frappe.get_doc({"doctype": "AI Job Profile", "job_opening": cls.opening, "title": TITLE, "status": "Draft"})
			for c in _criteria():
				doc.append("criteria", c)
			for q in _questions():
				doc.append("questions", q)
			doc.append("rules", {"fact": "height_cm", "operator": ">=", "value": "175"})
			doc.insert()
			cls.profile = doc.name
		with patch.object(engine, "call", side_effect=_engine_ok):
			profile.approve(cls.profile)
		frappe.db.commit()

	def _apply(self, email, answers, **facts):
		form = {
			"job_title": self.opening, "applicant_name": "متقدم تجريبي", "email_id": email, "nationality": "Saudi Arabia",
			"id_type": "هوية وطنية", "national_id": facts.pop("national_id", "1000000999"), "date_of_birth": "1995-01-01",
			"height_cm": facts.pop("height_cm", 180), "ai_consent": 1, "answers": json.dumps(answers, ensure_ascii=False),
		}
		frappe.local.form_dict = frappe._dict(form)
		frappe.local.request = None
		with patch.object(frappe, "enqueue") as enq:
			res = api.apply.__wrapped__() if hasattr(api.apply, "__wrapped__") else api.apply()
		return res, enq

	# ------------------------------------------------------------------ A1 + A6
	def test_application_saved_with_all_answers_even_if_engine_down(self):
		res, enq = self._apply("a1.test@example.com", {"years_sup": 0, "licence": "سارية", "last_job": ""})
		self.assertTrue(res["ok"], res)
		doc = frappe.get_doc("Job Applicant", res["reference"])
		self.assertEqual(doc.job_title, self.opening)
		answers = {r.question_key: (r.answer, r.answered) for r in doc.ai_answers}
		self.assertEqual(answers["years_sup"], ("0", 1))  # 0 is a real answer
		self.assertEqual(answers["last_job"], ("", 0))  # blank = not answered
		self.assertEqual(doc.ai_status, "Processing")
		self.assertEqual(doc.status, "Open")
		# the request only queues a background job after its commit; that job creates the AI Recruitment Job
		self.assertFalse(enq.called)
		with patch.object(frappe, "enqueue") as enq:
			frappe.db.commit()
		self.assertEqual(enq.call_args.args[0], "ido_talent_ai.screening.start_screening")
		self.assertFalse(frappe.db.exists("AI Recruitment Job", {"reference_name": doc.name}))
		with patch.object(frappe, "enqueue") as enq2:
			screening.start_screening(doc.name)
		job = frappe.get_last_doc("AI Recruitment Job", filters={"reference_name": doc.name})
		self.assertEqual(job.status, "Queued")
		self.assertEqual(enq2.call_args.args[0], "ido_talent_ai.screening.run_job")
		# the engine is down: the job retries and finally fails, the application stays saved
		with patch.object(frappe, "enqueue"), patch.object(time, "sleep"):
			for _ in range(3):
				screening.run_job(job.name)
		job.reload()
		self.assertEqual(job.status, "Failed")
		self.assertEqual(job.attempts, 3)
		self.assertIn("reach", job.error_message)
		doc.reload()
		self.assertEqual(doc.ai_status, "Failed")
		self.assertEqual(doc.status, "Open")

	def test_missing_required_answer_and_consent_are_refused(self):
		frappe.local.form_dict = frappe._dict(
			{"job_title": self.opening, "applicant_name": "x", "email_id": "a1.bad@example.com", "nationality": "Saudi Arabia",
			 "date_of_birth": "1995-01-01", "ai_consent": 0, "answers": json.dumps({"licence": "سارية"})}
		)
		frappe.local.request = None
		res = api.apply()
		self.assertFalse(res["ok"])
		self.assertTrue(any("الموافقة" in e for e in res["errors"]))
		self.assertTrue(any("سنوات الإشراف" in e for e in res["errors"]))

	def test_blank_is_never_zero(self):
		self.assertEqual(screening.parse_answer("", "number"), "")
		self.assertEqual(screening.parse_answer("0", "number"), 0)
		self.assertEqual(screening.parse_answer("٣", "number"), 3)
		self.assertEqual(screening.parse_answer("العربية\nالإنجليزية", "multiselect"), ["العربية", "الإنجليزية"])

	def test_engine_payload_has_no_identity(self):
		res, _ = self._apply("a1.payload@example.com", {"years_sup": 3, "licence": "سارية"}, national_id="1234567890")
		doc = frappe.get_doc("Job Applicant", res["reference"])
		payload = screening.candidate_payload(doc)
		text = json.dumps(payload, ensure_ascii=False)
		self.assertNotIn("1234567890", text)
		self.assertNotIn("متقدم تجريبي", text)
		self.assertNotIn("a1.payload@example.com", text)
		self.assertEqual(len(payload["id_token"]), 64)
		self.assertEqual(payload["answers"]["years_sup"], 3)

	# ------------------------------------------------------------------ A2 + A5
	def _complete(self, name, status="completed", **extra):
		doc = frappe.get_doc("Job Applicant", name)
		ref = screening.ensure_candidate_ref(doc)
		a = screening._assessment_for(doc)
		if not a.engine_screening_id:
			TestTalentAI._sid = getattr(TestTalentAI, "_sid", 5000) + 1
			a.engine_screening_id = f"scr_test_{TestTalentAI._sid}"  # the engine uses string ids
			a.save()
		payload = {
			"screening_id": a.engine_screening_id, "candidate_ref": ref, "status": status, "eligibility": "eligible",
			"score": 70.0, "coverage": 1.0, "band": "medium", "rank": 1, "ranked_total": 1, "flags": [], "current": True,
			"job_version": 1, "criteria": [{"key": "supervision", "text": "الإشراف", "weight": 60, "mandatory": True, "level": 50,
											"effective_level": 50, "source": "form_field", "field": "years_sup", "evidence": "1"}],
			"versions": {"model": "fake", "prompt": "judge-v1", "total_ms": 10}, **extra,
		}
		with patch.object(frappe, "enqueue"):
			screening.apply_result(payload)
		return payload

	def test_result_sets_ai_fields_but_never_the_status(self):
		res, _ = self._apply("a2.test@example.com", {"years_sup": 1, "licence": "سارية"})
		self._complete(res["reference"])
		doc = frappe.get_doc("Job Applicant", res["reference"])
		self.assertEqual(doc.ai_status, "Completed")
		self.assertEqual(doc.ai_score, 70.0)
		self.assertEqual(doc.status, "Open")
		self._complete(res["reference"], status="needs_review")
		self.assertEqual(frappe.db.get_value("Job Applicant", doc.name, "ai_status"), "Needs Review")
		self.assertEqual(frappe.db.get_value("Job Applicant", doc.name, "status"), "Open")

	def test_hr_decision_needs_a_reason_and_is_logged(self):
		res, _ = self._apply("a5.decide@example.com", {"years_sup": 2, "licence": "سارية"})
		with self.assertRaises(frappe.ValidationError):
			api.decide(res["reference"], "Rejected", "  ")
		api.decide(res["reference"], "Shortlisted", "خبرة إشراف مناسبة")
		doc = frappe.get_doc("Job Applicant", res["reference"])
		self.assertEqual(doc.status, "Shortlisted")
		self.assertEqual(doc.ai_decided_by, "Administrator")
		log = frappe.get_last_doc("AI Recruitment Audit Log", filters={"action": "hr.decision", "reference_name": doc.name})
		self.assertEqual(log.reason, "خبرة إشراف مناسبة")

	def test_ai_fields_are_hr_only(self):
		meta = frappe.get_meta("Job Applicant")
		for f in ("ai_status", "ai_score", "ai_html", "national_id", "ai_assessment"):
			self.assertEqual(meta.get_field(f).permlevel, 1, f)
		perms = frappe.get_all("Custom DocPerm", filters={"parent": "Job Applicant", "permlevel": 1}, pluck="role")
		self.assertTrue({"HR Manager", "HR User"} <= set(perms))
		self.assertNotIn("Employee", perms)
		frappe.set_user(_employee_user())
		try:
			with self.assertRaises(frappe.PermissionError):
				api.ranking(self.opening)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------------ A4
	def test_edit_after_evaluation_makes_the_result_stale(self):
		res, _ = self._apply("a4.test@example.com", {"years_sup": 1, "licence": "سارية"})
		self._complete(res["reference"])
		doc = frappe.get_doc("Job Applicant", res["reference"])
		for row in doc.ai_answers:
			if row.question_key == "years_sup":
				row.answer = "6"
		with patch.object(frappe, "enqueue"):
			doc.save()
		self.assertEqual(frappe.db.get_value("Job Applicant", doc.name, "ai_stale"), 1)
		self.assertEqual(frappe.db.get_value("AI Candidate Assessment", doc.ai_assessment, "stale_reason"), "data_changed")

	# ------------------------------------------------------------------ callback
	def test_callback_signature(self):
		secret = get_settings().get_password("callback_secret")
		body = json.dumps({"candidate_ref": "JA-NOPE", "status": "completed"}).encode()
		ts = str(int(time.time()))
		good = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

		def call(sig, stamp):
			env = EnvironBuilder(method="POST", data=body, headers={"X-Talent-Timestamp": stamp, "X-Talent-Signature": sig,
																	 "Content-Type": "application/json"}).get_environ()
			frappe.local.request = Request(env)
			frappe.local.response = frappe._dict()
			try:
				return api.receive_result()
			finally:
				frappe.local.request = None
				frappe.set_user("Administrator")

		self.assertEqual(call(good, ts), {"ok": True, "assessment": None})
		self.assertEqual(call("sha256=" + "0" * 64, ts), {"ok": False})
		old = str(int(time.time()) - 3600)
		old_sig = "sha256=" + hmac.new(secret.encode(), old.encode() + b"." + body, hashlib.sha256).hexdigest()
		self.assertEqual(call(old_sig, old), {"ok": False})

	# ------------------------------------------------------------------ profile
	def test_weights_must_total_100_to_approve(self):
		doc = frappe.get_doc("AI Job Profile", self.profile)
		doc.criteria[0].weight = 65  # total 105
		doc.save()
		with self.assertRaises(frappe.ValidationError):
			profile.approve(doc.name)
		doc.reload()
		doc.criteria[0].weight = 60
		doc.save()

	def test_ai_section_is_on_the_main_tab_of_the_opening(self):
		"""The guide screenshots found the Talent AI section of Job Opening inside the «Pay Details» tab."""
		names = [f.fieldname for f in frappe.get_meta("Job Opening").fields]
		first_tab = next((i for i, f in enumerate(frappe.get_meta("Job Opening").fields) if f.fieldtype == "Tab Break"), len(names))
		self.assertLess(names.index("ai_section"), first_tab)
		self.assertLess(names.index("ai_links"), first_tab)

	def test_opening_points_the_apply_button_to_the_ai_form(self):
		op = frappe.get_doc("Job Opening", self.opening)
		self.assertEqual(op.ai_profile_approved, 1)
		self.assertEqual(op.job_application_route, "ai-apply")
		self.assertEqual(api.job_requirements(self.opening)["requirements"], ["الطول 175 سم أو أكثر"])

	# ------------------------------------------------------------------ feature 13
	def test_talent_pool_names_suggestions_and_exclusions(self):
		res, _ = self._apply("pool.one@example.com", {"years_sup": 6, "licence": "سارية"})
		doc = frappe.get_doc("Job Applicant", res["reference"])
		ref = screening.ensure_candidate_ref(doc)
		engine_out = {
			"job_ref": self.opening, "suggestion_only": True, "model": "fake",
			"suggestions": [{"candidate_ref": ref, "similarity": 0.8, "eligibility": "eligible", "eligibility_checks": [], "previous": {"job_title": TITLE}}],
			"excluded": [{"candidate_ref": "JA-UNKNOWN", "reason": "retention_expired", "reason_ar": "انتهت مدة الاحتفاظ ببياناته", "reason_en": "", "details": []}],
			"counts": {"suggested": 1, "excluded": 1},
		}
		with patch.object(engine, "call", return_value=engine_out) as call:
			out = api.talent_pool(self.opening)
		self.assertEqual(call.call_args.args[:2], ("POST", "/v1/talent-pool/search"))
		self.assertTrue(out["suggestion_only"])
		self.assertEqual(out["suggestions"][0]["applicant"], doc.name)
		self.assertEqual(out["suggestions"][0]["applicant_name"], "متقدم تجريبي")
		self.assertEqual(out["excluded"], [])  # candidates of other systems in the same engine tenant are not shown

	def test_withdrawn_consent_stops_processing(self):
		res, _ = self._apply("consent.off@example.com", {"years_sup": 2, "licence": "سارية"})
		name = res["reference"]
		with self.assertRaises(frappe.ValidationError):
			api.withdraw_consent(name, "")
		with patch.object(engine, "call", side_effect=_engine_ok):
			screening.ensure_candidate_ref(frappe.get_doc("Job Applicant", name))
			api.withdraw_consent(name, "طلب المتقدم ذلك")
		self.assertEqual(frappe.db.get_value("Job Applicant", name, "ai_consent"), 0)
		self.assertTrue(frappe.db.get_value("Job Applicant", name, "ai_consent_withdrawn_on"))
		payload = screening.candidate_payload(frappe.get_doc("Job Applicant", name))
		self.assertFalse(payload["consent"])
		with self.assertRaises(frappe.ValidationError):
			screening.queue_screening(name, "Rescreen")
		screening.start_screening(name)
		self.assertFalse(frappe.db.exists("AI Recruitment Job", {"reference_name": name, "status": "Queued"}))
		# «إعادة تقييم الكل» skips this applicant and still re-scores the others (the full browser test
		# found the whole run stopping at the first applicant who withdrew consent)
		other, _ = self._apply("consent.on@example.com", {"years_sup": 4, "licence": "سارية"}, national_id="1000000888")
		for n in (name, other["reference"]):
			frappe.db.set_value("Job Applicant", n, {"ai_stale": 1, "ai_status": "Completed"})
		with patch.object(frappe, "enqueue"):
			res = api.rescreen_all(self.opening)
		self.assertGreaterEqual(res["queued"], 1)
		self.assertGreaterEqual(res["skipped"], 1)
		self.assertTrue(frappe.db.exists("AI Recruitment Job", {"reference_name": other["reference"], "status": "Queued"}))
		self.assertFalse(frappe.db.exists("AI Recruitment Job", {"reference_name": name, "status": "Queued"}))

	# ------------------------------------------------------------------ the application is always saved
	def test_application_is_always_saved(self):
		"""Acceptance criterion 6 as a permanent test: nothing on the AI side can lose an application."""
		answers = {"years_sup": 3, "licence": "سارية"}

		def saved(res):
			self.assertTrue(res["ok"], res)
			self.assertTrue(frappe.db.exists("Job Applicant", res["reference"]))
			self.assertEqual(len(frappe.get_doc("Job Applicant", res["reference"]).ai_answers), 3)

		# 1. the queue (Redis) is down when the request commits
		with patch.object(frappe, "enqueue", side_effect=ConnectionError("queue down")):
			res, _ = self._apply("always.queue@example.com", answers, national_id="1000088001")
			frappe.db.commit()  # runs the after-commit enqueue, which must swallow the error
		saved(res)
		self.assertEqual(frappe.db.get_value("Job Applicant", res["reference"], "ai_status"), "Processing")
		# 2. the AI hook itself crashes
		with patch.object(screening, "data_signature", side_effect=RuntimeError("boom")):
			res, _ = self._apply("always.hook@example.com", answers, national_id="1000088002")
		saved(res)
		# 3. the audit log cannot be written
		with patch.object(api, "audit", side_effect=RuntimeError("audit down")):
			res, _ = self._apply("always.audit@example.com", answers, national_id="1000088003")
		saved(res)
		# 4. a database conflict on the first attempt is retried
		real = api._save_application
		calls = {"n": 0}

		def flaky(*a, **k):
			calls["n"] += 1
			if calls["n"] == 1:
				raise frappe.QueryDeadlockError("conflict")
			return real(*a, **k)

		with patch.object(api, "_save_application", side_effect=flaky):
			res, _ = self._apply("always.retry@example.com", answers, national_id="1000088004")
		saved(res)
		self.assertEqual(calls["n"], 2)
		# 5. the AI is switched off: saved, no AI status
		frappe.db.set_single_value("AI Recruitment Settings", "enabled", 0)
		frappe.clear_document_cache("AI Recruitment Settings", "AI Recruitment Settings")
		try:
			res, _ = self._apply("always.off@example.com", answers, national_id="1000088005")
			saved(res)
			self.assertFalse(frappe.db.get_value("Job Applicant", res["reference"], "ai_status"))
		finally:
			frappe.db.set_single_value("AI Recruitment Settings", "enabled", 1)
			frappe.clear_document_cache("AI Recruitment Settings", "AI Recruitment Settings")
		# 6. a damaged CV: saved without the file, with a note, assessed from the answers
		form = {
			"job_title": self.opening, "applicant_name": "متقدم بسيرة تالفة", "email_id": "always.cv@example.com",
			"nationality": "Saudi Arabia", "id_type": "هوية وطنية", "national_id": "1000088006", "date_of_birth": "1995-01-01",
			"height_cm": 180, "ai_consent": 1, "answers": json.dumps(answers, ensure_ascii=False),
		}
		env = EnvironBuilder(method="POST", data={"cv": (io.BytesIO(b"%PDF-1.4\n" + b"\x00garbage" * 400), "broken.pdf")}).get_environ()
		frappe.local.request = Request(env)
		frappe.local.request_ip = "127.0.0.1"  # the public endpoint is rate limited per IP
		frappe.local.form_dict = frappe._dict(form)
		try:
			with patch.object(frappe, "enqueue"):
				res = api.apply()
		finally:
			frappe.local.request = None
		saved(res)
		doc = frappe.get_doc("Job Applicant", res["reference"])
		self.assertFalse(doc.resume_attachment)
		self.assertIn("broken.pdf", doc.ai_cv_note or "")

	# ------------------------------------------------------------------ CV files
	def test_text_cv_is_sent_as_bytes_and_cv_problems_never_fail(self):
		"""RTF is a text format, so Frappe's File.get_content() returns str for it (the full browser test
		found an RTF CV ending in «فشل»). The engine gets the raw bytes, and a CV that cannot be read or is
		refused by the engine never fails the screening (decision 14)."""
		res, _ = self._apply("cv.rtf.test@example.com", {"years_sup": 3, "licence": "سارية"}, national_id="1000000777")
		name = res["reference"]
		rtf = b"{\\rtf1\\ansi{\\fonttbl\\f0 Arial;}\\f0 Security supervisor, 6 years.\\par}"
		f = frappe.get_doc({"doctype": "File", "file_name": "cv.rtf", "content": rtf, "attached_to_doctype": "Job Applicant",
		                    "attached_to_name": name, "is_private": 1}).insert(ignore_permissions=True)
		frappe.db.set_value("Job Applicant", name, "resume_attachment", f.file_url)
		self.assertIsInstance(frappe.get_doc("File", f.name).get_content(), str)  # the trap
		doc = frappe.get_doc("Job Applicant", name)
		with patch.object(engine, "put") as put:
			screening.push_cv(doc, "JA-TEST-RTF")
		sent = put.call_args.kwargs["files"]["file"][1]
		self.assertIsInstance(sent, bytes)
		self.assertEqual(sent, rtf)
		# the engine refuses the file: no exception, a note for HR, the screening goes on
		frappe.db.set_value("Job Applicant", name, "ai_cv_sha", "")
		doc = frappe.get_doc("Job Applicant", name)
		with patch.object(engine, "put", side_effect=engine.EngineError("unsupported file", 415)):
			screening.push_cv(doc, "JA-TEST-RTF")
		self.assertIn("رفض ملف السيرة", frappe.db.get_value("Job Applicant", name, "ai_cv_note") or "")
		# the file cannot be read on the platform: same
		with patch.object(screening, "_file_bytes", side_effect=OSError("disk")):
			screening.push_cv(doc, "JA-TEST-RTF")
		self.assertIn("تعذّرت قراءة ملف السيرة", frappe.db.get_value("Job Applicant", name, "ai_cv_note") or "")
		# an engine outage is still raised, so the whole job is retried later
		with patch.object(engine, "put", side_effect=engine.EngineUnavailable("down")):
			with self.assertRaises(engine.EngineUnavailable):
				screening.push_cv(doc, "JA-TEST-RTF")

	# ------------------------------------------------------------------ permissions
	def test_every_hr_method_refuses_other_users_first(self):
		"""Every whitelisted method except the public form, the job requirements, the signed engine
		callback and i_am_hr refuses a non-HR user before it reads or changes anything."""
		import inspect

		from ido_talent_ai import profile
		from ido_talent_ai.talent_ai.doctype.ai_recruitment_settings import ai_recruitment_settings

		public = {"apply", "job_requirements", "receive_result", "i_am_hr"}
		methods = [
			f for m in (api, profile, ai_recruitment_settings) for _, f in inspect.getmembers(m, inspect.isfunction)
			if f in frappe.whitelisted and f.__module__ == m.__name__ and f.__name__ not in public
		]
		self.assertGreaterEqual(len(methods), 22)
		frappe.set_user(_employee_user())
		try:
			for f in methods:
				kwargs = {
					n: 0 if p.annotation in (int, "int") else "x"
					for n, p in inspect.signature(f).parameters.items() if p.default is inspect.Parameter.empty
				}
				with self.assertRaises(frappe.PermissionError, msg=f.__name__):
					f(**kwargs)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------------ home page
	def test_hr_users_land_on_the_home_page_in_arabic(self):
		from ido_talent_ai.utils import HOME_ROUTE, on_session_creation

		email = "talentai.hr.landing@example.com"
		if not frappe.db.exists("User", email):
			u = frappe.get_doc({"doctype": "User", "email": email, "first_name": "HR", "send_welcome_email": 0})
			u.insert()
			u.add_roles("HR User")
		frappe.db.set_value("User", email, "language", "")
		frappe.set_user(email)
		try:
			frappe.local.flags.home_page = None
			on_session_creation()
			self.assertEqual(frappe.local.flags.home_page, HOME_ROUTE)
			self.assertEqual(frappe.db.get_value("User", email, "language"), "ar")
			counts = api.home_counts()
			self.assertTrue({"openings", "applicants", "processing", "needs_review", "failed"} <= set(counts))
		finally:
			frappe.local.flags.home_page = None
			frappe.set_user("Administrator")
		# an Employee keeps the normal landing page and cannot read the counts
		frappe.set_user(_employee_user())
		try:
			frappe.local.flags.home_page = None
			on_session_creation()
			self.assertFalse(frappe.local.flags.home_page)
			with self.assertRaises(frappe.PermissionError):
				api.home_counts()
		finally:
			frappe.set_user("Administrator")

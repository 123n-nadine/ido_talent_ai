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
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import flt
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
		# no real background job may leave a test: a job queued here would run on the bench's shared
		# workers against an engine nobody serves (tests that look at the queue patch it themselves)
		cls._no_jobs = patch.object(frappe, "enqueue")
		cls._no_jobs.start()
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

	@classmethod
	def tearDownClass(cls):
		frappe.db.after_commit.reset()  # callbacks of the tests (screening starts) never run later
		cls._no_jobs.stop()
		super().tearDownClass()

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
		self.assertIn("غير متاح حاليًا", job.error_message)  # the plain sentence for HR, no technical name (round 10)
		doc.reload()
		self.assertEqual(doc.ai_status, "Failed")
		self.assertEqual(doc.status, "Open")
		# final QA (Q9): the hourly retry recognises that failure and queues the application again
		with patch.object(screening, "queue_screening") as again:
			screening.retry_failed_jobs()
		self.assertIn(doc.name, [c.args[0] for c in again.call_args_list])

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

	# ------------------------------------------------------------------ consent defaults (OPEN_QUESTIONS #20, #21)
	def _paper_application(self, tag: str) -> str:
		"""An application entered by HR in the desk from a paper form: no consent box was ticked."""
		doc = frappe.get_doc(
			{"doctype": "Job Applicant", "applicant_name": "طلب ورقي", "email_id": f"paper.{tag}.{frappe.generate_hash(length=6)}@example.com",
			 "job_title": self.opening, "designation": DESIGNATION, "status": "Open", "nationality": "Saudi Arabia", "height_cm": 180}
		)
		doc.append("ai_answers", {"question_key": "years_sup", "question": "سنوات الإشراف", "answer": "3", "answered": 1})
		doc.append("ai_answers", {"question_key": "licence", "question": "الرخصة", "answer": "سارية", "answered": 1})
		with patch.object(frappe, "enqueue"):
			doc.insert()
		return doc.name

	def test_paper_application_waits_until_hr_records_the_consent(self):
		"""#20: saved as usual, never screened without consent; HR records the consent with a
		mandatory source, who and when are kept, and the screening starts by itself."""
		name = self._paper_application("wait")
		row = frappe.db.get_value("Job Applicant", name, ["ai_status", "ai_consent", "ai_candidate_ref"], as_dict=True)
		self.assertEqual(row.ai_status, "Awaiting Consent")
		self.assertFalse(row.ai_consent)
		self.assertFalse(row.ai_candidate_ref)  # nothing of it reached the engine
		self.assertFalse(frappe.db.exists("AI Recruitment Job", {"reference_name": name}))
		with self.assertRaises(frappe.ValidationError):
			screening.queue_screening(name, "Rescreen")
		screening.start_screening(name)
		self.assertFalse(frappe.db.exists("AI Recruitment Job", {"reference_name": name}))
		with patch.object(engine, "call", side_effect=AssertionError("no engine call without consent")):
			rk_engine = {"total": 0, "ranked_total": 0, "ranked": [], "groups": {}}
			with patch.object(engine, "get", return_value=rk_engine):
				rk = api.ranking(self.opening)
		self.assertIn(name, [x["applicant"] for x in rk["groups"]["awaiting_consent"]])
		self.assertNotIn(name, [x.get("applicant") for x in rk["groups"]["processing"]])
		self.assertIsNone(next(x for x in rk["groups"]["awaiting_consent"] if x["applicant"] == name)["score"])
		# the source is mandatory, and only HR may record it
		with self.assertRaises(frappe.ValidationError):
			api.record_consent(name, "   ")
		frappe.set_user(_employee_user())
		try:
			with self.assertRaises(frappe.PermissionError):
				api.record_consent(name, "ورقة موقّعة")
		finally:
			frappe.set_user("Administrator")
		with patch.object(frappe, "enqueue") as enq:
			res = api.record_consent(name, "ورقة موقّعة")
			frappe.db.commit()  # the screening is started after the commit
		self.assertTrue(res["screening_started"])
		row = frappe.db.get_value(
			"Job Applicant", name,
			["ai_status", "ai_consent", "ai_consent_source", "ai_consent_recorded_by", "ai_consent_on", "ai_consent_version"], as_dict=True,
		)
		self.assertEqual((row.ai_status, row.ai_consent, row.ai_consent_source), ("Processing", 1, "ورقة موقّعة"))
		self.assertEqual(row.ai_consent_recorded_by, "Administrator")
		self.assertTrue(row.ai_consent_on and row.ai_consent_version)
		started = [c.kwargs.get("applicant") for c in enq.call_args_list if c.args and c.args[0] == "ido_talent_ai.screening.start_screening"]
		self.assertIn(name, started)
		log = frappe.get_all("AI Recruitment Audit Log", filters={"reference_name": name, "action": "applicant.consent_recorded"},
							 fields=["actor", "reason", "timestamp"])
		self.assertEqual([(x.actor, x.reason) for x in log], [("Administrator", "ورقة موقّعة")])
		self.assertTrue(log[0].timestamp)
		with self.assertRaises(frappe.ValidationError):  # recorded once
			api.record_consent(name, "ورقة موقّعة")
		# from here it is screened like any other application
		with patch.object(frappe, "enqueue"):
			screening.start_screening(name)
		self.assertTrue(frappe.db.exists("AI Recruitment Job", {"reference_name": name, "status": "Queued"}))

	def test_withdrawn_consent_leaves_the_ranking_and_erases_the_ai_data(self):
		"""#21: out of the ranking at once, in «مستبعد: سحب الموافقة» with no score and no details;
		the AI data is erased in the engine and in Frappe; the application stays."""
		res, _ = self._apply("withdraw.erase@example.com", {"years_sup": 6, "licence": "سارية"}, national_id="1000000777")
		name = res["reference"]
		ref = screening.ensure_candidate_ref(frappe.get_doc("Job Applicant", name))
		result = {
			"candidate_ref": ref, "screening_id": "scr_withdraw_1", "status": "completed", "score": 88.5, "band": "high",
			"eligibility": "eligible", "coverage": 1.0, "rank": 1, "ranked_total": 1, "flags": [], "job_version": 1,
			"criteria": [{"key": "supervision", "text": "الإشراف", "weight": 60, "level": 100, "source": "form_field", "evidence": "6"}],
		}
		with patch.object(frappe, "enqueue"):
			screening.apply_result(result)
		self.assertEqual(frappe.db.get_value("Job Applicant", name, "ai_score"), 88.5)
		# a later application of the same person was grouped as its duplicate
		copy, _ = self._apply("withdraw.copy@example.com", {"years_sup": 6, "licence": "سارية"}, national_id="1000000777")
		frappe.db.set_value("Job Applicant", copy["reference"], "ai_duplicate_of", name)
		sent = []

		def fake(method, path, **kw):
			sent.append((method, path, kw.get("json")))
			if method == "PUT" and path == f"/v1/candidates/{ref}":
				return {"consent": False, "erased": {"documents": 1, "screenings": 1, "embeddings": 1, "files": 1, "promoted": []}}
			return _engine_ok(method, path, **kw)

		with patch.object(engine, "call", side_effect=fake), patch.object(frappe, "enqueue"):
			out = api.withdraw_consent(name, "طلب المتقدم ذلك")
		self.assertTrue(out["erased"])
		self.assertIn(("PUT", f"/v1/candidates/{ref}", {"consent": False}), sent)  # nothing but the withdrawal goes out
		row = frappe.db.get_value(
			"Job Applicant", name,
			["ai_status", "ai_score", "ai_band", "ai_rank", "ai_assessment", "ai_consent", "ai_consent_withdrawn_on", "ai_erased_on"],
			as_dict=True,
		)
		self.assertEqual(row.ai_status, "Consent Withdrawn")
		self.assertFalse(row.ai_score or row.ai_band or row.ai_rank or row.ai_assessment or row.ai_consent)
		self.assertTrue(row.ai_consent_withdrawn_on and row.ai_erased_on)
		self.assertFalse(frappe.db.exists("AI Candidate Assessment", {"job_applicant": name}))
		self.assertFalse(frappe.db.get_value("Job Applicant", copy["reference"], "ai_duplicate_of"))
		self.assertEqual(len(frappe.get_doc("Job Applicant", name).ai_answers), 3)  # the application itself stays
		# the audit trail keeps the actions, not the findings
		details = frappe.get_all("AI Recruitment Audit Log", filters={"reference_name": name, "action": ["like", "screening.%"]}, pluck="details")
		self.assertTrue(details)
		for d in details:
			self.assertNotIn("88.5", d)
			self.assertIn("erased", d)
		for action in ("applicant.consent_withdrawn", "applicant.ai_data_erased"):
			self.assertTrue(frappe.db.exists("AI Recruitment Audit Log", {"reference_name": name, "action": action}), action)
		# a result that arrives late is never written
		with patch.object(frappe, "enqueue"):
			self.assertIsNone(screening.apply_result(result))
		self.assertFalse(frappe.db.get_value("Job Applicant", name, "ai_score"))
		self.assertFalse(frappe.db.exists("AI Candidate Assessment", {"job_applicant": name}))
		# out of the ranking even while the engine still lists it (its erasure pending there)
		groups = {g: [] for g in ("not_eligible", "needs_review", "processing", "failed", "stale", "duplicate", "consent_withdrawn")}
		engine_rk = {"total": 1, "ranked_total": 1, "groups": groups,
					 "ranked": [{"candidate_ref": ref, "rank": 1, "score": 88.5, "band": "high", "coverage": 1.0, "status": "completed"}]}
		with patch.object(engine, "get", return_value=engine_rk):
			rk = api.ranking(self.opening)
		self.assertNotIn(name, [x.get("applicant") for x in rk["ranked"]])
		(item,) = [x for x in rk["groups"]["consent_withdrawn"] if x["applicant"] == name]
		self.assertIsNone(item["score"])
		self.assertTrue(item["at"])
		self.assertEqual(item["flags"], [])
		# no new processing, and the withdrawal is final for this application
		with self.assertRaises(frappe.ValidationError):
			screening.queue_screening(name, "Rescreen")
		with self.assertRaises(frappe.ValidationError):
			api.record_consent(name, "ورقة موقّعة")
		with self.assertRaises(frappe.ValidationError):
			api.withdraw_consent(name, "مرة أخرى")

	def test_withdrawal_while_the_engine_is_down_is_erased_later(self):
		res, _ = self._apply("withdraw.down@example.com", {"years_sup": 2, "licence": "سارية"}, national_id="1000000666")
		name = res["reference"]
		screening.ensure_candidate_ref(frappe.get_doc("Job Applicant", name))
		with patch.object(frappe, "enqueue"):
			job = screening.queue_screening(name, "Screening")
		with patch.object(engine, "call", side_effect=engine.EngineUnavailable("down")), patch.object(frappe, "enqueue"):
			out = api.withdraw_consent(name, "طلب المتقدم ذلك")
		self.assertFalse(out["erased"])
		self.assertEqual(frappe.db.get_value("AI Recruitment Job", job, "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("Job Applicant", name, "ai_status"), "Consent Withdrawn")
		self.assertFalse(frappe.db.get_value("Job Applicant", name, "ai_erased_on"))
		# the cancelled job never runs, and a failure never puts «فشل» over «سحب الموافقة»
		with patch.object(engine, "call", side_effect=AssertionError("must not call the engine")):
			screening.run_job(job)
		screening.fail(frappe.get_doc("AI Recruitment Job", job), name, "boom")
		self.assertEqual(frappe.db.get_value("AI Recruitment Job", job, "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("Job Applicant", name, "ai_status"), "Consent Withdrawn")
		# the two-minute safety net erases it as soon as the engine answers
		with patch.object(engine, "call", side_effect=_engine_ok), patch.object(frappe, "enqueue"):
			screening.erase_pending()
		self.assertTrue(frappe.db.get_value("Job Applicant", name, "ai_erased_on"))

	def test_the_safety_nets_read_the_site_clock(self):
		"""`creation` and `finished_on` are in the site's time zone while the database clock may be
		UTC (it is on the local bench): rebuilding the demo found 15 applications left «Processing»
		because the 2-minute safety net compared them with SQL now()."""
		from frappe.utils import flt, add_to_date, now_datetime

		res, _ = self._apply("safety.net@example.com", {"years_sup": 2, "licence": "سارية"}, national_id="1000000555")
		name = res["reference"]
		frappe.db.delete("AI Recruitment Job", {"reference_name": name})
		frappe.db.set_value("Job Applicant", name, {"ai_status": "Processing", "creation": add_to_date(now_datetime(), minutes=-3)}, update_modified=False)
		screening.queue_missing()
		self.assertTrue(frappe.db.exists("AI Recruitment Job", {"reference_name": name, "status": "Queued"}))
		# a job that finished half an hour ago is not «finished in the last 10 minutes»
		job = frappe.get_all("AI Recruitment Job", filters={"reference_name": name}, pluck="name")[0]
		before = api.batch_status(self.opening)["finished_last_10_min"]
		frappe.db.set_value("AI Recruitment Job", job, {"status": "Completed", "finished_on": add_to_date(now_datetime(), minutes=-30)})
		self.assertEqual(api.batch_status(self.opening)["finished_last_10_min"], before)

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

	def test_partial_cv_read_flag_is_shown_on_the_assessment_card(self):
		"""Round 8: the engine raises «cv_partial_read» when the model's first answer overran and the
		CV was re-read from its first half; the card must label the flag and explain it to HR."""
		import os

		js = open(os.path.join(os.path.dirname(__file__), "..", "public", "js", "talent_ai.js"), encoding="utf-8").read()
		self.assertIn('cv_partial_read: { ar: "السيرة قُرئت جزئيًا"', js)
		self.assertIn('includes("cv_partial_read") ? `<div class="note strong">', js)
		self.assertIn("أُعيدت القراءة على أول نصف النص فقط", js)

	def test_engine_down_message_is_plain_arabic(self):
		"""Round 10: with the engine unreachable the settings screen gets a plain sentence for HR,
		never a server error or a technical name."""
		old = get_settings().engine_url
		frappe.db.set_single_value("AI Recruitment Settings", "engine_url", "http://127.0.0.1:9")  # a closed port
		frappe.clear_cache()
		try:
			frappe.set_user("hr.manager@example.com")
			r = api.engine_settings()
		finally:
			frappe.db.set_single_value("AI Recruitment Settings", "engine_url", old)
			frappe.clear_cache()
			frappe.set_user("Administrator")
		self.assertFalse(r["available"])
		self.assertEqual(r["message"], "محرك الذكاء غير متاح حاليًا — الطلبات تُحفظ بشكل طبيعي وتُقيَّم عند عودته.")
		for word in ("ConnectionError", "EngineUnavailable", "Traceback", "http"):
			self.assertNotIn(word, json.dumps(r, ensure_ascii=False))

	def test_engine_settings_are_refused_to_hr_user(self):
		"""Final QA (Q5): the settings screen refuses an HR User, and so do the two API reads behind it
		(the engine's provider, model, callback URL and prompt are for HR Manager and System Manager
		only, like the «AI Recruitment Settings» DocType itself)."""
		from ido_talent_ai.talent_ai.doctype.ai_recruitment_settings import ai_recruitment_settings

		email = "talentai.hr.user.only@example.com"
		if not frappe.db.exists("User", email):
			u = frappe.get_doc({"doctype": "User", "email": email, "first_name": "HR User", "send_welcome_email": 0, "roles": [{"role": "HR User"}]})
			u.insert()
		try:
			frappe.set_user(email)
			self.assertFalse(frappe.has_permission("AI Recruitment Settings", "read"))
			with self.assertRaises(frappe.PermissionError):
				api.engine_settings()
			with self.assertRaises(frappe.PermissionError):
				ai_recruitment_settings.refresh_from_engine()
			frappe.set_user("hr.manager@example.com")
			self.assertIn("available", api.engine_settings())
		finally:
			frappe.set_user("Administrator")

	def test_empty_cv_file_is_refused_with_a_clear_message(self):
		"""Final QA (Q6): a 0-byte CV was saved as «no CV» without a word; now the form refuses it like a
		wrong type, and the applicant can send the right file (nothing is saved with a bad file)."""
		from io import BytesIO
		from types import SimpleNamespace

		from werkzeug.datastructures import FileStorage

		email = "empty.cv@example.com"
		frappe.local.form_dict = frappe._dict({
			"job_title": self.opening, "applicant_name": "متقدم تجريبي", "email_id": email, "nationality": "Saudi Arabia",
			"id_type": "هوية وطنية", "national_id": "1000088009", "date_of_birth": "1995-01-01", "height_cm": 180,
			"ai_consent": 1, "answers": json.dumps({"years_sup": 3, "licence": "سارية"}, ensure_ascii=False),
		})
		frappe.local.request = SimpleNamespace(files={"cv": FileStorage(BytesIO(b""), filename="cv.pdf")}, method="POST")
		try:
			with patch.object(frappe, "enqueue"):
				res = api.apply.__wrapped__() if hasattr(api.apply, "__wrapped__") else api.apply()
		finally:
			frappe.local.request = None
		self.assertFalse(res["ok"])
		self.assertTrue(any("فارغ" in e for e in res["errors"]), res)
		self.assertFalse(frappe.db.exists("Job Applicant", {"email_id": email}))

	def test_engine_5xx_is_the_plain_sentence_for_hr(self):
		"""Final QA (Q9): an engine 5xx (e.g. 503 «queue unavailable» while its Redis restarts) reached
		HR's red bar as «خطأ في محرك الذكاء 503: queue unavailable, try again»; now it is the same plain
		sentence as an unreachable engine, and the hourly retry recognises it."""
		from ido_talent_ai import engine

		resp = MagicMock(status_code=503, text="queue unavailable")
		resp.json.return_value = {"detail": "queue unavailable, try again"}
		with patch("requests.request", return_value=resp):
			with self.assertRaises(engine.EngineUnavailable) as ctx:
				engine.call("POST", "/v1/screenings", json={})
		self.assertEqual(str(ctx.exception), engine.UNAVAILABLE_MESSAGE)
		for word in ("503", "queue", "error"):
			self.assertNotIn(word, str(ctx.exception))

	def test_failed_score_shows_a_dash_in_the_list(self):
		"""Final QA (Q3): a failed screening keeps ai_score 0 in the database (the column is NOT NULL), but
		the applicant list shows «—» instead of a score of 0."""
		import os

		js = open(os.path.join(os.path.dirname(__file__), "..", "public", "js", "job_applicant_list.js"), encoding="utf-8").read()
		self.assertIn('if (doc.ai_status === "Failed") return `<span class="text-muted">—</span>`;', js)
		# inside the ai_score formatter, before the number is drawn
		start = js.index("ai_score(value, df, doc) {")
		self.assertLess(start, js.index('doc.ai_status === "Failed"'))
		self.assertLess(js.index('doc.ai_status === "Failed"'), js.index("T.fmt1(value)", start))

	def test_engine_failure_result_marks_the_application_failed(self):
		"""Round 12: the engine's signed «failed» result (sent after its last attempt) makes the
		application «Failed» with the red bar and «إعادة المحاولة», in plain Arabic; the technical
		reason goes to the error log only."""
		res, _ = self._apply("a12.enginefail@example.com", {"years_sup": 3, "licence": "سارية"})
		doc = frappe.get_doc("Job Applicant", res["reference"])
		a = screening._assessment_for(doc)
		a.engine_screening_id = "scr_test_fail_12"
		a.save()
		job = frappe.get_doc({"doctype": "AI Recruitment Job", "reference_doctype": "Job Applicant", "reference_name": doc.name,
							  "job_opening": doc.job_title, "job_type": "Screening", "status": "Running", "attempts": 1, "max_attempts": 3,
							  "engine_screening_id": "scr_test_fail_12"}).insert(ignore_permissions=True)
		before = frappe.db.count("Error Log")
		self._complete(doc.name, status="failed", error="LLMOutputError: candidate_profile: invalid JSON after repair", score=None, criteria=[])
		self.assertEqual(frappe.db.get_value("Job Applicant", doc.name, "ai_status"), "Failed")
		self.assertEqual(flt(frappe.db.get_value("Job Applicant", doc.name, "ai_score")), 0)
		job.reload()
		self.assertEqual(job.status, "Failed")
		self.assertEqual(job.error_message, screening.ENGINE_FAILED_MESSAGE)
		for word in ("LLMOutputError", "Traceback", "Error"):
			self.assertNotIn(word, job.error_message)
		self.assertGreater(frappe.db.count("Error Log"), before)  # the technical reason is logged

	def test_free_text_answer_never_carries_the_applicant_name(self):
		"""Final QA: a free answer that mentions the applicant's own name is sent to the engine
		with the name replaced (the engine redacts phones, e-mails and IDs itself, not this name)."""
		res, _ = self._apply("a13.name@example.com", {"years_sup": 2, "licence": "سارية", "last_job": "أنا متقدم تجريبي، مشرف وردية منذ 2019 وأتابع 8 حراس"})
		doc = frappe.get_doc("Job Applicant", res["reference"])
		payload = screening.candidate_payload(doc)
		txt = payload["answers"].get("last_job") or ""
		self.assertNotIn("متقدم تجريبي", txt)
		self.assertIn("[الاسم]", txt)
		self.assertIn("منذ 2019 وأتابع 8 حراس", txt)  # the evidence stays
		self.assertEqual(screening.strip_own_name("مشرف أمن في بنك", "ماجد الشهراني"), "مشرف أمن في بنك")
		self.assertEqual(screening.strip_own_name("اسمي ماجد الشهراني والشهراني لقبي", "ماجد الشهراني"), "اسمي [الاسم] [الاسم] [الاسم] لقبي")

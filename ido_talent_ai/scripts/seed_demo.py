"""Demo setup on a local development site (synthetic data only). Never run on a client site.

	bench --site talent.localhost execute ido_talent_ai.scripts.seed_demo.setup \
		--kwargs '{"engine_url": "http://api:8000", "api_key": "...", "passwords": {...}}'

Creates the company (setup wizard), HR users, the designation template profile, the opening
«مشرف أمن — الرياض» with its approved AI Job Profile, and connects AI Recruitment Settings to the
engine. Applicants are not created here: `submit_demo_applications.py` sends them through the
public form endpoint, like a browser would."""

from __future__ import annotations

import json
import os

import frappe
from frappe.utils import add_days, getdate, nowdate

DATA = os.path.join(os.path.dirname(__file__), "demo_data.json")
CONSENT_AR = (
	"أوافق على معالجة بياناتي وإجاباتي وسيرتي الذاتية لغرض التوظيف، بما في ذلك الفرز الآلي المساعد الذي يراجعه "
	"موظف مختص، ووفق نظام حماية البيانات الشخصية. يمكنني سحب الموافقة أو طلب حذف بياناتي."
)
USERS = {
	"hr.manager@example.com": ("مديرة الموارد البشرية", ["HR Manager", "HR User", "Employee"]),
	"hr.user@example.com": ("أخصائي التوظيف", ["HR User", "Employee"]),
	"employee@example.com": ("موظف بدون صلاحيات توظيف", ["Employee"]),
}


def load() -> dict:
	with open(DATA, encoding="utf-8") as f:
		return json.load(f)


def _guard() -> None:
	if not frappe.conf.get("developer_mode"):
		frappe.throw("seed_demo runs only on a developer-mode site (synthetic demo data).")


def ensure_setup(data: dict) -> str:
	company = data["company"]["name"]
	if frappe.db.exists("Company", company):
		return company
	if not frappe.is_setup_complete():
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

		year = getdate(nowdate()).year
		setup_complete(
			{
				"language": "English",
				"country": "Saudi Arabia",
				"timezone": "Asia/Riyadh",
				"currency": "SAR",
				"full_name": "Talent AI Admin",
				"email": "admin.talentai@example.com",
				"company_name": company,
				"company_abbr": data["company"]["abbr"],
				"chart_of_accounts": "Standard",
				"fy_start_date": f"{year}-01-01",
				"fy_end_date": f"{year}-12-31",
				"setup_demo": 0,
			}
		)
		frappe.db.commit()
	if not frappe.db.exists("Company", company):
		frappe.get_doc(
			{"doctype": "Company", "company_name": company, "abbr": data["company"]["abbr"], "country": "Saudi Arabia", "default_currency": "SAR"}
		).insert(ignore_permissions=True)
	return company


def ensure_locale() -> None:
	ss = frappe.get_single("System Settings")
	ss.language = "ar"
	ss.time_zone = "Asia/Riyadh"
	ss.country = "Saudi Arabia"
	ss.flags.ignore_mandatory = True
	ss.save(ignore_permissions=True)


def fix_scheduler_times() -> int:
	"""Jobs registered before the site switched to Asia/Riyadh carry a creation time in the future
	(the default zone was ahead), so the scheduler would skip them for hours. Bring them to now."""
	from frappe.utils import now_datetime

	now = now_datetime()
	names = frappe.get_all("Scheduled Job Type", filters={"creation": [">", now], "last_execution": ["is", "not set"]}, pluck="name")
	for n in names:
		frappe.db.set_value("Scheduled Job Type", n, "creation", now, update_modified=False)
	return len(names)


def ensure_users(passwords: dict) -> None:
	from frappe.utils.password import update_password

	for email, (full_name, roles) in USERS.items():
		if not frappe.db.exists("User", email):
			u = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": full_name, "language": "ar", "send_welcome_email": 0, "user_type": "System User"}
			)
			u.insert(ignore_permissions=True)
		u = frappe.get_doc("User", email)
		u.add_roles(*roles)
		if passwords.get(email):
			update_password(email, passwords[email])


def ensure_settings(engine_url: str, api_key: str | None, callback_url: str | None) -> None:
	s = frappe.get_single("AI Recruitment Settings")
	s.enabled = 1
	s.auto_screen_on_apply = 1
	s.engine_url = engine_url
	if api_key:
		s.api_key = api_key
	s.request_timeout = 60
	if callback_url:
		s.callback_url = callback_url
	s.allowed_facts = "nationality\nage\nheight_cm\nweight_kg"
	s.retention_days = s.retention_days or 365
	s.consent_version = s.consent_version or "v1"
	s.consent_text = s.consent_text or CONSENT_AR
	s.save(ignore_permissions=True)


def _profile_rows(doc, p: dict) -> None:
	doc.set("criteria", [])
	doc.set("rules", [])
	doc.set("questions", [])
	for c in p["criteria"]:
		doc.append("criteria", c)
	for r in p["rules"]:
		doc.append("rules", r)
	for q in p["questions"]:
		doc.append("questions", q)


def ensure_template(data: dict) -> str:
	from ido_talent_ai.profile import approve

	if not frappe.db.exists("Designation", data["designation"]):
		frappe.get_doc({"doctype": "Designation", "designation_name": data["designation"]}).insert(ignore_permissions=True)

	name = frappe.db.get_value("AI Job Profile", {"is_template": 1, "designation": data["designation"]})
	if name:
		return name
	doc = frappe.get_doc(
		{"doctype": "AI Job Profile", "is_template": 1, "designation": data["designation"], "title": f"قالب {data['designation']}",
		 "description": data["profile"]["description"], "status": "Draft"}
	)
	_profile_rows(doc, data["profile"])
	doc.insert(ignore_permissions=True)
	approve(doc.name)
	return doc.name


def ensure_opening(data: dict, company: str, o: dict | None = None) -> str:
	o = o or data["opening"]
	name = frappe.db.get_value("Job Opening", {"job_title": o["job_title"]})
	if name:
		return name
	if not frappe.db.exists("Branch", o["location"]):
		frappe.get_doc({"doctype": "Branch", "branch": o["location"]}).insert(ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Job Opening",
			"job_title": o["job_title"],
			"company": company,
			"designation": data["designation"],
			"status": "Open",
			"publish": 1,
			"route": o.get("route") or "jobs/security/security-supervisor-riyadh",
			"description": f"<p>{o['description']}</p>",
			"location": o["location"],
			"closes_on": add_days(nowdate(), 60),
			"vacancies": 5,
			"ai_enabled": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_profile(opening: str, template: str, data: dict, title: str | None = None) -> str:
	from ido_talent_ai.profile import approve, copy_from_template

	name = frappe.db.get_value("AI Job Profile", {"job_opening": opening})
	if not name:
		doc = frappe.get_doc(
			{"doctype": "AI Job Profile", "job_opening": opening, "title": title or data["opening"]["job_title"], "designation": data["designation"], "status": "Draft"}
		).insert(ignore_permissions=True)
		name = doc.name
		copy_from_template(name, template)
	if not frappe.db.get_value("AI Job Profile", name, "version"):
		approve(name)
	return name


def setup(engine_url: str = "http://api:8000", api_key: str | None = None, callback_url: str | None = None, passwords: dict | None = None) -> dict:
	_guard()
	frappe.set_user("Administrator")
	data = load()
	company = ensure_setup(data)
	ensure_locale()
	fix_scheduler_times()
	ensure_users(passwords or {})
	ensure_settings(engine_url, api_key, callback_url)
	template = ensure_template(data)
	opening = ensure_opening(data, company)
	profile = ensure_profile(opening, template, data)
	frappe.db.commit()
	out = {"company": company, "opening": opening, "profile": profile, "template": template,
		   "apply_url": f"/ai-apply/new?job_title={opening}"}
	print(json.dumps(out, ensure_ascii=False))
	return out


def company_only() -> str:
	"""Complete the setup wizard only (used to prepare the automated-test site)."""
	_guard()
	frappe.set_user("Administrator")
	company = ensure_setup(load())
	frappe.db.commit()
	return company


def rescore_all(opening: str) -> dict:
	"""Dev helper: push every applicant of the opening to the engine first (so application times and
	duplicates are known), then queue a forced re-score for each, oldest application first."""
	_guard()
	frappe.set_user("Administrator")
	from ido_talent_ai.screening import db_retry, queue_screening, sync_candidate

	names = frappe.get_all("Job Applicant", filters={"job_title": opening}, order_by="creation asc", pluck="name")
	for n in names:
		sync_candidate(n)
	frappe.db.commit()
	for n in names:
		db_retry(queue_screening, n, "Rescreen", force=True)
	return {"queued": len(names)}


def second_opening() -> dict:
	"""A second opening of the same designation (Jeddah): its ranking is separate (acceptance A5)
	and its talent pool search finds the Riyadh applicants (feature 13)."""
	_guard()
	frappe.set_user("Administrator")
	data = load()
	company = ensure_setup(data)
	template = ensure_template(data)
	o = {"job_title": "مشرف أمن — جدة", "location": "جدة", "route": "jobs/security/security-supervisor-jeddah",
		 "description": data["opening"]["description"]}
	opening = ensure_opening(data, company, o)
	profile = ensure_profile(opening, template, data, title=o["job_title"])
	frappe.db.commit()
	return {"opening": opening, "profile": profile}


def pool_cases() -> dict:
	"""Dev demo only: one applicant withdraws consent and one application is made to look old
	(retention ended), so the talent pool shows both exclusions."""
	_guard()
	frappe.set_user("Administrator")
	from ido_talent_ai.api import withdraw_consent
	from ido_talent_ai.screening import sync_candidate

	withdrawn = "applicant.2014@example.com"
	old = "applicant.2019@example.com"
	if frappe.db.get_value("Job Applicant", withdrawn, "ai_consent"):
		withdraw_consent(withdrawn, "طلب المتقدم سحب موافقته على المعالجة (حالة تجريبية)")
	frappe.db.set_value("Job Applicant", old, "creation", "2024-09-15 10:00:00", update_modified=False)
	sync_candidate(old)
	frappe.db.commit()
	return {"consent_withdrawn": withdrawn, "retention_expired": old}

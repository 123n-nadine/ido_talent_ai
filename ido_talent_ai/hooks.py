app_name = "ido_talent_ai"
app_title = "IDO Talent AI"
app_publisher = "i-do Holding"
app_description = "AI screening and ranking for HRMS recruitment. The AI ranks and explains; HR decides."
app_email = "nadien222101510@gmail.com"
app_license = "Proprietary"

required_apps = ["frappe/erpnext", "frappe/hrms"]

# Shared UI helpers (bilingual labels, assessment and CV analysis renderers) and styles
app_include_js = ["/assets/ido_talent_ai/js/talent_ai.js"]
app_include_css = ["/assets/ido_talent_ai/css/talent_ai.css"]

# Website: eligibility sentences on the HRMS job page (no template override)
web_include_js = ["/assets/ido_talent_ai/js/talent_ai_web.js"]
web_include_css = ["/assets/ido_talent_ai/css/talent_ai_web.css"]

doctype_js = {
	"Job Applicant": "public/js/job_applicant.js",
	"Job Opening": "public/js/job_opening.js",
}
doctype_list_js = {"Job Applicant": "public/js/job_applicant_list.js"}

# HR users land on «التوظيف الذكي» (Arabic by default) after login
on_session_creation = "ido_talent_ai.utils.on_session_creation"

after_install = "ido_talent_ai.setup.install.after_install"
after_migrate = "ido_talent_ai.setup.install.after_migrate"
before_uninstall = "ido_talent_ai.setup.install.before_uninstall"

doc_events = {
	"Job Applicant": {
		"after_insert": "ido_talent_ai.screening.on_applicant_insert",
		"on_update": "ido_talent_ai.screening.on_applicant_update",
		"on_trash": "ido_talent_ai.screening.on_applicant_trash",
	},
	"Job Opening": {
		"validate": "ido_talent_ai.screening.on_opening_validate",
		"on_trash": "ido_talent_ai.screening.on_opening_trash",
	},
}

scheduler_events = {
	"cron": {"*/2 * * * *": ["ido_talent_ai.screening.sync_running_jobs", "ido_talent_ai.screening.queue_missing"]},
	"hourly": ["ido_talent_ai.screening.retry_failed_jobs"],
}

# Never touch HRMS code: everything is DocTypes, custom fields (created in setup.install), hooks and pages.

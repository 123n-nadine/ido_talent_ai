# ido_talent_ai

Frappe app that adds AI screening and ranking to the recruitment module of Frappe HRMS. It adds DocTypes, custom fields, an application web form, hooks and HR screens, and talks to the standalone `talent-engine` over HTTP. The platform's own code (frappe, erpnext, hrms) is never modified.

Install:

```
bench get-app <this repo url>
bench --site <site> install-app ido_talent_ai
bench --site <site> migrate
```

Deployment steps, settings and upgrades: `docs/DEPLOY.md` in the workspace repository (`talent-ai`). Tests: `bench --site <test site> run-tests --app ido_talent_ai` (keep the scheduler of the test site disabled).

DocTypes (client names): AI Recruitment Settings, AI Job Profile, AI Job Criterion, AI Candidate Assessment, AI Assessment Evidence, AI Recruitment Job, AI Recruitment Audit Log.

No consent, no AI (OPEN_QUESTIONS #20 and #21, defaults until the client confirms):

- An application saved without consent (a paper form entered by HR in the desk) is kept but never sent to the engine. Its AI status is «بانتظار الموافقة»; HR records the consent with its source («تسجيل الموافقة», `api.record_consent`), and the screening starts by itself.
- «سحب موافقة المعالجة» (`api.withdraw_consent`) takes the applicant out of the ranking at once, into «مستبعد: سحب الموافقة» with no score; the engine erases what the AI made of the application and Frappe drops its copy (assessment, evidence, AI fields). The application stays.

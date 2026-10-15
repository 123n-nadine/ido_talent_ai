# ido_talent_ai

Frappe app that adds AI screening and ranking to the recruitment module of Frappe HRMS. It adds DocTypes, custom fields, an application web form, hooks and HR screens, and talks to the standalone `talent-engine` over HTTP. The platform's own code (frappe, erpnext, hrms) is never modified.

Install (later):

```
bench get-app <this repo url>
bench --site <site> install-app ido_talent_ai
bench --site <site> migrate
```

Status: Phase 0 (repository created). The app skeleton is built in Phase 6; see `docs/PLAN.md` in the workspace.

DocTypes (client names): AI Recruitment Settings, AI Job Profile, AI Job Criterion, AI Candidate Assessment, AI Assessment Evidence, AI Recruitment Job, AI Recruitment Audit Log.

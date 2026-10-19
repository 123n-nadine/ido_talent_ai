# Copyright (c) 2026, i-do Holding
"""AI Recruitment Settings. Provider, model, OCR, timeout, retries and the judge prompt are owned
by the engine (decision 13): this form reads them from /v1/settings and writes changes back."""

import frappe
from frappe.model.document import Document
from frappe.utils import cint, get_url, now_datetime

ENGINE_FIELDS = ("provider", "model", "ocr_provider", "timeout", "max_retries", "judge_prompt")


class AIRecruitmentSettings(Document):
	def on_update(self):
		if self.flags.get("talent_ai_local_only") or self.flags.get("talent_ai_from_engine"):
			return
		if not self.engine_url or not self.get_password("api_key", raise_exception=False):
			return
		from ido_talent_ai import engine

		before = self.get_doc_before_save()
		body = {}
		mapping = {"provider": "ai_provider", "model": "ai_model", "ocr_provider": "ocr_provider",
				   "timeout": "llm_timeout_s", "max_retries": "max_retries", "judge_prompt": "judge_prompt"}
		for f, key in mapping.items():
			if before is None or self.get(f) != before.get(f):
				if self.get(f) not in (None, "", 0):
					body[key] = cint(self.get(f)) if f in ("timeout", "max_retries") else self.get(f)
		facts = [x.strip() for x in (self.allowed_facts or "").splitlines() if x.strip()]
		body["allowed_facts"] = facts
		body["retention_days"] = cint(self.retention_days) or None
		body["callback_url"] = self.callback_url or get_url("/api/method/ido_talent_ai.api.receive_result")
		secret = self.get_password("callback_secret", raise_exception=False)
		if secret:
			body["callback_secret"] = secret
		body = {k: v for k, v in body.items() if v is not None}
		try:
			res = engine.put("/v1/settings", json=body)
		except engine.EngineError as e:
			frappe.throw(frappe._("The engine refused the settings: {0}").format(e))
		self.flags.talent_ai_from_engine = True
		self._copy_from_engine(res)

	def _copy_from_engine(self, res: dict):
		vals = {
			"provider": res.get("ai_provider"), "model": res.get("ai_model"), "ocr_provider": res.get("ocr_provider"),
			"timeout": res.get("llm_timeout_s"), "max_retries": res.get("max_retries"),
			"judge_prompt": res.get("judge_prompt"), "last_synced": now_datetime(),
		}
		for k, v in vals.items():
			if v is not None:
				frappe.db.set_single_value("AI Recruitment Settings", k, v)
		frappe.clear_document_cache("AI Recruitment Settings", "AI Recruitment Settings")


@frappe.whitelist()
def refresh_from_engine() -> dict:
	from ido_talent_ai import engine
	from ido_talent_ai.utils import require_settings_access

	require_settings_access()
	res = engine.get("/v1/settings")
	frappe.get_single("AI Recruitment Settings")._copy_from_engine(res)
	return {"settings": res, "health": engine.health()}

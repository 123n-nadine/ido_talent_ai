"""HTTP client for talent-engine. All engine traffic goes through here (server side only).

The API key lives in AI Recruitment Settings (Password field) and never reaches the browser."""

from __future__ import annotations

import time
from typing import Any

import frappe
import requests
from frappe import _

from ido_talent_ai.utils import get_settings


class EngineError(Exception):
	"""The engine answered with an error (4xx/5xx)."""

	def __init__(self, message: str, status: int | None = None, payload: Any = None):
		super().__init__(message)
		self.status = status
		self.payload = payload


class EngineUnavailable(EngineError):
	"""The engine could not be reached (connection refused, DNS, timeout)."""


def _base() -> tuple[str, dict[str, str], int]:
	s = get_settings()
	url = (s.engine_url or "").rstrip("/")
	if not url:
		raise EngineUnavailable(_("Engine URL is not configured in AI Recruitment Settings"))
	key = s.get_password("api_key", raise_exception=False) or ""
	actor = frappe.session.user if getattr(frappe, "session", None) and frappe.session.user else "system"
	headers = {"Authorization": f"Bearer {key}", "X-Talent-Actor": actor[:140]}
	return url, headers, int(s.request_timeout or 30)


def call(
	method: str,
	path: str,
	json: Any = None,
	files: dict | None = None,
	data: dict | None = None,
	params: dict | None = None,
	timeout: int | None = None,
	raw: bool = False,
) -> Any:
	url, headers, default_timeout = _base()
	t0 = time.time()
	try:
		resp = requests.request(
			method,
			url + path,
			json=json,
			files=files,
			data=data,
			params=params,
			headers=headers,
			timeout=timeout or default_timeout,
		)
	except (requests.ConnectionError, requests.Timeout) as e:
		raise EngineUnavailable(_("Could not reach the AI engine: {0}").format(type(e).__name__)) from e
	if resp.status_code >= 400:
		try:
			payload = resp.json()
			detail = payload.get("detail") if isinstance(payload, dict) else payload
		except ValueError:
			payload, detail = None, resp.text[:300]
		if resp.status_code >= 500:
			raise EngineUnavailable(_("AI engine error {0}: {1}").format(resp.status_code, detail), resp.status_code, payload)
		raise EngineError(str(detail), resp.status_code, payload)
	frappe.local.talent_ai_last_call_ms = int((time.time() - t0) * 1000)
	if raw:
		return resp
	if not resp.content:
		return None
	return resp.json()


def get(path: str, **kw) -> Any:
	return call("GET", path, **kw)


def put(path: str, **kw) -> Any:
	return call("PUT", path, **kw)


def post(path: str, **kw) -> Any:
	return call("POST", path, **kw)


def delete(path: str, **kw) -> Any:
	return call("DELETE", path, **kw)


def health() -> dict:
	"""Engine readiness for the settings screen (never raises)."""
	try:
		url, _h, _t = _base()
		r = requests.get(url + "/ready", timeout=5)
		return {"ok": r.status_code == 200, "status": r.status_code, "body": r.json()}
	except Exception as e:
		return {"ok": False, "error": f"{type(e).__name__}: {e}"}

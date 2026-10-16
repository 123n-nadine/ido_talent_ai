#!/usr/bin/env python3
"""Submit the 25 synthetic applicants of demo_data.json through the public application endpoint,
exactly as the browser form at /ai-apply/new does (multipart POST, optional CV file).

	python3 submit_demo_applications.py --url http://127.0.0.1:18050 --host talent.localhost \
		--opening HR-OPN-2026-0001 --cvs ../../../talent-engine/data/cvs [--only 2001,2002] [--delay 1]

Development use only, against a local bench. Fictional data."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.request
import uuid
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))


def dob_for(age: int) -> str:
	today = date.today()
	d = today.replace(year=today.year - int(age)) - timedelta(days=120)
	return d.isoformat()


def multipart(fields: dict, file: tuple[str, bytes] | None) -> tuple[bytes, str]:
	boundary = "----talentai" + uuid.uuid4().hex
	out = bytearray()
	for k, v in fields.items():
		out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode()
		out += str(v).encode("utf-8") + b"\r\n"
	if file:
		name, content = file
		ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
		out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"cv\"; filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n".encode()
		out += content + b"\r\n"
	out += f"--{boundary}--\r\n".encode()
	return bytes(out), f"multipart/form-data; boundary={boundary}"


def submit(url: str, host: str, opening: str, a: dict, cv_dir: str | None) -> dict:
	fields = {
		"job_title": opening,
		"applicant_name": a["applicant_name"],
		"email_id": a["email_id"],
		"phone_number": a.get("phone_number") or "",
		"nationality": a["nationality"],
		"id_type": a["id_type"],
		"national_id": a["national_id"],
		"date_of_birth": dob_for(a["age"]),
		"height_cm": a.get("height_cm") or "",
		"weight_kg": a.get("weight_kg") or "",
		"ai_consent": "1",
		"answers": json.dumps(a["answers"], ensure_ascii=False),
	}
	file = None
	if a.get("cv") and cv_dir:
		path = os.path.join(cv_dir, a["cv"])
		with open(path, "rb") as f:
			file = (a["cv"], f.read())
	body, ctype = multipart(fields, file)
	req = urllib.request.Request(url.rstrip("/") + "/api/method/ido_talent_ai.api.apply", data=body, method="POST")
	req.add_header("Content-Type", ctype)
	req.add_header("Host", host)
	req.add_header("Accept", "application/json")
	try:
		with urllib.request.urlopen(req, timeout=120) as r:
			return json.loads(r.read())
	except urllib.error.HTTPError as e:
		return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:500]}


def main() -> int:
	p = argparse.ArgumentParser()
	p.add_argument("--url", default="http://127.0.0.1:18050")
	p.add_argument("--host", default="talent.localhost")
	p.add_argument("--opening", required=True)
	p.add_argument("--cvs", default=None, help="folder with the synthetic CV files (talent-engine/data/cvs)")
	p.add_argument("--only", default="", help="comma-separated last 4 digits of the demo keys")
	p.add_argument("--skip", default="", help="comma-separated last 4 digits to leave out (e.g. one submitted in a browser)")
	p.add_argument("--delay", type=float, default=1.0)
	args = p.parse_args()
	with open(os.path.join(HERE, "demo_data.json"), encoding="utf-8") as f:
		data = json.load(f)
	only = {x.strip() for x in args.only.split(",") if x.strip()}
	skip = {x.strip() for x in args.skip.split(",") if x.strip()}
	ok = 0
	for a in data["applicants"]:
		if (only and a["key"][-4:] not in only) or a["key"][-4:] in skip:
			continue
		res = submit(args.url, args.host, args.opening, a, args.cvs)
		msg = res.get("message") or {}
		good = bool(msg.get("ok"))
		ok += good
		print(f"{a['key']}  {a['applicant_name']:<22} cv={a.get('cv') or '-':<24} -> {msg.get('reference') if good else res}")
		time.sleep(args.delay)
	print(f"{ok} applications saved")
	return 0 if ok else 1


if __name__ == "__main__":
	sys.exit(main())

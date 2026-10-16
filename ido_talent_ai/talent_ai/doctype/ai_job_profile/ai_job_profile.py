# Copyright (c) 2026, i-do Holding
import frappe
from frappe.model.document import Document

from ido_talent_ai.profile import content_hash, validate_profile


class AIJobProfile(Document):
	def validate(self):
		validate_profile(self)
		if self.flags.get("talent_ai_approving") or self.flags.get("talent_ai_keep_status"):
			return
		if self.status == "Approved" and self.versions:
			last = sorted(self.versions, key=lambda r: r.version)[-1]
			if last.content_hash and last.content_hash != content_hash(self):
				self.status = "Draft"  # an edit after approval is a draft of the next version
		if self.job_opening and frappe.db.exists(
			"AI Job Profile", {"job_opening": self.job_opening, "name": ["!=", self.name]}
		):
			frappe.throw(frappe._("This Job Opening already has an AI Job Profile."))

// AI Candidate Assessment is written by the integration only; the readable view is on the Job Applicant.
frappe.ui.form.on("AI Candidate Assessment", {
	refresh(frm) {
		const T = talent_ai;
		frm.disable_save();
		frm.set_intro(T.t("هذا السجل يكتبه الذكاء الاصطناعي ولا يُعدَّل يدويًا. العرض الكامل مع الأدلة في صفحة المتقدم.", "Written by the AI integration, never edited by hand. The full view with evidence is on the applicant page.") + " " + T.t(T.DISCLAIMER.ar, T.DISCLAIMER.en), "blue");
		if (frm.doc.job_applicant) frm.add_custom_button(T.t("فتح المتقدم", "Open applicant"), () => frappe.set_route("Form", "Job Applicant", frm.doc.job_applicant));
	},
});

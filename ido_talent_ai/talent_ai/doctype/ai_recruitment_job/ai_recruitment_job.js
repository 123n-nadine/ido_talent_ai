// AI Recruitment Job: attempts, error and a retry button for failed jobs.
frappe.ui.form.on("AI Recruitment Job", {
	refresh(frm) {
		const T = talent_ai;
		if (frm.doc.status === "Failed" && frm.doc.reference_name) {
			frm.add_custom_button(T.t("إعادة المحاولة", "Retry"), () =>
				frappe.xcall("ido_talent_ai.api.retry_job", { job: frm.doc.name }).then((r) => frappe.set_route("Form", "AI Recruitment Job", r.job))
			).addClass("btn-primary");
		}
		if (frm.doc.reference_name) {
			frm.add_custom_button(T.t("فتح المتقدم", "Open applicant"), () => frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name));
		}
	},
});

// Talent AI on the Job Opening form: create/open the AI Job Profile, the public form link and the
// links to the ranking, the batch monitor and the talent pool of this opening.
frappe.ui.form.on("Job Opening", {
	refresh(frm) {
		if (frm.is_new() || !frm.fields_dict.ai_links) return;
		const T = talent_ai;
		const t = T.t;
		const grp = "Talent AI";
		if (frm.doc.ai_profile) {
			frm.add_custom_button(t("ملف المعايير", "Criteria profile"), () => frappe.set_route("Form", "AI Job Profile", frm.doc.ai_profile), grp);
		} else if (frm.doc.ai_enabled) {
			frm.add_custom_button(t("إنشاء ملف المعايير", "Create criteria profile"), () => talent_ai_opening.create_profile(frm), grp);
		}
		if (frm.doc.ai_enabled) {
			frm.add_custom_button(t("ترتيب المتقدمين", "Ranking"), () => frappe.set_route("ai-ranking", { opening: frm.doc.name }), grp);
			frm.add_custom_button(t("متابعة المعالجة", "Batch monitor"), () => frappe.set_route("ai-batch", { opening: frm.doc.name }), grp);
			frm.add_custom_button(t("بنك المتقدمين", "Talent pool"), () => frappe.set_route("ai-talent-pool", { opening: frm.doc.name }), grp);
		}
		talent_ai_opening.links(frm);
	},
	ai_enabled(frm) {
		talent_ai_opening.links(frm);
	},
});

const talent_ai_opening = {
	create_profile(frm) {
		frappe.db
			.get_list("AI Job Profile", { filters: { job_opening: frm.doc.name }, fields: ["name"], limit: 1 })
			.then((rows) => {
				if (rows.length) return frappe.set_route("Form", "AI Job Profile", rows[0].name);
				frappe.new_doc("AI Job Profile", { job_opening: frm.doc.name, title: frm.doc.job_title, designation: frm.doc.designation });
			});
	},

	links(frm) {
		const T = talent_ai;
		const t = T.t;
		const $w = frm.fields_dict.ai_links.$wrapper;
		if (!frm.doc.ai_enabled) return $w.html("");
		const apply = `/ai-apply/new?job_title=${encodeURIComponent(frm.doc.name)}`;
		const state = frm.doc.ai_profile_approved
			? `<span class="chip green"><span class="dot"></span>${t("المعايير معتمدة — التقديم مفتوح", "Criteria approved — applications open")}</span>`
			: `<span class="chip amber"><span class="dot"></span>${t("لا يبدأ الفرز قبل اعتماد ملف المعايير", "Screening starts only after the profile is approved")}</span>`;
		$w.html(`<div class="tai"><div style="display:flex;flex-direction:column;gap:6px">${state}
			${frm.doc.ai_profile_approved ? `<div class="hint">${t("رابط التقديم العام", "Public application link")}: <a href="${apply}" target="_blank">${apply}</a></div>` : ""}
			<div class="hint">${t("الذكاء يرتّب ويشرح فقط، والقرار دائمًا لـ HR.", "The AI ranks and explains only; HR always decides.")}</div></div></div>`);
	},
};

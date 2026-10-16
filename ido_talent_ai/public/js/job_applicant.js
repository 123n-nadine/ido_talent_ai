// Talent AI on the Job Applicant form: the AI section (HR only), HR decision buttons with a
// mandatory reason, criterion override, re-score / retry, CV analysis, live updates.
frappe.ui.form.on("Job Applicant", {
	setup(frm) {
		frm._tai = { hilite: null };
	},

	refresh(frm) {
		// the AI section is at permission level 1: only HR Manager / HR User (and System Manager) read it
		if (frm.is_new() || !frm.fields_dict.ai_html || !(frm.perm[1] && frm.perm[1].read)) return;
		talent_ai_form.listen(frm);
		talent_ai_form.load(frm);
		talent_ai_form.buttons(frm);
	},
});

const talent_ai_form = {
	listen(frm) {
		if (frm._tai_listening) return;
		frm._tai_listening = true;
		frappe.realtime.on("talent_ai_update", (d) => {
			if (!d || d.applicant !== frm.doc.name || frm.doctype !== "Job Applicant") return;
			// fields written by the AI never mark the form dirty: reload quietly unless the user is editing
			if (frm.is_dirty()) talent_ai_form.load(frm);
			else frm.reload_doc();
		});
	},

	buttons(frm) {
		const T = talent_ai;
		const t = T.t;
		// HRMS's own Reject / Shortlist change the status without a reason; with Talent AI the
		// decision goes through the buttons below (reason + decision maker, audited)
		setTimeout(() => ["Reject", "Shortlist", __("Reject"), __("Shortlist")].forEach((b) => frm.remove_custom_button(b)), 0);
		const grp = t("القرار", "Decision");
		[["Shortlisted", t("ترشيح للمقابلة", "Shortlist")], ["Hold", t("تعليق", "Hold")], ["Rejected", t("رفض", "Reject")]].forEach(([st, label]) =>
			frm.add_custom_button(label, () => talent_ai_form.decide(frm, st), grp)
		);
		if (frm.doc.ai_candidate_ref) {
			frm.add_custom_button(t("إعادة التقييم", "Re-score"), () => talent_ai_form.rescreen(frm), "Talent AI");
		}
		if (frm.doc.ai_assessment) {
			frm.add_custom_button(t("تحليل السيرة", "CV analysis"), () => T.openCvAnalysis(frm.doc.name), "Talent AI");
		}
		if (frm.doc.job_title) {
			frm.add_custom_button(t("ترتيب الشاغر", "Opening ranking"), () => frappe.set_route("ai-ranking", { opening: frm.doc.job_title }), "Talent AI");
		}
	},

	load(frm) {
		const T = talent_ai;
		const $w = frm.fields_dict.ai_html.$wrapper;
		if (!$w.children().length) $w.html(`<div class="tai"><span class="spin"></span> ${T.t("جارٍ التحميل…", "Loading…")}</div>`);
		T.call("get_assessment", { applicant: frm.doc.name })
			.then((d) => {
				frm._tai.data = d;
				talent_ai_form.draw(frm);
			})
			.catch(() => $w.html(""));
	},

	draw(frm) {
		const T = talent_ai;
		const d = frm._tai.data;
		const $w = frm.fields_dict.ai_html.$wrapper;
		T.hiliteKey = frm._tai.hilite;
		$w.html(T.assessmentHtml(d) + (d.engine_offline ? `<div class="tai"><div class="note">${T.t("المحرك غير متاح الآن — تُعرض آخر نتيجة محفوظة.", "The engine is offline — showing the last saved result.")}</div></div>` : ""));
		$w.off("click.tai").on("click.tai", "[data-tai]", (e) => {
			const el = e.currentTarget.dataset;
			if (el.tai === "decide") talent_ai_form.decide(frm, el.status);
			else if (el.tai === "rescreen") talent_ai_form.rescreen(frm);
			else if (el.tai === "retry") talent_ai_form.retry(frm, el.job);
			else if (el.tai === "override") talent_ai_form.override(frm, el.key, el.text, Number(el.level));
			else if (el.tai === "cv") T.openCvAnalysis(frm.doc.name);
			else if (el.tai === "hilite") {
				frm._tai.hilite = frm._tai.hilite === el.key ? null : el.key;
				talent_ai_form.draw(frm);
				const m = document.getElementById("tai-q-" + el.key);
				if (m) m.scrollIntoView({ behavior: "smooth", block: "center" });
			}
		});
	},

	decide(frm, status) {
		const T = talent_ai;
		const label = T.L(T.STATUS[status]);
		T.reason_dialog(T.t(`تغيير الحالة إلى «${label}»`, `Change status to “${label}”`), (v) =>
			T.call("decide", { applicant: frm.doc.name, status, reason: v.reason }).then(() => {
				frappe.show_alert({ message: T.t("تم حفظ القرار وتسجيله", "Decision saved and logged"), indicator: "green" });
				frm.reload_doc();
			})
		);
	},

	override(frm, key, text, current) {
		const T = talent_ai;
		const d = T.reason_dialog(
			T.t(`إلغاء حكم الذكاء: ${text}`, `Override the AI judgement: ${text}`),
			(v) =>
				T.call("override", { applicant: frm.doc.name, criterion_key: key, level: Number(v.level), reason: v.reason }).then((r) => {
					frappe.show_alert({ message: T.t(`الدرجة الجديدة ${T.fmt1(r.score)}`, `New score ${T.fmt1(r.score)}`), indicator: "green" });
					talent_ai_form.load(frm);
				}),
			[{ fieldname: "level", fieldtype: "Select", label: T.t("المستوى الجديد", "New level"), options: "0\n25\n50\n75\n100", default: String(current), reqd: 1 }]
		);
		return d;
	},

	rescreen(frm) {
		const T = talent_ai;
		frappe.confirm(T.t("إعادة تقييم هذا المتقدم بآخر نسخة معتمدة من المعايير؟", "Re-score this applicant with the latest approved criteria?"), () =>
			T.call("rescreen", { applicant: frm.doc.name }).then(() => {
				frappe.show_alert({ message: T.t("أُضيف إلى قائمة المعالجة", "Queued"), indicator: "blue" });
				frm.reload_doc();
			})
		);
	},

	retry(frm, job) {
		const T = talent_ai;
		T.call("retry_job", { job }).then(() => {
			frappe.show_alert({ message: T.t("أُعيدت المحاولة", "Retry queued"), indicator: "blue" });
			frm.reload_doc();
		});
	},
};

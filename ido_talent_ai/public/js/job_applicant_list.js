// Talent AI columns on the Job Applicant list: AI status, score, band and eligibility as chips,
// live refresh when a screening finishes. Extends the HRMS list settings instead of replacing them.
(function () {
	const base = frappe.listview_settings["Job Applicant"] || {};
	const base_onload = base.onload;
	const add = ["ai_status", "ai_score", "ai_band", "ai_eligibility", "ai_stale", "ai_rank", "ai_duplicate_of"];
	const ind = (o) => (o && o.cls ? { green: "green", amber: "orange", red: "red", blue: "blue" }[o.cls] || "gray" : "gray");
	const pill = (o, txt) => `<span class="indicator-pill ${ind(o)} filterable ellipsis"><span class="ellipsis">${txt}</span></span>`;

	frappe.listview_settings["Job Applicant"] = Object.assign({}, base, {
		// the ID is the applicant's e-mail, already in its own column; in a narrow column it read «com»
		hide_name_column: true,
		add_fields: Array.from(new Set([...(base.add_fields || []), ...add])),
		formatters: Object.assign({}, base.formatters, {
			ai_status(value, df, doc) {
				if (!value) return "";
				const T = talent_ai;
				const o = T.AIST[value];
				const stale = doc.ai_stale ? ` · ${T.t("قديم", "stale")}` : "";
				return pill(doc.ai_stale ? { cls: "grey" } : o, T.L(o) + stale);
			},
			ai_score(value, df, doc) {
				// a score only exists for a finished screening (0 is the empty value of the column);
				// a failed screening shows a dash, never its 0 (final QA)
				if (doc.ai_status === "Failed") return `<span class="text-muted">—</span>`;
				if (value == null || value === "" || !["Completed", "Needs Review"].includes(doc.ai_status)) return "";
				const T = talent_ai;
				if (doc.ai_eligibility === "not_eligible") return `<b class="text-muted">${T.fmt1(value)}</b> ${pill({ cls: "red" }, T.t("غير مستوفٍ", "not eligible"))}`;
				if (doc.ai_duplicate_of) return `<b class="text-muted">${T.fmt1(value)}</b> ${pill({ cls: "gray" }, T.t("مكرر", "duplicate"))}`;
				if (doc.ai_stale) return `<b class="text-muted">${T.fmt1(value)}</b> ${pill({ cls: "grey" }, T.t("قديم", "stale"))}`;
				const o = T.BAND[doc.ai_band];
				const rank = doc.ai_rank ? ` <span class="text-muted" title="${T.t("الترتيب", "rank")}"><bdi>#${doc.ai_rank}</bdi></span>` : "";
				return `<b>${T.fmt1(value)}</b> ${o ? pill(o, T.L(o)) : ""}${rank}`;
			},
			ai_band(value) {
				const o = talent_ai.BAND[value];
				return o ? pill(o, talent_ai.L(o)) : "";
			},
			ai_eligibility(value) {
				const o = talent_ai.ELIG[value];
				return o ? pill(o, talent_ai.L(o)) : "";
			},
		}),
		onload(listview) {
			if (base_onload) base_onload.call(this, listview);
			if (!frappe.perm.has_perm("Job Applicant", 1, "read")) return;
			// a score anywhere comes with the disclaimer
			if (!listview.$tai_note) {
				listview.$tai_note = $(`<div class="tai" style="padding:6px 15px 0"><div class="disclaimer" style="margin:0">ⓘ ${talent_ai.t(talent_ai.DISCLAIMER.ar, talent_ai.DISCLAIMER.en)}</div></div>`);
				listview.$result.before(listview.$tai_note);
			}
			listview.page.add_inner_button(talent_ai.t("ترتيب الشاغر", "Opening ranking"), () => {
				const f = (listview.filter_area.get() || []).find((x) => x[1] === "job_title" && x[2] === "=");
				frappe.set_route("ai-ranking", f ? { opening: f[3] } : {});
			});
			let timer = null;
			frappe.realtime.on("talent_ai_batch", () => {
				if (frappe.get_route_str() !== "List/Job Applicant/List") return;
				clearTimeout(timer);
				timer = setTimeout(() => listview.refresh(), 1500);
			});
		},
	});
})();

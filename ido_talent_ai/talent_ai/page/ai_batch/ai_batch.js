// Batch monitor of one opening: real counts from Job Applicant.ai_status and AI Recruitment Job,
// throughput over the last 10 minutes, recent jobs with attempts and errors. Updates live.
frappe.pages["ai-batch"].on_page_load = function (wrapper) {
	const T = talent_ai;
	const page = frappe.ui.make_app_page({ parent: wrapper, title: T.t("متابعة المعالجة", "Batch monitor"), single_column: true });
	const state = { opening: null };
	wrapper.tai = { page, state };
	T.pageSetup(page);
	const field = page.add_field({
		fieldname: "opening", fieldtype: "Link", options: "Job Opening", label: T.t("الشاغر", "Opening"),
		get_query: () => ({ filters: { ai_enabled: 1 } }),
		change() { const v = field.get_value(); if (v && v !== state.opening) { state.opening = v; load(); } },
	});
	wrapper.tai.field = field;
	page.add_inner_button(T.t("ترتيب الشاغر", "Ranking"), () => frappe.set_route("ai-ranking", { opening: state.opening }));
	page.add_inner_button(T.t("مهام الذكاء", "AI jobs"), () => frappe.set_route("List", "AI Recruitment Job", { job_opening: state.opening }));
	const $body = $(`<div class="tai" style="padding:12px 0"></div>`).appendTo(page.main);

	function load() {
		if (!state.opening) return;
		T.call("batch_status", { job_opening: state.opening }).then(draw);
	}
	wrapper.tai.load = load;

	function draw(d) {
		const t = T.t;
		const a = d.applicants || {};
		const j = d.jobs || {};
		const total = Object.values(a).reduce((x, y) => x + y, 0);
		const done = (a["Completed"] || 0) + (a["Needs Review"] || 0);
		const failed = a["Failed"] || 0;
		const proc = a["Processing"] || 0;
		const notSent = a[""] || 0;
		const pct = total ? Math.round(((done + failed) / total) * 100) : 0;
		const avg = d.avg_duration_s ? Number(d.avg_duration_s) : null;
		const perMin = d.finished_last_10_min ? d.finished_last_10_min / 10 : 0;
		const eta = proc && perMin ? Math.ceil(proc / perMin) : null;
		const kpi = (label, v, cls) => `<div class="kpi"><small>${label}</small><b class="${cls || ""}">${T.N(v)}</b></div>`;
		const jobs = (d.recent_jobs || []).map((x) => `<tr><td><a href="${frappe.utils.get_form_link("AI Recruitment Job", x.name)}">${T.esc(x.name)}</a></td><td><a href="${frappe.utils.get_form_link("Job Applicant", x.reference_name)}">${T.esc(x.applicant_name || x.reference_name)}</a></td><td>${T.esc(x.job_type)}</td><td>${T.chip({ Queued: { ar: "في الانتظار", en: "Queued", cls: "" }, Running: { ar: "قيد التشغيل", en: "Running", cls: "blue" }, Completed: { ar: "مكتمل", en: "Completed", cls: "green" }, Failed: { ar: "فشل", en: "Failed", cls: "red" }, Cancelled: { ar: "أُلغيت", en: "Cancelled", cls: "grey" } }[x.status])}</td><td class="num">${x.attempts}/${x.max_attempts || 3}</td><td class="num">${x.duration_s ? Number(x.duration_s).toFixed(1) + "s" : "—"}</td><td class="hint">${T.esc(x.error_message || "")}</td></tr>`).join("");
		$body.html(`
			<div class="page-title"><div><h1>${T.esc(d.title || state.opening)}</h1><div class="sub">${t("أرقام حقيقية من طلبات هذا الشاغر ومهام الذكاء — تتحدّث تلقائيًا", "Real counts from this opening's applications and AI jobs — updates by itself")}</div></div></div>
			<div class="kpis5">${kpi(t("كل الطلبات", "All applications"), total)}${kpi(t("جاري المعالجة", "Processing"), proc)}${kpi(t("مكتمل", "Completed"), a["Completed"] || 0)}${kpi(t("يحتاج مراجعة", "Needs review"), a["Needs Review"] || 0)}${kpi(t("فشل", "Failed"), failed)}</div>
			<div class="card"><h2>${t("التقدّم", "Progress")} <small>${T.N(done + failed)} / ${T.N(total)} (${pct}%)</small></h2><div class="progress"><i style="width:${pct}%"></i></div>
				<div class="kv" style="margin-top:10px"><small>${t("انتهى خلال آخر 10 دقائق", "Finished in the last 10 min")}</small><span class="num">${T.N(d.finished_last_10_min || 0)}</span>
				<small>${t("متوسط زمن الطلب", "Average time per application")}</small><span class="num">${avg ? avg.toFixed(1) + "s" : "—"}</span>
				<small>${t("الوقت المتبقي التقريبي", "Approximate time left")}</small><span class="num">${eta ? eta + " " + t("دقيقة", "min") : "—"}</span>
				<small>${t("لم تُرسل للذكاء", "Not sent to the AI")}</small><span class="num">${T.N(notSent)}</span>
				<small>${t("بانتظار الموافقة", "Awaiting consent")}</small><span class="num">${T.N(a["Awaiting Consent"] || 0)}</span>
				<small>${t("سحب الموافقة", "Consent withdrawn")}</small><span class="num">${T.N(a["Consent Withdrawn"] || 0)}</span>
				<small>${t("مهام الذكاء", "AI jobs")}</small><span>${Object.entries(j).map(([k, v]) => `<span class="chip">${T.esc(k)} · ${v}</span>`).join(" ") || "—"}</span></div>
				<div class="note">${t("الطلب يُحفظ فورًا حتى لو المحرك متوقف؛ المعالجة تجري في الخلفية وتُعاد المحاولة تلقائيًا (3 محاولات).", "Applications are saved at once even when the engine is down; processing runs in the background with automatic retries (3 attempts).")}</div></div>
			<div class="card"><h2>${t("آخر المهام", "Recent jobs")}</h2><div class="tscroll"><table><thead><tr><th>${t("المهمة", "Job")}</th><th>${t("المتقدم", "Applicant")}</th><th>${t("النوع", "Type")}</th><th>${t("الحالة", "Status")}</th><th>${t("المحاولات", "Attempts")}</th><th>${t("الزمن", "Time")}</th><th>${t("الخطأ", "Error")}</th></tr></thead><tbody>${jobs || `<tr><td colspan="7" class="hint">—</td></tr>`}</tbody></table></div></div>`);
	}

	let timer = null;
	frappe.realtime.on("talent_ai_batch", (d) => {
		if (frappe.get_route()[0] !== "ai-batch" || (d && d.job_opening && d.job_opening !== state.opening)) return;
		clearTimeout(timer);
		timer = setTimeout(load, 800);
	});
	setInterval(() => { if (frappe.get_route()[0] === "ai-batch" && !document.hidden) load(); }, 15000);
};

frappe.pages["ai-batch"].on_page_show = function (wrapper) {
	const opts = frappe.route_options || {};
	frappe.route_options = null;
	const s = wrapper.tai;
	if (opts.opening) { s.state.opening = opts.opening; s.field.set_value(opts.opening); s.load(); }
	else if (!s.state.opening) talent_ai.call("openings").then((rows) => { if (rows.length) { s.state.opening = rows[0].name; s.field.set_value(rows[0].name); s.load(); } });
	else s.load();
};

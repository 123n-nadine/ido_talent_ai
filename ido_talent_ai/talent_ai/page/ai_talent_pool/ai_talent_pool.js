// Feature 13 — talent pool for an opening: past applicants, hard rules first, then similarity.
// Suggestions only: nothing is moved and no status changes. Excluded applicants are listed with the reason.
frappe.pages["ai-talent-pool"].on_page_load = function (wrapper) {
	const T = talent_ai;
	const page = frappe.ui.make_app_page({ parent: wrapper, title: T.t("بنك المتقدمين", "Talent pool"), single_column: true });
	const state = { opening: null, data: null };
	wrapper.tai = { page, state };
	T.pageSetup(page);
	const field = page.add_field({
		fieldname: "opening", fieldtype: "Link", options: "Job Opening", label: T.t("الشاغر الجديد", "New opening"),
		get_query: () => ({ filters: { ai_enabled: 1 } }),
		change() { const v = field.get_value(); if (v && v !== state.opening) { state.opening = v; load(); } },
	});
	wrapper.tai.field = field;
	page.set_primary_action(T.t("بحث في بنك المتقدمين", "Search the pool"), () => load(), "search");
	page.add_inner_button(T.t("ترتيب الشاغر", "Opening ranking"), () => frappe.set_route("ai-ranking", { opening: state.opening }));
	const $body = $(`<div class="tai" style="padding:12px 0"></div>`).appendTo(page.main);
	$body.html(`<div class="card"><p class="hint">${T.t("اختر شاغرًا ثم ابحث.", "Pick an opening, then search.")}</p></div>`);

	const ELIG = (e) => T.chipElig(e);
	const REASON = { consent_withdrawn: "red", retention_expired: "red", already_applied: "grey", not_eligible: "red", duplicate: "grey" };

	function load() {
		if (!state.opening) return;
		$body.html(`<div class="card"><span class="spin"></span> ${T.t("جارٍ البحث: الشروط الإلزامية أولًا ثم التشابه…", "Searching: hard rules first, then similarity…")}</div>`);
		T.call("talent_pool", { job_opening: state.opening, limit: 30 })
			.then((d) => { state.data = d; draw(); })
			.catch((e) => $body.html(`<div class="note danger">${T.esc(e.message || e)}</div>`));
	}
	wrapper.tai.load = load;

	function draw() {
		const t = T.t;
		const d = state.data;
		const link = (x) => (x.applicant ? `<a href="${T.formUrl("Job Applicant", x.applicant)}"><b>${T.esc(x.applicant_name)}</b></a>` : `<b>${T.esc(x.applicant_name)}</b>`);
		const sug = d.suggestions.map((x, i) => {
			const p = x.previous || {};
			const pct = Math.round((x.similarity || 0) * 100);
			const why = (x.eligibility_checks || []).filter((c) => c.ok !== true).map((c) => T.mix(T.lang() === "ar" ? c.text_ar : c.text_en)).join("<br>");
			return `<div class="rankrow r4">
				<div class="pos num">${i + 1}</div>
				<div class="c-name">${link(x)}</div>
				<div class="c-prev hint">${t("تقدّم سابقًا لـ", "Applied before to")} <b>${T.esc(x.previous_opening_title || p.job_title || "—")}</b><br>${t("درجته هناك", "score there")} <b class="num">${T.fmt1(p.score)}</b> ${p.band ? T.chipBand(p.band) : ""}</div>
				<div class="c-sim"><div class="bar sim"><i style="width:${pct}%"></i></div><div class="hint">${t("تشابه", "similarity")} <b class="num">${pct}%</b></div></div>
				<div class="c-elig">${ELIG(x.eligibility)}${why ? `<div class="hint" style="margin-top:4px">${why}</div>` : ""}</div>
				${(p.strengths || []).length ? `<div class="c-str">${(p.strengths || []).slice(0, 4).map((x2) => `<span class="chip green">${T.esc(x2)}</span>`).join("")}</div>` : ""}</div>`;
		}).join("");
		const exc = d.excluded.map((x) => `<tr><td>${link(x)}</td><td><span class="chip ${REASON[x.reason] || ""}">${T.esc(T.lang() === "ar" ? x.reason_ar : x.reason_en)}</span>${(x.details || []).length ? `<div class="hint">${x.details.map(T.mix).join("<br>")}</div>` : ""}</td><td class="hint">${T.esc(x.previous_opening_title || "")}</td></tr>`).join("");
		$body.html(`
			<div class="page-title"><div><h1>${T.esc(d.opening_title)}</h1><div class="sub">${t("اقتراحات من المتقدمين السابقين", "Suggestions from past applicants")} · ${t("نموذج التشابه", "similarity model")} <code>${T.esc(d.model)}</code></div></div></div>
			<div class="note info">ⓘ ${t("اقتراح فقط: لا يُنقل أي متقدم ولا تتغيّر حالة أي طلب تلقائيًا. الشروط الإلزامية تُفحص أولًا في الكود، ثم يُرتَّب المستوفون بالتشابه بين الشاغر وملفهم المُتحقَّق منه. من سحب موافقته أو انتهت مدة الاحتفاظ ببياناته لا يُقترح أبدًا.", "Suggestions only: nobody is moved and no status changes automatically. Hard rules are checked first in code, then eligible applicants are ordered by similarity between the opening and their verified profile. Applicants who withdrew consent or whose retention ended are never suggested.")}</div>
			<div class="kpis5" style="grid-template-columns:repeat(3,minmax(0,1fr))"><div class="kpi"><small>${t("مقترحون", "Suggested")}</small><b>${T.N(d.counts.suggested)}</b></div><div class="kpi"><small>${t("مستوفون للشروط", "Meet the rules")}</small><b>${T.N(d.suggestions.filter((x) => x.eligibility === "eligible").length)}</b></div><div class="kpi"><small>${t("مستبعدون", "Excluded")}</small><b>${T.N(d.counts.excluded)}</b></div></div>
			<div class="card"><h2>${t("المقترحون", "Suggested")} <small>${t("المستوفون أولًا، ثم الأعلى تشابهًا", "eligible first, then highest similarity")}</small></h2>${sug || `<p class="hint">${t("لا اقتراحات", "No suggestions")}</p>`}
				<p class="hint">${t("نسبة التشابه تقارب بين نص الشاغر ومعاييره وبين ملف المتقدم (المعايير المُثبتة، الإجابات المنظمة، نص السيرة بعد إخفاء الهوية). ليست درجة تقييم.", "Similarity compares the opening and its criteria with the applicant's profile (proven criteria, structured answers, redacted CV text). It is not an assessment score.")}</p>${T.disclaimer()}</div>
			<details class="tai-group" ${d.excluded.length ? "open" : ""}><summary>${t("المستبعدون", "Excluded")} (${T.N(d.excluded.length)}) — ${t("مع السبب", "with the reason")}</summary>
				<table style="margin-top:8px"><thead><tr><th>${t("المتقدم", "Applicant")}</th><th>${t("سبب الاستبعاد", "Reason")}</th><th>${t("تقدّم لـ", "Applied to")}</th></tr></thead><tbody>${exc || `<tr><td colspan="3" class="hint">—</td></tr>`}</tbody></table></details>`);
	}
};

frappe.pages["ai-talent-pool"].on_page_show = function (wrapper) {
	const opts = frappe.route_options || {};
	frappe.route_options = null;
	const s = wrapper.tai;
	if (opts.opening && opts.opening !== s.state.opening) {
		s.state.opening = opts.opening;
		s.field.set_value(opts.opening);
		s.load();
	}
};

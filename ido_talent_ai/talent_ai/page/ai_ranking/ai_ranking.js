// Ranking of one opening: only completed + eligible + current + non-duplicate applications are
// ranked; everything else sits in collapsed groups with the reason. CSV for Excel, compare 2–3.
frappe.pages["ai-ranking"].on_page_load = function (wrapper) {
	const T = talent_ai;
	const page = frappe.ui.make_app_page({ parent: wrapper, title: T.t("ترتيب المتقدمين", "Applicant ranking"), single_column: true });
	const state = { opening: null, sel: new Set(), data: null };
	wrapper.tai = { page, state };
	T.pageSetup(page);
	const field = page.add_field({
		fieldname: "opening", fieldtype: "Link", options: "Job Opening", label: T.t("الشاغر", "Opening"),
		get_query: () => ({ filters: { ai_enabled: 1 } }),
		change() { const v = field.get_value(); if (v && v !== state.opening) { state.opening = v; state.sel.clear(); load(); } },
	});
	wrapper.tai.field = field;
	page.set_primary_action(T.t("تصدير CSV", "Export CSV"), () => {
		if (!state.opening) return;
		window.open(`/api/method/ido_talent_ai.api.export_ranking_csv?job_opening=${encodeURIComponent(state.opening)}`);
	}, "download");
	page.add_inner_button(T.t("مقارنة المحددين", "Compare selected"), () => compare());
	page.add_inner_button(T.t("إعادة تقييم القديم والفاشل", "Re-score stale and failed"), () => rescoreAll());
	page.add_inner_button(T.t("متابعة المعالجة", "Batch monitor"), () => frappe.set_route("ai-batch", { opening: state.opening }));
	page.add_inner_button(T.t("بنك المتقدمين", "Talent pool"), () => frappe.set_route("ai-talent-pool", { opening: state.opening }));
	const $body = $(`<div class="tai" style="padding:12px 0"></div>`).appendTo(page.main);

	const GROUPS = {
		not_eligible: { ar: "غير مستوفين", en: "Not eligible", why: { ar: "لا يُرتَّبون، ويبقون في بنك المتقدمين", en: "not ranked, kept in the talent pool" } },
		needs_review: { ar: "يحتاج مراجعة", en: "Needs review", why: { ar: "قيمة مفقودة أو تغطية منخفضة أو تعارض", en: "missing value, low coverage or contradiction" } },
		processing: { ar: "جاري المعالجة", en: "Processing", why: { ar: "لم تكتمل بعد", en: "not finished yet" } },
		failed: { ar: "فشل", en: "Failed", why: { ar: "خطأ في المحرك بعد المحاولات", en: "engine error after retries" } },
		stale: { ar: "قديم", en: "Stale", why: { ar: "نسخة معايير سابقة أو بيانات معدّلة", en: "previous criteria version or edited data" } },
		duplicate: { ar: "مكرر", en: "Duplicate", why: { ar: "يُرتَّب الطلب الأصلي فقط", en: "only the original application is ranked" } },
	};

	function load() {
		if (!state.opening) {
			$body.html(`<div class="card"><p class="hint">${T.t("اختر شاغرًا مفعّلًا للذكاء الاصطناعي.", "Pick an opening with AI screening enabled.")}</p></div>`);
			return;
		}
		$body.html(`<span class="spin"></span>`);
		T.call("ranking", { job_opening: state.opening }).then((d) => { state.data = d; draw(); }).catch((e) => $body.html(`<div class="note danger">${T.esc(e.message || e)}</div>`));
	}
	wrapper.tai.load = load;

	function draw() {
		const t = T.t;
		const d = state.data;
		const crit = {};
		(d.criteria || []).forEach((c) => (crit[c.key] = c.text));
		const link = (x) => (x.applicant ? `<a href="${talent_ai.formUrl("Job Applicant", x.applicant)}"><b>${T.esc(x.applicant_name)}</b></a>` : `<b>${T.esc(x.applicant_name)}</b>`);
		const row = (x) => `<div class="rankrow r2">
			<div class="c-chk"><input type="checkbox" data-sel="${T.esc(x.applicant)}" ${state.sel.has(x.applicant) ? "checked" : ""} aria-label="${t("اختيار للمقارنة", "select to compare")}"></div>
			<div class="pos num">${x.rank}</div>
			<div class="c-name">${link(x)} <span class="hint">v${x.job_version}</span></div>
			<div class="c-score"><b class="score ${x.band}">${T.N(T.fmt1(x.score))}</b></div>
			<div class="c-band">${T.chipBand(x.band)}</div>
			<div class="c-bar bar ${x.band}"><i style="width:${x.score}%"></i></div>
			<div class="c-cov hint">${t("تغطية", "coverage")} ${T.N(T.pct(x.coverage))}</div>
			<div class="c-status">${x.hr_status ? T.chipStatus(x.hr_status) : ""}</div>
			${(x.strengths || []).length ? `<div class="c-str">${(x.strengths || []).slice(0, 4).map((k) => `<span class="chip green">${T.esc(crit[k] || k)}</span>`).join("")}</div>` : ""}</div>`;
		const other = (x) => `<div class="rankrow r3">
			<div class="pos off">—</div>
			<div class="c-name">${link(x)}<div class="hint">${T.mix(T.lang() === "ar" ? x.reason_ar : x.reason_en)}</div></div>
			<div class="c-score">${x.score != null && x.status !== "failed" ? `<b class="score ${x.eligibility === "not_eligible" ? "off" : x.band}">${T.N(T.fmt1(x.score))}</b>` : '<span class="hint">—</span>'}</div>
			<div class="c-chips">${T.chipAi(x.status)} ${x.eligibility ? T.chipElig(x.eligibility) : ""} ${T.flagChips((x.flags || []).filter((f) => ["contradiction", "missing_evidence", "low_coverage", "cv_unreadable", "duplicate"].includes(f)))}</div></div>`;
		const g = d.groups;
		const stale = g.stale.length + g.failed.length;
		const total = (d.criteria || []).reduce((a, c) => a + c.weight, 0);
		$body.html(`
			<div class="page-title"><div><h1>${T.esc(d.opening_title)}</h1><div class="sub">${T.N(d.total + g.processing.filter((x) => !x.candidate_ref).length)} ${t("متقدمًا", "applicants")} · ${T.N(d.ranked_total)} ${t("مرتَّبون", "ranked")} · ${t("نسخة المعايير", "profile version")} ${T.N("v" + d.job_version)}</div></div></div>
			<div class="kpis5" style="grid-template-columns:repeat(6,minmax(0,1fr))"><div class="kpi"><small>${t("مرتَّبون", "Ranked")}</small><b>${T.N(d.ranked_total)}</b></div>${Object.keys(GROUPS).filter((k) => k !== "duplicate").map((k) => `<div class="kpi"><small>${T.L(GROUPS[k])}</small><b>${T.N(g[k].length)}</b></div>`).join("")}</div>
			${stale ? `<div class="note grey">⚠ ${T.N(g.stale.length)} ${t("نتائج قديمة و", "stale and ")}${T.N(g.failed.length)} ${t("فاشلة لا تدخل الترتيب.", "failed results are not ranked.")} <button class="btn sm primary" data-act="rescore">↻ ${t("إعادة تقييمها", "Re-score them")}</button></div>` : ""}
			<div class="split" style="grid-template-columns:2.6fr 1fr"><div>
				<div class="card"><h2>${t("المرتَّبون (مكتملون ومستوفون)", "Ranked (completed and eligible)")} <small>${t("من الأعلى إلى الأدنى · حدّد 2–3 للمقارنة", "high to low · tick 2–3 to compare")}</small></h2>${d.ranked.map(row).join("") || `<p class="hint">${t("لا أحد بعد", "Nobody yet")}</p>`}${T.disclaimer()}</div>
				${Object.keys(GROUPS).map((k) => `<details class="tai-group"><summary>${T.L(GROUPS[k])} (${T.N(g[k].length)}) — ${T.L(GROUPS[k].why)}</summary><div style="margin-top:10px">${g[k].map(other).join("") || `<p class="hint">${t("لا أحد", "Nobody")}</p>`}</div></details>`).join("")}
			</div><div>
				<div class="card"><h2>${t("الأوزان المعتمدة", "Approved weights")} <small>v${d.job_version}</small></h2><table><tbody>${(d.criteria || []).map((c) => `<tr><td>${T.esc(c.text)} ${c.mandatory ? T.chipMand(true) : ""}</td><td class="num">${c.weight}%</td></tr>`).join("")}<tr><td><b>${t("المجموع", "Total")}</b></td><td class="num"><b>${total}%</b></td></tr></tbody></table><p class="hint">${t("تغيير الأوزان من ملف المعايير: مسودة ← معاينة الأثر ← اعتماد نسخة جديدة ← إعادة التقييم.", "Weights change in the AI Job Profile: draft → impact preview → approve a new version → re-score.")}</p></div>
				<div class="card"><h2>${t("كيف يُحسب", "How it is computed")}</h2><div class="kv"><small>${t("الدرجة", "score")}</small><span class="num">Σ(w% × level) ÷ 100</span><small>${t("المستويات", "levels")}</small><span class="num">0 · 25 · 50 · 75 · 100</span><small>${t("التغطية", "coverage")}</small><span class="num">Σw(evidence) ÷ Σw</span><small>${t("الفئات", "bands")}</small><span class="bands"><span class="chip green">${t("مرتفعة", "high")} <bdi dir="ltr">≥ 75</bdi></span> <span class="chip amber">${t("متوسطة", "medium")} <bdi dir="ltr">50–74.9</bdi></span> <span class="chip red">${t("منخفضة", "low")} <bdi dir="ltr">&lt; 50</bdi></span></span></div>${T.disclaimer()}</div>
			</div></div>`);
	}

	$body.on("change", "[data-sel]", (e) => {
		const n = e.currentTarget.dataset.sel;
		if (e.currentTarget.checked) state.sel.add(n);
		else state.sel.delete(n);
		if (state.sel.size > 3) { state.sel.delete(n); e.currentTarget.checked = false; frappe.show_alert(T.t("المقارنة بين 2 أو 3 فقط", "Compare 2 or 3 only")); }
	});
	$body.on("click", "[data-act=rescore]", () => rescoreAll());

	function rescoreAll() {
		if (!state.opening) return;
		frappe.confirm(T.t("إعادة تقييم كل النتائج القديمة والفاشلة بآخر نسخة معتمدة؟", "Re-score every stale and failed result with the latest approved version?"), () =>
			T.call("rescreen_all", { job_opening: state.opening }).then((r) => { frappe.show_alert({ indicator: "blue", message: T.t(`أُضيف ${r.queued} للمعالجة` + (r.skipped ? ` · ${r.skipped} بدون موافقة على المعالجة` : ""), `${r.queued} queued` + (r.skipped ? ` · ${r.skipped} without consent` : "")) }); load(); })
		);
	}

	function compare() {
		const names = Array.from(state.sel);
		if (names.length < 2) return frappe.msgprint(T.t("حدّد متقدمَين أو ثلاثة من قائمة المرتَّبين.", "Tick two or three ranked applicants."));
		T.openCompare(names);
	}

	let timer = null;
	frappe.realtime.on("talent_ai_batch", (d) => {
		if (frappe.get_route()[0] !== "ai-ranking" || !state.opening || (d && d.job_opening && d.job_opening !== state.opening)) return;
		clearTimeout(timer);
		timer = setTimeout(load, 2000);
	});
};

frappe.pages["ai-ranking"].on_page_show = function (wrapper) {
	const opts = frappe.route_options || {};
	frappe.route_options = null;
	const s = wrapper.tai;
	if (opts.opening && opts.opening !== s.state.opening) {
		s.state.opening = opts.opening;
		s.field.set_value(opts.opening);
		s.load();
	} else if (!s.state.opening) {
		talent_ai.call("openings").then((rows) => {
			if (rows.length && !s.state.opening) { s.state.opening = rows[0].name; s.field.set_value(rows[0].name); }
			s.load();
		});
	} else s.load();
};

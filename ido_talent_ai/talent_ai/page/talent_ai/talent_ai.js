// Step 0 — the recruitment cycle with Talent AI. Every stage opens the real screen; the counts are live.
frappe.pages["talent-ai"].on_page_load = function (wrapper) {
	const T = talent_ai;
	const page = frappe.ui.make_app_page({ parent: wrapper, title: T.t("خريطة دورة التوظيف مع Talent AI", "Recruitment cycle map with Talent AI"), single_column: true });
	T.pageSetup(page);
	const $body = $(`<div class="tai" style="padding:12px 0"></div>`).appendTo(page.main);
	wrapper.tai = { load };

	function go(k, op) {
		const o = op ? { opening: op.name } : {};
		const routes = {
			profile: () => (op && op.ai_profile ? frappe.set_route("Form", "AI Job Profile", op.ai_profile) : frappe.set_route("List", "AI Job Profile")),
			opening: () => (op ? frappe.set_route("Form", "Job Opening", op.name) : frappe.set_route("List", "Job Opening")),
			portal: () => window.open("/jobs", "_blank"),
			form: () => window.open(op ? `/ai-apply/new?job_title=${encodeURIComponent(op.name)}` : "/jobs", "_blank"),
			processing: () => frappe.set_route("ai-batch", o),
			list: () => frappe.set_route("List", "Job Applicant", op ? { job_title: op.name } : {}),
			ranking: () => frappe.set_route("ai-ranking", o),
			decision: () => frappe.set_route("List", "Job Applicant", op ? { job_title: op.name, ai_status: "Completed" } : {}),
			interview: () => frappe.set_route("List", "Interview"),
			pool: () => frappe.set_route("ai-talent-pool", o),
			jobs: () => frappe.set_route("List", "AI Recruitment Job"),
			settings: () => frappe.set_route("Form", "AI Recruitment Settings"),
			audit: () => frappe.set_route("List", "AI Recruitment Audit Log"),
		};
		(routes[k] || (() => {}))();
	}

	function load() {
		Promise.all([T.call("openings"), frappe.xcall("frappe.client.get_count", { doctype: "AI Recruitment Job", filters: { status: "Failed" } })]).then(([ops, failed]) => draw(ops, failed));
	}

	function draw(ops, failed) {
		const t = T.t;
		const op = ops[0];
		const WHO = { hr: ["HR", "HR"], applicant: ["المتقدم", "Applicant"], system: ["النظام", "System"] };
		const who = (w) => `<span class="who ${w}">${t(...WHO[w])}</span>`;
		const nodes = [
			["profile", "ملف المعايير", "AI Job Profile", "hr", "شروط + أسئلة فرز + معايير بأوزان 100% + سُلّم 0–100", "Rules + screening questions + criteria (100%) + rubric 0–100"],
			["opening", "الشاغر", "Job Opening", "hr", "ai_enabled · ai_profile · ai_profile_approved", "ai_enabled · ai_profile · ai_profile_approved"],
			["portal", "النشر", "Publish", "hr", "صفحة الوظائف العامة /jobs", "Public jobs page /jobs"],
			["form", "نموذج التقديم", "Application form", "applicant", "بيانات الشروط + إجابات الفرز + سيرة اختيارية + موافقة", "Rule facts + answers + optional CV + consent"],
			["processing", "المعالجة", "Processing", "system", "إجابات ← نص ← إخفاء هوية ← أدلة ← شروط ← مستويات ← درجة", "Answers → text → redact → evidence → rules → levels → score"],
			["list", "قائمة المتقدمين", "Applicant list", "hr", "ai_status · الدرجة · الفئة · الأهلية", "ai_status · score · band · eligibility"],
			["ranking", "الترتيب", "Ranking", "hr", "مكتملون ومستوفون فقط · مقارنة · تصدير", "Completed and eligible only · compare · export"],
			["decision", "قرار HR", "HR decision", "hr", "ترشيح / تعليق / رفض بسبب مكتوب — HR فقط", "Shortlist / hold / reject with a reason — HR only"],
			["interview", "المقابلة / العرض", "Interview / offer", "hr", "كما هو في Frappe HR اليوم", "As in Frappe HR today"],
		];
		const box = (n) => `<div class="mnode"><div class="box" data-go="${n[0]}"><b>${t(n[1], n[2])}</b><small>${T.mix(t(n[4], n[5]))}</small>${who(n[3])}</div><span class="arrow">${T.lang() === "ar" ? "←" : "→"}</span></div>`;
		const side = (k, ar, en, dar, den, w) => `<div class="mnode" style="flex:0 0 240px"><div class="box" data-go="${k}"><b>${t(ar, en)}</b><small>${T.mix(t(dar, den))}</small>${who(w)}</div></div>`;
		const opRows = ops.map((o) => `<tr><td><a href="${frappe.utils.get_form_link("Job Opening", o.name)}">${T.esc(o.job_title)}</a></td><td>${o.ai_profile_approved ? `<span class="chip green">${t("معتمد", "approved")}</span>` : `<span class="chip amber">${t("غير معتمد", "not approved")}</span>`}</td><td>${T.chip(o.status === "Open" ? { ar: "مفتوح", en: "Open", cls: "green" } : { ar: "مغلق", en: "Closed", cls: "grey" })}</td><td><button class="btn sm" data-go="ranking" data-op="${T.esc(o.name)}">${t("الترتيب", "Ranking")}</button> <button class="btn sm" data-go="processing" data-op="${T.esc(o.name)}">${t("المعالجة", "Processing")}</button></td></tr>`).join("");
		$body.html(`<div class="card"><div class="map">${nodes.map(box).join("")}</div>
			<div class="branch"><span class="hint">${t("فروع جانبية:", "Side branches:")}</span>
			${side("pool", "بنك المتقدمين", "Talent pool", "كل متقدم يبقى محفوظًا ويُقترح لشواغر لاحقة", "Every applicant is kept and suggested for later openings", "hr")}
			${side("jobs", "مهام الذكاء الاصطناعي", "AI Recruitment Jobs", `طابور خلفي بمحاولات · ${failed} فاشلة`, `Background queue with retries · ${failed} failed`, "system")}
			${side("settings", "الإعدادات", "Settings", "المزوّد والنموذج والمهلة والمحاولات من المحرك", "Provider, model, timeout and retries from the engine", "hr")}
			${side("audit", "سجل التدقيق", "Audit log", "كل مهمة وكل قرار بالمستخدم والسبب", "Every job and decision with user and reason", "system")}</div></div>
			<div class="card"><h2>${t("الشواغر المفعّل لها الذكاء", "Openings with AI enabled")}</h2><table><thead><tr><th>${t("الشاغر", "Opening")}</th><th>${t("ملف المعايير", "Profile")}</th><th>${t("الحالة", "Status")}</th><th></th></tr></thead><tbody>${opRows || `<tr><td colspan="4" class="hint">${t("لا شواغر بعد", "No openings yet")}</td></tr>`}</tbody></table></div>
			<div class="grid3">
				<div class="card"><h2>${t("ما الذي يتغيّر لـ HR", "What changes for HR")}</h2><ul class="ul"><li>${t("ملف معايير معتمد لكل شاغر بأوزان مجموعها 100%", "An approved AI Job Profile per opening, weights totalling 100%")}</li><li>${t("حالة معالجة ودرجة وفئة في قائمة المتقدمين", "ai_status, score and band in the applicant list")}</li><li>${t("دليل لكل مستوى: إجابة النموذج أو اقتباس من السيرة", "Evidence for every level: a form answer or a CV quote")}</li><li>${t("الحالة تتغيّر بأزرار HR فقط وبسبب مكتوب", "Status changes only through HR buttons with a reason")}</li></ul></div>
				<div class="card"><h2>${t("ما الذي يتغيّر للمتقدم", "What changes for the applicant")}</h2><ul class="ul"><li>${t("أسئلة فرز قصيرة بدل الاعتماد على السيرة", "Short screening questions instead of relying on the CV")}</li><li>${t("السيرة الذاتية اختيارية", "The CV is optional")}</li><li>${t("موافقة صريحة على المعالجة", "Explicit consent to processing")}</li></ul></div>
				<div class="card"><h2>${t("ما الذي يفعله النظام", "What the system does")}</h2><ul class="ul"><li>${t("قراءة الإجابات ثم النص (التعرف الضوئي للصور فقط)", "Reads answers, then text (OCR for scans only)")}</li><li>${t("تحقق من الشروط الإلزامية في الكود", "Hard-rule check in code")}</li><li>${t("إخفاء الهوية قبل النموذج اللغوي", "Redaction before the language model")}</li><li>${t("مهام خلفية بمحاولات، وإعادة تقييم عند تغيير المعايير", "Background jobs with retries, re-scoring when criteria change")}</li></ul></div>
			</div>${T.disclaimer()}`);
		$body.off("click.go").on("click.go", "[data-go]", (e) => {
			const el = e.currentTarget.dataset;
			go(el.go, el.op ? ops.find((o) => o.name === el.op) : op);
		});
	}
};

frappe.pages["talent-ai"].on_page_show = function (wrapper) {
	wrapper.tai.load();
};

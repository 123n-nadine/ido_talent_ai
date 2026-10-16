// «التوظيف الذكي» — the home page of Talent AI for HR: the nine places HR uses, in the order of
// the cycle, each with one line saying what it is for, plus live counts.
frappe.pages["ai-recruitment"].on_page_load = function (wrapper) {
	const T = talent_ai;
	const page = frappe.ui.make_app_page({ parent: wrapper, title: T.t("التوظيف الذكي", "AI Recruitment"), single_column: true });
	T.pageSetup(page);
	page.add_inner_button(T.t("خريطة الدورة", "Cycle map"), () => frappe.set_route("talent-ai"));
	const $body = $(`<div class="tai tai-home"></div>`).appendTo(page.main);
	wrapper.tai = { load };

	const can = (dt) => frappe.model.can_read(dt);
	const CARDS = [
		{ n: 1, icon: "list-checks", ar: "ملف المعايير", en: "Criteria profiles", go: () => frappe.set_route("List", "AI Job Profile"),
			dar: "شروط الوظيفة وأسئلة الفرز والمعايير بأوزانها (مجموعها 100%)، وبتتعتمد قبل ما يبدأ الفرز.",
			den: "Hard rules, screening questions and weighted criteria (total 100%), approved before screening starts.", dt: "AI Job Profile" },
		{ n: 2, icon: "briefcase", ar: "الشواغر", en: "Job openings", go: () => frappe.set_route("List", "Job Opening"),
			dar: "الشاغر نفسه: بتفعّلي فيه الفرز الذكي وتربطيه بملف المعايير المعتمد.",
			den: "The opening itself: turn on AI screening and link the approved criteria profile.", dt: "Job Opening" },
		{ n: 3, icon: "globe", ar: "صفحة التقديم العامة", en: "Public application page", newtab: "/jobs",
			dar: "الصفحة اللي المتقدم بيشوفها: الوظائف المنشورة وفورم التقديم بالعربي. بتفتح في تاب جديد.",
			den: "What applicants see: published jobs and the Arabic application form. Opens in a new tab." },
		{ n: 4, icon: "users", ar: "قائمة المتقدمين", en: "Applicants", go: () => frappe.set_route("List", "Job Applicant"),
			dar: "كل الطلبات بحالة المعالجة والدرجة والفئة، ومنها بتفتحي تقييم أي متقدم بالأدلة.",
			den: "Every application with AI status, score and band; open any applicant to see the evidence.", dt: "Job Applicant" },
		{ n: 5, icon: "list-ordered", ar: "الترتيب", en: "Ranking", go: () => frappe.set_route("ai-ranking"),
			dar: "ترتيب المستوفين في كل شاغر من الأعلى للأقل، مع المقارنة وتصدير القائمة لـ Excel.",
			den: "Eligible applicants of an opening from highest to lowest, with comparison and Excel export." },
		{ n: 6, icon: "user-search", ar: "بنك المتقدمين", en: "Talent pool", go: () => frappe.set_route("ai-talent-pool"),
			dar: "اقتراحات من متقدمين سابقين لشاغر جديد: الشروط الأول وبعدين التشابه. اقتراح بس.",
			den: "Suggestions from past applicants for a new opening: rules first, then similarity. Suggestions only." },
		{ n: 7, icon: "cpu", ar: "مهام الذكاء", en: "AI jobs", go: () => frappe.set_route("List", "AI Recruitment Job"),
			dar: "كل مهمة معالجة بحالتها ومحاولاتها، وإعادة المحاولة لو فشلت.",
			den: "Every processing job with its status and attempts; retry the failed ones.", dt: "AI Recruitment Job" },
		{ n: 8, icon: "settings", ar: "الإعدادات", en: "Settings", go: () => frappe.set_route("Form", "AI Recruitment Settings"),
			dar: "ربط المحرك، والمزوّد والنموذج، والبيانات المسموح تتبعت. لمديرة الموارد البشرية بس.",
			den: "Engine connection, provider and model, and the facts allowed to be sent. HR Manager only.", dt: "AI Recruitment Settings" },
		{ n: 9, icon: "scroll-text", ar: "سجل التدقيق", en: "Audit log", go: () => frappe.set_route("List", "AI Recruitment Audit Log"),
			dar: "كل قرار وكل تعديل وكل مهمة: مين عملها وإمتى وليه.",
			den: "Every decision, edit and job: who, when and why.", dt: "AI Recruitment Audit Log" },
	];

	function load() {
		T.call("home_counts").then(draw).catch(() => draw(null));
	}

	function draw(c) {
		const t = T.t;
		const num = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"];
		const counts = c
			? `<div class="tai-home-counts">
				<div><b class="num">${T.N(c.openings)}</b><small>${t("شواغر بالفرز الذكي", "openings with AI")}</small></div>
				<div><b class="num">${T.N(c.applicants)}</b><small>${t("طلبات", "applications")}</small></div>
				<div class="blue"><b class="num">${T.N(c.processing)}</b><small>${t("جاري المعالجة", "processing")}</small></div>
				<div class="amber"><b class="num">${T.N(c.needs_review)}</b><small>${t("يحتاج مراجعة", "needs review")}</small></div>
				<div class="red"><b class="num">${T.N(c.failed)}</b><small>${t("فشل", "failed")}</small></div>
			</div>`
			: "";
		const cards = CARDS.map((x, i) => {
			const allowed = !x.dt || can(x.dt);
			return `<button type="button" class="tai-home-card ${allowed ? "" : "off"}" data-i="${i}" ${allowed ? "" : "disabled"}>
				<span class="n">${num[i]}</span>
				<span class="ico">${frappe.utils.icon(x.icon, "md")}</span>
				<span class="txt"><b>${T.esc(T.lang() === "ar" ? x.ar : x.en)}${x.newtab ? ` <span class="ext">↗</span>` : ""}</b>
				<small>${T.mix(T.lang() === "ar" ? x.dar : x.den)}</small>
				${allowed ? "" : `<small class="deny">${t("غير متاح لدورك", "not available for your role")}</small>`}</span></button>`;
		}).join("");
		$body.html(`<div class="tai-home-head"><h1>${t("التوظيف الذكي", "AI Recruitment")}</h1>
			<p>${t("الذكاء الاصطناعي يرشّح ويشرح، والقرار للـ HR.", "The AI ranks and explains; HR decides.")}</p></div>
			${counts}<div class="tai-home-grid">${cards}</div>
			<p class="hint tai-home-foot">${t("الأرقام دي حقيقية من الطلبات الحالية. الدرجة ترتيب مقابل معايير معتمدة، وليست احتمال نجاح في الوظيفة.", "These counts are live. A score is a ranking against approved criteria, not a probability of success in the job.")}</p>`);
		$body.off("click.home").on("click.home", ".tai-home-card", (e) => {
			const x = CARDS[Number(e.currentTarget.dataset.i)];
			if (x.newtab) window.open(x.newtab, "_blank", "noopener");
			else x.go();
		});
	}
};

frappe.pages["ai-recruitment"].on_page_show = function (wrapper) {
	wrapper.tai.load();
};

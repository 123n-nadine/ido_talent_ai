/* Talent AI — shared desk helpers: labels (Arabic first), chips, the AI assessment section and the
   CV analysis view. Used by the Job Applicant form and the Talent AI pages. Everything comes from
   whitelisted methods; nothing here talks to the engine directly. */
frappe.provide("talent_ai");

(function () {
	const T = talent_ai;
	T.lang = () => ((frappe.boot && frappe.boot.lang) || "en").startsWith("ar") ? "ar" : "en";
	T.t = (ar, en) => (T.lang() === "ar" ? ar : en);
	T.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
	T.N = (n) => `<bdi class="num">${T.esc(n)}</bdi>`;
	// escape, then keep Latin words, numbers, codes and paths in their own reading direction inside
	// Arabic sentences (never inside an HTML entity)
	T.mix = (s) => T.esc(s).replace(/(?<![&#\w])[A-Za-z0-9](?:[A-Za-z0-9_.:/@%+\-]*[A-Za-z0-9%])?(?:\s+[A-Za-z](?:[A-Za-z0-9_.:/@%+\-]*[A-Za-z0-9%])?)*/g, (m) => `<bdi dir="ltr">${m}</bdi>`);
	// Same labels as the engine (app/domain/arabic_text.py): how the CV was read, what redaction removed.
	T.REDACT = { name: ["الاسم", "name"], phone: ["الهاتف", "phone"], email: ["البريد", "e-mail"], national_id: ["رقم الهوية", "ID number"], dob: ["تاريخ الميلاد", "date of birth"], age: ["العمر", "age"], nationality: ["الجنسية", "nationality"], gender: ["الجنس", "gender"], address: ["العنوان", "address"], url: ["رابط", "link"] };
	T.redactLabel = (k) => (T.REDACT[k] ? T.t(T.REDACT[k][0], T.REDACT[k][1]) : k);
	T.method = (m) => {
		m = m || "";
		const base = m.split("+").pop();
		if (m.startsWith("libreoffice+")) return T.t("ملف DOC/RTF محوَّل إلى PDF", "DOC/RTF converted to PDF");
		if (base.startsWith("ocr:")) return T.t("قراءة ضوئية (OCR)", "OCR (scanned image)");
		if (base === "pdf_text") return T.t("نص PDF مباشر", "PDF text layer");
		if (base === "docx") return T.t("ملف Word", "Word file");
		return T.esc(base || "—");
	};
	// a CV quote: Arabic in «…»; an English quote keeps English marks inside its own LTR block
	T.q = (s) => (/[\u0600-\u06FF]/.test(String(s || "")) ? `«<bdi>${T.esc(s)}</bdi>»` : `<bdi dir="ltr">“${T.esc(s)}”</bdi>`);
	T.fmt1 = (n) => (n == null || n === "" ? "—" : (Math.round(Number(n) * 10) / 10).toString());
	T.pct = (n) => (n == null ? "—" : Math.round(Number(n) * 100) + "%");
	T.fd = (s, withTime = true) => {
		if (!s) return "—";
		const d = new Date(String(s).replace(" ", "T"));
		if (isNaN(d)) return T.esc(s);
		const opts = { day: "numeric", month: "long", year: "numeric" };
		if (withTime) Object.assign(opts, { hour: "numeric", minute: "2-digit" });
		return `<bdi>${T.esc(d.toLocaleString(T.lang() === "ar" ? "ar-EG-u-nu-latn" : "en-GB", opts))}</bdi>`;
	};
	T.DISCLAIMER = { ar: "الدرجة ترتيب مقابل معايير معتمدة، وليست احتمال نجاح في الوظيفة.", en: "The score is a ranking against approved criteria, not a probability of success in the job." };
	T.disclaimer = () => `<div class="disclaimer">ⓘ ${T.t(T.DISCLAIMER.ar, T.DISCLAIMER.en)}</div>`;
	T.BAND = { high: { ar: "مرتفعة", en: "High", cls: "green" }, medium: { ar: "متوسطة", en: "Medium", cls: "amber" }, low: { ar: "منخفضة", en: "Low", cls: "red" } };
	T.ELIG = { eligible: { ar: "مستوفٍ", en: "Eligible", cls: "green" }, not_eligible: { ar: "غير مستوفٍ بحسب ما كتبه", en: "Not eligible (as declared)", cls: "red" }, needs_review: { ar: "يحتاج مراجعة", en: "Needs review", cls: "amber" } };
	T.AIST = { Processing: { ar: "جاري المعالجة", en: "Processing", cls: "blue" }, Completed: { ar: "مكتمل", en: "Completed", cls: "green" }, "Needs Review": { ar: "يحتاج مراجعة", en: "Needs Review", cls: "amber" }, Failed: { ar: "فشل", en: "Failed", cls: "red" },
		"Awaiting Consent": { ar: "بانتظار الموافقة", en: "Awaiting consent", cls: "amber" }, "Consent Withdrawn": { ar: "سحب الموافقة", en: "Consent withdrawn", cls: "grey" } };
	T.ENG = { queued: "Processing", processing: "Processing", completed: "Completed", needs_review: "Needs Review", failed: "Failed",
		awaiting_consent: "Awaiting Consent", consent_withdrawn: "Consent Withdrawn" };
	T.STATUS = { Open: { ar: "جديد", en: "Open", cls: "blue" }, Replied: { ar: "تم الرد", en: "Replied", cls: "blue" }, Shortlisted: { ar: "مرشّح للمقابلة", en: "Shortlisted", cls: "green" }, Rejected: { ar: "مرفوض", en: "Rejected", cls: "red" }, Hold: { ar: "معلّق", en: "On hold", cls: "amber" }, Accepted: { ar: "مقبول", en: "Accepted", cls: "green" } };
	T.FLAGS = {
		missing_evidence: { ar: "دليل ناقص", en: "Missing evidence" }, mandatory_missing: { ar: "معيار إلزامي بلا دليل", en: "Mandatory without evidence" },
		mandatory_zero: { ar: "معيار إلزامي عند 0", en: "Mandatory at level 0" }, low_coverage: { ar: "تغطية منخفضة", en: "Low coverage" },
		contradiction: { ar: "تعارض بين الإجابة والسيرة", en: "Answer vs CV contradiction" }, evidence_mismatch: { ar: "دليل لا يطابق الإجابة", en: "Evidence mismatch" },
		quote_not_found: { ar: "اقتباس غير موجود (أُسقط)", en: "Quote not found (dropped)" }, cv_unreadable: { ar: "ملف السيرة غير مقروء", en: "CV unreadable" },
		redaction_guard: { ar: "حارس الإخفاء أزال بيانات متبقية", en: "Redaction guard removed leftover data" },
		cv_partial_read: { ar: "السيرة قُرئت جزئيًا", en: "CV read partially" },
		low_ocr_confidence: { ar: "ثقة OCR منخفضة", en: "Low OCR confidence" }, duplicate: { ar: "طلب مكرر", en: "Duplicate" },
		stale: { ar: "قديم — نسخة معايير سابقة", en: "Stale — previous version" }, data_changed: { ar: "النتيجة لا تعكس آخر تعديل", en: "Result does not reflect the latest edit" },
		hr_override: { ar: "تعديل HR", en: "HR override" },
	};
	T.L = (o) => (o ? (T.lang() === "ar" ? o.ar : o.en) : "");
	T.chip = (o, extra) => (o ? `<span class="chip ${o.cls || ""}"><span class="dot"></span>${T.L(o)}${extra || ""}</span>` : "");
	T.chipBand = (b, elig) => (elig === "not_eligible" ? `<span class="chip">${T.t("خارج الترتيب", "Not ranked")}</span>` : T.chip(T.BAND[b]));
	T.chipElig = (e) => T.chip(T.ELIG[e]);
	T.chipAi = (s) => T.chip(T.AIST[T.ENG[s] || s] || null);
	T.chipStatus = (s) => T.chip(T.STATUS[s] || { ar: s, en: s });
	T.chipLvl = (l) => `<span class="chip ${l >= 75 ? "green" : l >= 50 ? "amber" : l > 0 ? "red" : ""}">${l == null ? "—" : l}</span>`;
	T.FLAG_CLS = { hr_override: "purple", duplicate: "grey", stale: "grey", data_changed: "grey" };
	T.flagChips = (flags) => (flags || []).filter((f) => T.FLAGS[f]).map((f) => `<span class="chip ${T.FLAG_CLS[f] || "amber"}">${T.L(T.FLAGS[f])}</span>`).join(" ");
	T.chipMand = (m) => (m ? `<span class="chip mand">${T.t("إلزامي", "mandatory")}</span>` : `<span class="chip">${T.t("اختياري", "optional")}</span>`);
	T.formUrl = (dt, name) => frappe.utils.get_form_link(dt, name);
	T.call = (method, args) => frappe.xcall("ido_talent_ai.api." + method, args || {});
	T.isHR = () => frappe.user && (frappe.user.has_role("HR Manager") || frappe.user.has_role("HR User"));

	// The first time an HR user opens the desk home in a browser tab, show «التوظيف الذكي».
	$(document).on("page-change", () => {
		try {
			const r = frappe.get_route() || [];
			const atHome = !r.length || (r.length === 1 && ["", "desktop", "desk", "Workspaces", "workspaces"].includes(r[0]));
			if (!atHome || !T.isHR() || frappe.session.user === "Administrator" || sessionStorage.getItem("tai_home_shown")) return;
			sessionStorage.setItem("tai_home_shown", "1");
			frappe.set_route("ai-recruitment");
		} catch (e) {
			/* never block the desk */
		}
	});

	/* ------------------------------------------------------------------ dialogs */
	T.reason_dialog = (title, onok, extra_fields) => {
		const d = new frappe.ui.Dialog({
			title,
			fields: (extra_fields || []).concat([{ fieldname: "reason", fieldtype: "Small Text", label: T.t("السبب (إلزامي — يُسجَّل في سجل التدقيق)", "Reason (required — recorded in the audit log)"), reqd: 1 }]),
			primary_action_label: T.t("تأكيد", "Confirm"),
			primary_action(values) {
				if (!(values.reason || "").trim()) { frappe.msgprint(T.t("السبب مطلوب", "A reason is required")); return; }
				d.hide();
				onok(values);
			},
		});
		d.show();
		return d;
	};

	/* ------------------------------------------------------------------ the 10 stages */
	T.stagesHtml = (stages) => {
		if (!stages || !stages.length) return "";
		const cells = stages.map((st, i) => {
			const cls = st.status === "done" ? "done" : st.status === "running" ? "on" : st.status === "skipped" ? "skip" : st.status === "failed" ? "failed" : "";
			const mark = st.status === "done" ? "✓" : st.status === "skipped" ? "–" : st.status === "failed" ? "✗" : i + 1;
			const ms = st.ms != null && st.ms > 0 ? ` <span class="num">(${st.ms >= 1000 ? (st.ms / 1000).toFixed(1) + "s" : st.ms + "ms"})</span>` : "";
			return `<div class="pstep ${cls}"><div class="n">${mark}</div><div class="t"><b>${T.esc(T.lang() === "ar" ? st.label_ar : st.label_en)}</b><small>${st.status === "running" ? `<span class="spin"></span> ${T.t("جارٍ…", "running…")}` : T.mix((T.lang() === "ar" ? st.note : st.note_en || st.note) || "")}${ms}</small></div></div>`;
		}).join("");
		return `<div class="stages pipe">${cells}</div>`;
	};

	/* ------------------------------------------------------------------ the AI section of an applicant */
	T.assessmentHtml = (d) => {
		const t = T.t;
		T.cvNote = d.cv_note;
		const r = d.result;
		const qLabel = {};
		(d.questions || []).forEach((q) => (qLabel[q.key] = q.label));
		const rubric = {};
		(d.criteria || []).forEach((c) => (rubric[c.key] = c.rubric || []));
		const rubricText = (key, lvl) => { const x = (rubric[key] || []).find((y) => y.level === lvl); return x ? T.esc(x.text) : ""; };
		let html = "";
		const c = d.consent || {};
		if (c.withdrawn_on) {
			html += `<div class="note grey">⊘ <b>${t("مستبعد: سحب الموافقة", "Excluded: consent withdrawn")}</b> — ${t("سحب المتقدم موافقته على المعالجة في", "the applicant withdrew consent to processing on")} ${T.fd(c.withdrawn_on)}. ${t("خرج من الترتيب، ولا تُعرض له درجة ولا تفاصيل.", "Out of the ranking, with no score and no details.")} ${c.erased_on ? `${t("حُذفت بيانات الذكاء الاصطناعي الخاصة به من المحرك (المستندات والملف المنظّم والفهرسة والنتائج) في", "Their AI data was erased from the engine (documents, structured profile, index and results) on")} ${T.fd(c.erased_on)}.` : t("حذف بياناته من المحرك قيد التنفيذ، ويُعاد تلقائيًا كل دقيقتين حتى يتم.", "The erasure in the engine is pending and is retried every two minutes until done.")} ${t("الطلب الأصلي باقٍ كما هو.", "The original application stays as it is.")}</div>`;
			return `<div class="tai">${html}${T.decisionHtml(d)}</div>`;
		}
		if (d.ai_status === "Awaiting Consent") {
			html += `<div class="note strong">⏸ <b>${t("بانتظار موافقة المتقدم على المعالجة", "Awaiting the applicant's consent to processing")}</b> — ${t("الطلب محفوظ بكل بياناته، ولا يُرسل للذكاء الاصطناعي قبل تسجيل الموافقة. إذا وقّع المتقدم موافقة خارج النظام (مثل نموذج ورقي)، سجّلها مع مصدرها، ويبدأ التقييم وحده.", "The application is saved with all its data and is not sent to the AI before the consent is recorded. If the applicant signed a consent outside the system (a paper form, for example), record it with its source and the screening starts by itself.")} <button class="btn sm primary" data-tai="consent">✓ ${t("تسجيل الموافقة", "Record consent")}</button></div>`;
			return `<div class="tai">${html}${T.decisionHtml(d)}</div>`;
		}
		if (c.source) html += `<div class="note info">✓ ${t("سجّل الموافقة", "Consent recorded by")} <b>${T.esc(c.recorded_by || "")}</b> · ${T.fd(c.on)} — ${t("المصدر", "source")}: ${T.q(c.source)}</div>`;
		if (d.duplicate_of) html += `<div class="note grey">⧉ <b>${t("طلب مكرر", "Duplicate application")}</b> — ${t("نفس رقم الهوية (بصمة مشفّرة) مثل", "Same national ID (hashed) as")} <a href="${talent_ai.formUrl("Job Applicant", d.duplicate_of)}"><b>${T.esc(d.duplicate_of_name || d.duplicate_of)}</b></a>. ${t("لا يُحذف أي طلب تلقائيًا؛ يُرتَّب الطلب الأصلي فقط.", "Nothing is deleted automatically; only the original application is ranked.")}</div>`;
		const stale = d.ai_stale || (r && r.current === false);
		if (stale && r && d.ai_status !== "Processing") html += `<div class="note grey">⚠ ${d.stale_reason === "stale" || (r && r.stale_reason === "stale") ? t("هذه النتيجة محسوبة بنسخة معايير سابقة", "This result was computed with a previous criteria version") : t("النتيجة لا تعكس آخر تعديل على بيانات المتقدم", "The result does not reflect the latest edit to the applicant data")}. ${t("لا تُعرض كنتيجة حالية ولا تدخل الترتيب حتى تُعاد.", "It is not current and is not ranked until re-scored.")} <button class="btn sm primary" data-tai="rescreen">↻ ${t("إعادة التقييم", "Re-score")}</button></div>`;
		if (d.ai_status === "Processing") html += `<div class="note"><span class="spin"></span> ${t("جاري المعالجة… تتحدّث هذه الشاشة تلقائيًا عند وصول النتيجة.", "Processing… this screen updates by itself when the result arrives.")}</div>`;
		if (d.ai_status === "Failed") {
			const j = (d.jobs || [])[0];
			html += `<div class="note danger">✗ ${t("فشلت المعالجة", "Processing failed")}${j ? ` — ${T.esc(j.error_message || "")} (${t("المحاولات", "attempts")} ${j.attempts}/${j.max_attempts || 3})` : ""}. ${t("الطلب محفوظ وظاهر بشكل طبيعي وإجاباته كاملة.", "The application is saved and visible with all its answers.")} <button class="btn sm primary" data-tai="retry" data-job="${j ? j.name : ""}">↻ ${t("إعادة المحاولة", "Retry")}</button></div>`;
		}
		if (!r || !r.criteria) {
			if (!d.ai_status) html += `<div class="note">${t("لم يُرسل هذا الطلب للفرز الذكي (الشاغر غير مفعّل للذكاء أو ملف المعايير غير معتمد).", "This application was not sent to AI screening (AI not enabled on the opening or the profile is not approved).")}</div>`;
			return `<div class="tai">${html}${T.decisionHtml(d)}</div>`;
		}
		const checks = (r.eligibility_checks || []).map((c) => `<li>${c.ok === true ? "✓" : c.ok === false ? "✗" : "?"} ${T.mix(T.lang() === "ar" ? c.text_ar : c.text_en)}</li>`).join("");
		const evCell = (c) => {
			if (c.missing_evidence && c.overridden_level == null) return `<span class="src missing">${t("دليل ناقص", "missing evidence")}</span> <span class="hint">${t("لم يُجب ولا تذكره السيرة", "not answered and not in the CV")}</span>`;
			if (c.contradiction) {
				const parts = String(c.evidence || "").split(" | ");
				return `<div class="contra"><div><span class="src cv">${t("من السيرة", "from the CV")}</span> <span class="quote" data-tai="hilite" data-key="${c.key}">${T.q(parts[0])}</span> → ${T.chipLvl(c.cv_level != null ? c.cv_level : c.level)}</div><div><span class="src form">${t("إجابة النموذج", "form answer")}</span> <span class="quote none">${T.esc(qLabel[c.field] ? qLabel[c.field] + ": " : "")}<b>${T.esc((parts[1] || "").replace(/^إجابة النموذج: /, ""))}</b></span>${c.form_level != null ? " → " + T.chipLvl(c.form_level) : ""}</div><div class="chip amber">⇄ ${t("تعارض — يُستخدم الأدنى", "contradiction — the lower is used")}</div></div>`;
			}
			if (c.source === "cv_quote") return `<span class="src cv">${t("من السيرة", "from the CV")}</span> <span class="quote" data-tai="hilite" data-key="${c.key}">${T.q(c.evidence)}</span>`;
			const conf = c.cv_quote ? `<div style="margin-top:4px"><span class="src cv">${c.confirmed_by_cv ? t("تؤكده السيرة", "confirmed by CV") : t("من السيرة", "from the CV")}${c.cv_level != null ? " · " + c.cv_level : ""}</span> <span class="quote" data-tai="hilite" data-key="${c.key}">${T.q(c.cv_quote)}</span></div>` : "";
			return `<span class="src form">${t("إجابة النموذج", "form answer")}</span> <span class="quote none">${T.esc(qLabel[c.field] ? qLabel[c.field] + ": " : "")}<b>${T.esc(c.evidence)}</b></span>${conf}`;
		};
		const crit = r.criteria.map((c) => `<tr><td>${T.esc(c.text)}</td><td>${T.chipMand(c.mandatory)}</td><td class="num">${c.weight}%</td><td>${T.chipLvl(c.effective_level)} <span class="hint">${rubricText(c.key, c.effective_level)}</span>${c.overridden_level != null ? ` <span class="tag-hr" title="${T.esc(c.override_reason)}">${t("تعديل HR", "HR edit")}</span><div class="hint">${t("مستوى الذكاء:", "AI level:")} ${c.missing_evidence ? t("دليل ناقص", "missing") : c.level} · ${T.esc(c.override_by)}: ${T.esc(c.override_reason)}</div>` : ""}</td><td>${evCell(c)}</td><td><button class="btn sm" data-tai="override" data-key="${c.key}" data-text="${T.esc(c.text)}" data-level="${c.effective_level}">${t("إلغاء الحكم", "Override")}</button></td></tr>`).join("");
		const strengths = (r.strengths || []).map((x) => `<div class="chip green" style="margin:3px 2px">${T.esc(x.text)} · ${x.level}</div>`).join("") || `<p class="hint">${t("لا شيء", "none")}</p>`;
		const gaps = (r.gaps || []).map((x) => `<div class="chip ${x.missing ? "amber" : "red"}" style="margin:3px 2px">${T.esc(x.text)} · ${x.missing ? t("دليل ناقص", "missing") : x.level}</div>`).join("") || `<p class="hint">${t("لا شيء", "none")}</p>`;
		const raise = (r.raise_score || []).length ? `<ul class="ul">${r.raise_score.map((x) => `<li>${x.missing ? t("تقديم دليل على", "Provide evidence for") : t("إثبات المستوى 100 في", "Prove level 100 in")} «${T.esc(x.text)}»: <b class="num">+${T.fmt1(x.points)}</b> ${t("نقطة", "points")}</li>`).join("")}</ul>` : `<p class="hint">${t("الدرجة كاملة", "Full score")}</p>`;
		const rankTxt = r.rank ? `${T.N(r.rank)} ${t("من", "of")} ${T.N(r.ranked_total)}` : "—";
		const notRanked = r.rank ? "" : `<div class="hint">${r.eligibility === "not_eligible" ? t("غير مرتَّب — غير مستوفٍ", "Not ranked — not eligible") : r.duplicate_of ? t("غير مرتَّب — طلب مكرر", "Not ranked — duplicate") : r.current === false ? t("غير مرتَّب — نتيجة قديمة", "Not ranked — stale") : t("غير مرتَّب — يحتاج مراجعة", "Not ranked — needs review")}</div>`;
		const vers = r.versions || {};
		const cv = r.cv;
		html += `
		<div class="card"><h2>${t("تقييم الذكاء الاصطناعي", "AI assessment")} <span class="chip blue">${t("قراءة فقط — لا يغيّر حالة الطلب", "read-only — never changes the status")}</span> ${T.flagChips((r.flags || []).filter((f) => f !== "hr_override"))}</h2>
			${(r.flags || []).includes("cv_partial_read") ? `<div class="note strong">⚠ <b>${t("السيرة قُرئت جزئيًا:", "The CV was read partially:")}</b> ${t("رد النموذج الأول تجاوز حد الطول، فأُعيدت القراءة على أول نصف النص فقط. أدلة السيرة تغطي ذلك الجزء وحده.", "the model's first answer overran its length budget, so the CV was re-read from its first half only. The CV evidence covers that part alone.")}</div>` : ""}
			${(r.flags || []).includes("cv_unreadable") || T.cvNote ? `<div class="note danger">⚠ <b>${t("السيرة الذاتية لم تُقرأ — التقييم من إجابات النموذج فقط.", "The CV was not read — assessed from the form answers only.")}</b> ${T.esc(T.cvNote || (cv && cv.error) || "")}</div>` : ""}
			${cv && cv.weak_lines && cv.weak_lines.length ? `<div class="note strong">◌ ${T.N(cv.weak_lines.length)} ${t("من أسطر السيرة ضعيفة القراءة (ثقة أقل من 80%) واستُبعدت من الأدلة.", "CV lines were read with low confidence (under 80%) and were excluded from the evidence.")}</div>` : ""}
			<div class="aihead">
				<div class="kpi"><small>${t("الأهلية", "Eligibility")}</small>${T.chipElig(r.eligibility)}</div>
				<div class="kpi"><small>${t("الدرجة", "Score")} <code>ai_score</code></small><b class="score ${r.eligibility === "not_eligible" ? "off" : r.band}">${T.N(T.fmt1(r.score))}</b> <span class="hint">/ 100</span><div>${T.chipBand(r.band, r.eligibility)}</div></div>
				<div class="kpi"><small>${t("التغطية", "Coverage")}</small><b>${T.N(T.pct(r.coverage))}</b>${r.needs_review ? `<div><span class="chip amber">${t("يحتاج مراجعة", "Needs review")}</span></div>` : ""}</div>
				<div class="kpi"><small>${t("الترتيب في الشاغر", "Rank in opening")}</small><b>${rankTxt}</b>${notRanked}</div>
			</div>
			<div class="grid2"><div><b class="lbl">${t("أسباب الأهلية (تُفحص في الكود)", "Eligibility reasons (checked in code)")}</b><ul class="ul">${checks || `<li>${t("لا شروط إلزامية لهذا الشاغر", "No hard rules for this opening")}</li>`}</ul></div><div><b class="lbl">${t("الملخص", "Summary")}</b><div class="summary">${T.mix(r.summary)}</div></div></div>
			${(r.flags || []).includes("mandatory_zero") ? `<div class="note danger">${t("معيار إلزامي في المستوى 0 ← الفئة «منخفضة» بغض النظر عن الدرجة.", "A mandatory criterion at level 0 → band Low regardless of the score.")}</div>` : ""}
			${(r.flags || []).includes("contradiction") ? `<div class="note strong">⇄ ${t("تعارض بين الإجابة والسيرة: يُستخدم المستوى الأدنى المدعوم بالدليل، والطلب يحتاج مراجعة بشرية.", "Answer vs CV contradiction: the lower evidenced level is used and the application needs human review.")}</div>` : ""}
			${T.disclaimer()}
		</div>
		<div class="card"><h2>${t("مراحل المعالجة", "Processing stages")} <small>${t("الوقت الكلي", "total")} ${((vers.total_ms || 0) / 1000).toFixed(1)}s · ${T.esc(vers.model || "")}</small>${cv && cv.status === "ready" ? ` <button class="btn sm primary" data-tai="cv" style="margin-inline-start:auto">◫ ${t("تحليل السيرة", "CV analysis")}</button>` : ""}</h2>${T.stagesHtml(r.stages)}</div>
		<div class="card"><h2>${t("نقاط القوة والنواقص", "Strengths and gaps")}</h2><div class="grid3"><div><b class="lbl">${t("نقاط القوة", "Strengths")} <span class="hint">(75–100)</span></b>${strengths}</div><div><b class="lbl">${t("النواقص", "Gaps")} <span class="hint">(0–25 ${t("أو دليل ناقص", "or missing")})</span></b>${gaps}</div><div><b class="lbl">${t("ما الذي يرفع درجته", "What would raise the score")}</b>${raise}</div></div></div>
		<div class="card"><h2>${t("المعايير والأدلة", "Criteria and evidence")} <small>AI Assessment Evidence</small></h2>
			<table><thead><tr><th>${t("المعيار", "Criterion")}</th><th>${t("النوع", "Type")}</th><th>${t("الوزن", "W")}</th><th>${t("المستوى", "Level")}</th><th>${t("الدليل", "Evidence")}</th><th></th></tr></thead><tbody>${crit}</tbody></table>
			<div class="audit"><span>${t("النموذج", "model")}: <code>${T.esc(vers.model)}</code></span><span>${t("الموجّه", "prompt")}: <code>${T.esc(vers.prompt)}</code></span><span>${t("نسخة المعايير", "profile version")}: <code>v${r.job_version}</code></span><span>${t("بصمة المدخلات", "input hash")}: <code>${T.esc(String(r.input_hash || "").slice(0, 23))}…</code></span><span>${t("تاريخ التقييم", "evaluated on")}: ${T.fd(r.completed_at)}</span></div>${T.disclaimer()}</div>
		${T.cvPanelHtml(r)}`;
		return `<div class="tai">${html}${T.decisionHtml(d)}</div>`;
	};

	T.cvPanelHtml = (r) => {
		const t = T.t;
		const cv = r.cv;
		if (!cv && T.cvNote) return `<div class="card"><h2>${t("السيرة الذاتية", "CV")}</h2><div class="note strong">${T.esc(T.cvNote)}</div></div>`;
		if (!cv) return `<div class="card"><h2>${t("السيرة الذاتية", "CV")}</h2><p class="hint">${t("لم يرفع المتقدم سيرة ذاتية. التقييم من إجابات النموذج فقط.", "No CV uploaded. Assessed from the form answers only.")}</p></div>`;
		if (cv.status !== "ready") return `<div class="card"><h2>${t("السيرة الذاتية", "CV")}</h2><div class="note strong">${t("تعذّرت قراءة الملف:", "The file could not be read:")} ${T.esc(cv.error)}</div></div>`;
		const quotes = (r.criteria || []).map((c) => ({ q: c.cv_quote || (c.source === "cv_quote" || c.contradiction ? String(c.evidence || "").split(" | ")[0] : ""), key: c.key })).filter((x) => x.q);
		let h = T.esc(cv.redacted_text || "");
		h = h.replace(/\[سطر ضعيف القراءة — مستبعد من الأدلة\]/g, (m) => `<mark class="weak" title="${t("ثقة القراءة أقل من 80%: لا يُقبل كدليل", "read confidence under 80%: not accepted as evidence")}">${m}</mark>`);
		quotes.forEach(({ q, key }) => { const eq = T.esc(q); if (eq && h.includes(eq)) h = h.replace(eq, `<mark class="${T.hiliteKey === key ? "hot" : ""}" id="tai-q-${key}">${eq}</mark>`); });
		return `<div class="card"><h2>${t("نص السيرة كما يراه النموذج (بعد إخفاء الهوية)", "CV text as the model sees it (redacted)")} <small>${T.method(cv.method)}${cv.ocr_confidence != null ? " · " + t("ثقة OCR", "OCR confidence") + " " + T.pct(cv.ocr_confidence) : ""}</small> <button class="btn sm" data-tai="cv" style="margin-inline-start:auto">◫ ${t("تحليل السيرة", "CV analysis")}</button></h2><div class="cvtext">${h}</div><p class="hint">${t("الاقتباسات المظلّلة هي أدلة السيرة. انقر اقتباسًا في جدول المعايير لإبرازه.", "Highlighted quotes are the CV evidence. Click a quote in the criteria table to highlight it.")}</p></div>`;
	};

	T.decisionHtml = (d) => {
		const t = T.t;
		const dec = d.decision || {};
		return `<div class="card"><h2>${t("قرار الموارد البشرية", "HR decision")} <small>${t("الحالة لا تتغيّر إلا بيد مستخدم مخوّل وبسبب مكتوب", "the status changes only by an authorised user with a written reason")}</small></h2>
			<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span>${t("الحالة الحالية", "Current status")}: ${T.chipStatus(d.status)}</span>
			<button class="btn ok" data-tai="decide" data-status="Shortlisted">${t("ترشيح للمقابلة", "Shortlist")}</button><button class="btn warn" data-tai="decide" data-status="Hold">${t("تعليق", "Hold")}</button><button class="btn danger" data-tai="decide" data-status="Rejected">${t("رفض", "Reject")}</button></div>
			${dec.by ? `<div class="hint" style="margin-top:8px">${t("آخر قرار", "Last decision")}: <b>${T.esc(dec.by)}</b> · ${T.fd(dec.on)} — ${T.esc(dec.reason)}</div>` : ""}</div>`;
	};

	/* ------------------------------------------------------------------ CV analysis */
	T.confCls = (c) => (c >= 0.9 ? "hi" : c >= 0.8 ? "mid" : "lo");
	T.cvAnalysisHtml = (d, state) => {
		const t = T.t;
		state = state || {};
		const lay = d.layout || { pages: [], lines: [] };
		const pages = lay.pages || [];
		const P = state.page || 0;
		const pg = pages[P] || { w: 1, h: 1 };
		const selBoxes = new Set();
		const selLines = new Set();
		if (state.sel && d.quote_boxes && d.quote_boxes[state.sel]) d.quote_boxes[state.sel].forEach(([li, bi]) => { selLines.add(li); selBoxes.add(li + ":" + bi); });
		if (state.line != null) selLines.add(state.line);
		const rects = (lay.lines || []).map((ln, li) => (ln.p !== P ? "" : (ln.boxes && ln.boxes.length ? ln.boxes : [[...ln.b, ln.c, ln.t]]).map((b, bi) => {
			const hit = selBoxes.has(li + ":" + bi) || selBoxes.has(li + ":-1") || state.line === li;
			return `<rect class="ocrbox ${T.confCls(b[4])} ${hit ? "hit" : ""}" x="${b[0]}" y="${b[1]}" width="${Math.max(1, b[2] - b[0])}" height="${Math.max(1, b[3] - b[1])}" data-tai="cvline" data-line="${li}"><title>${T.esc(b[5] || ln.t)} — ${Math.round((b[4] != null ? b[4] : ln.c) * 100)}%</title></rect>`;
		}).join(""))).join("");
		const img = d.page_images && d.page_images[P];
		const viewer = img ? `<div class="pageview"><img src="${T.esc(img)}" alt="page ${P + 1}"><svg viewBox="0 0 ${pg.w} ${pg.h}" preserveAspectRatio="none">${rects}</svg></div>` : `<p class="hint">${t("لا توجد صورة للصفحة", "No page image")}</p>`;
		const pager = pages.length > 1 ? `<div class="seg" style="margin-bottom:8px">${pages.map((_, i) => `<button class="${i === P ? "on" : ""}" data-tai="cvpage" data-p="${i}">${t("صفحة", "Page")} ${i + 1}</button>`).join("")}</div>` : "";
		const isOcr = d.ocr_confidence != null;
		const weak = new Set(d.weak_lines || []);
		const minPct = Math.round((d.min_confidence != null ? d.min_confidence : 0.8) * 100);
		const lines = (lay.lines || []).map((ln, li) => `<div class="ocrline ${selLines.has(li) ? "hit" : ""} ${weak.has(li) ? "weak" : ""}" data-tai="cvline" data-line="${li}"><span class="cf ${T.confCls(ln.c)}">${isOcr ? Math.round(ln.c * 100) + "%" : t("نص", "text")}</span><span class="ln">${T.esc(ln.t)}</span>${weak.has(li) ? `<span class="chip grey">${t("ضعيف — لا يُقبل كدليل", "weak — not evidence")}</span>` : ""}</div>`).join("");
		const tokenize = (x) => T.esc(x).replace(/\[[^\]]{1,20}\]/g, (m) => `<mark class="tok">${m}</mark>`);
		const pairs = d.redaction_pairs && d.redaction_pairs.length
			? `<table class="redact"><thead><tr><th>${t("قبل — النص كما استُخرج", "Before — as extracted")}</th><th>${t("بعد — ما يصل إلى النموذج اللغوي", "After — what reaches the language model")}</th></tr></thead><tbody>${d.redaction_pairs.filter(([a, b]) => a || b).map(([a, b]) => `<tr class="${a !== b ? "chg" : ""}"><td>${T.esc(a)}</td><td>${tokenize(b)}</td></tr>`).join("")}</tbody></table>`
			: `<div class="grid2"><div><b class="lbl">${t("قبل", "Before")}</b><div class="cvtext">${T.esc(d.raw_text || "")}</div></div><div><b class="lbl">${t("بعد", "After")}</b><div class="cvtext">${tokenize(d.redacted_text || "")}</div></div></div>`;
		const counts = d.redaction && d.redaction.counts ? Object.entries(d.redaction.counts).map(([k, v]) => `<span class="chip">${T.esc(T.redactLabel(k))} · ${T.N(v)}</span>`).join(" ") : `<span class="hint">${t("لم يُعثر على بيانات شخصية", "no personal data found")}</span>`;
		const ev = (d.criteria || []).filter((c) => d.quote_boxes && d.quote_boxes[c.key]).map((c) => `<div class="evq ${state.sel === c.key ? "on" : ""}" data-tai="cvsel" data-key="${c.key}"><b>${T.esc(c.text)}</b> ${T.chipLvl(c.cv_level != null ? c.cv_level : c.effective_level)}<div class="quote">${T.q(c.cv_quote || String(c.evidence || "").split(" | ")[0])}</div></div>`).join("");
		const avg = isOcr ? T.pct(d.ocr_confidence) : t("طبقة نصية (100%)", "text layer (100%)");
		return `<div class="tai"><div class="aihead"><div class="kpi"><small>${t("طريقة الاستخراج", "Method")}</small><b style="font-size:15px">${T.method(d.extraction_method)}</b><div class="hint"><bdi class="num">${T.esc(d.extraction_method || "")}</bdi></div></div><div class="kpi"><small>${t("الصفحات / الأسطر", "Pages / lines")}</small><b>${T.N(pages.length)} / ${T.N((lay.lines || []).length)}</b></div><div class="kpi"><small>${t("ثقة القراءة", "Read confidence")}</small><b style="font-size:17px">${avg}</b></div><div class="kpi"><small>${t("حروف", "Characters")}</small><b>${T.N(d.chars || 0)}</b></div></div>
			<div class="split" style="grid-template-columns:1.1fr 1fr"><div class="card"><h2>${t("الملف الأصلي", "Original file")} <small>${t("مربع لكل سطر أو مقطع بلون الثقة", "one box per line or segment, coloured by confidence")}</small></h2>${pager}${viewer}<div class="legend"><span class="cf hi">≥ 90%</span><span class="cf mid">80–89%</span><span class="cf lo">&lt; ${minPct}% — ${t("لا يُقبل كدليل", "not evidence")}</span><span class="cf hitc">${t("دليل محدد", "selected evidence")}</span></div>${weak.size ? `<div class="note strong">◌ ${T.N(weak.size)} ${t("سطر ضعيف القراءة: لا يُعرض على النموذج ولا يُقبل كدليل، ويظهر هنا للمراجعة البشرية فقط.", "weak lines: not shown to the model and never accepted as evidence; shown here for human review only.")}</div>` : ""}</div>
			<div><div class="card"><h2>${t("النص المستخرج", "Extracted text")} <small>${t("انقر سطرًا لإبرازه على الصورة", "click a line to locate it on the page")}</small></h2><div class="ocrlines">${lines || '<p class="hint">—</p>'}</div></div>
			${ev ? `<div class="card"><h2>${t("أدلة السيرة", "CV evidence")} <small>${t("انقر دليلًا لتظليله في النص والصورة", "click to highlight it in the text and on the page")}</small></h2>${ev}</div>` : ""}</div></div>
			<div class="card"><h2>${t("إخفاء الهوية: قبل وبعد", "Redaction: before and after")} <small>${counts}</small></h2>${pairs}<div class="note">${t("الاسم والهاتف والبريد والهوية وتاريخ الميلاد والجنسية والجنس والعنوان تُستبدل برموز قبل أي نموذج لغوي. النموذج يرى عمود «بعد» فقط.", "Name, phone, e-mail, ID, date of birth, nationality, gender and address are replaced by tokens before any language model. The model only sees the after column.")}</div></div></div>`;
	};

	/* ------------------------------------------------------------------ pages */
	T.pageSetup = (page) => {
		$(page.wrapper).find(".page-head").addClass("tai-head");
		page.add_inner_button(T.lang() === "ar" ? "English" : "عربي", () =>
			frappe.xcall("frappe.client.set_value", { doctype: "User", name: frappe.session.user, fieldname: "language", value: T.lang() === "ar" ? "en" : "ar" }).then(() => window.location.reload())
		);
	};

	/* ------------------------------------------------------------------ compare (feature 10) */
	T.compareHtml = (d) => {
		const t = T.t;
		const apps = d.applicants;
		const res = apps.map((a) => a.result || {});
		const byKey = res.map((r) => { const m = {}; (r.criteria || []).forEach((c) => (m[c.key] = c)); return m; });
		const best = (key) => Math.max(...byKey.map((m) => (m[key] ? m[key].effective_level : -1)));
		const ev = (c) => {
			if (!c) return `<span class="hint">—</span>`;
			if (c.missing_evidence && c.overridden_level == null) return `<span class="src missing">${t("دليل ناقص", "missing evidence")}</span>`;
			const q = c.source === "cv_quote" ? `<span class="src cv">${t("من السيرة", "from the CV")}</span> ${T.q(String(c.evidence || "").split(" | ")[0])}` : `<span class="src form">${t("إجابة النموذج", "form answer")}</span> <b>${T.esc(c.evidence)}</b>`;
			const conf = c.cv_quote && c.source !== "cv_quote" ? `<div class="hint"><span class="src cv">${t("تؤكده السيرة", "confirmed by CV")}</span> ${T.q(c.cv_quote)}</div>` : "";
			return `${q}${conf}${c.contradiction ? ` <span class="chip amber">⇄ ${t("تعارض", "contradiction")}</span>` : ""}`;
		};
		const head = apps.map((a, i) => `<th><a href="${talent_ai.formUrl("Job Applicant", a.applicant)}">${T.esc(a.applicant_name)}</a><div style="margin-top:4px"><b class="score ${res[i].eligibility === "not_eligible" ? "off" : res[i].band}">${T.N(T.fmt1(res[i].score))}</b> ${T.chipBand(res[i].band, res[i].eligibility)}</div><div class="hint">${t("الترتيب", "rank")} ${res[i].rank ? T.N(res[i].rank) : "—"} · ${t("تغطية", "cov.")} ${T.pct(res[i].coverage)} · ${T.chipElig(res[i].eligibility)}</div></th>`).join("");
		const rows = (d.criteria || []).map((c) => {
			const b = best(c.key);
			return `<tr><td><b>${T.esc(c.text)}</b><div class="hint">${c.weight}%${c.mandatory ? " · " + t("إلزامي", "mandatory") : ""}</div></td>${byKey.map((m) => { const x = m[c.key]; const lv = x ? x.effective_level : null; return `<td class="${lv != null && lv === b && b > 0 ? "best" : ""}">${T.chipLvl(lv)} <div style="margin-top:4px">${ev(x)}</div></td>`; }).join("")}</tr>`;
		}).join("");
		const list = (key, cls) => res.map((r) => `<td>${(r[key] || []).map((x) => `<div class="chip ${cls}" style="margin:2px">${T.esc(x.text)}</div>`).join("") || '<span class="hint">—</span>'}</td>`).join("");
		return `<div class="tai"><div class="note">${t("مقارنة معيارًا بمعيار بالأدلة نفسها. الأعلى في كل معيار مظلّل. القرار لـ HR.", "Criterion by criterion with the same evidence. The highest per criterion is shaded. HR decides.")}</div>
			<div class="tscroll"><table class="cmptable"><thead><tr><th>${t("المعيار", "Criterion")}</th>${head}</tr></thead><tbody>${rows}
			<tr><td><b>${t("نقاط القوة", "Strengths")}</b></td>${list("strengths", "green")}</tr><tr><td><b>${t("النواقص", "Gaps")}</b></td>${list("gaps", "red")}</tr>
			<tr><td><b>${t("الملخص", "Summary")}</b></td>${res.map((r) => `<td class="hint">${T.esc(r.summary || "")}</td>`).join("")}</tr></tbody></table></div>${T.disclaimer()}</div>`;
	};
	T.openCompare = (names) => {
		const d = new frappe.ui.Dialog({ title: T.t("مقارنة المتقدمين", "Compare applicants"), size: "extra-large" });
		d.$body.html(`<div class="tai"><span class="spin"></span></div>`);
		d.show();
		T.call("compare", { applicants: JSON.stringify(names) }).then((r) => d.$body.html(T.compareHtml(r))).catch((e) => d.$body.html(`<div class="tai"><div class="note danger">${T.esc(e.message || e)}</div></div>`));
	};

	T.openCvAnalysis = (applicant) => {
		const d = new frappe.ui.Dialog({ title: T.t("تحليل السيرة الذاتية", "CV analysis"), size: "extra-large" });
		const $body = d.$body;
		$body.html(`<div class="tai"><span class="spin"></span> ${T.t("جارٍ التحميل…", "Loading…")}</div>`);
		d.show();
		const state = { page: 0, sel: null, line: null };
		T.call("cv_analysis", { applicant }).then((data) => {
			const draw = () => $body.html(T.cvAnalysisHtml(data, state));
			draw();
			$body.on("click", "[data-tai]", (e) => {
				const el = e.currentTarget.dataset;
				if (el.tai === "cvpage") state.page = Number(el.p);
				else if (el.tai === "cvsel") { state.sel = state.sel === el.key ? null : el.key; state.line = null; }
				else if (el.tai === "cvline") { const li = Number(el.line); state.line = state.line === li ? null : li; state.sel = null; }
				else return;
				draw();
			});
		}).catch((e) => $body.html(`<div class="tai"><div class="note danger">${T.esc(e.message || e)}</div></div>`));
	};
})();

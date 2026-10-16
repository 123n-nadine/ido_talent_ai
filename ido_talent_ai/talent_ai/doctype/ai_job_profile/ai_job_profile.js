// AI Job Profile: live weights total (approval blocked unless 100%), impact preview before approval,
// «اقتراح معايير AI» (draft only), «نسخ من قالب المسمى الوظيفي», version history.
frappe.ui.form.on("AI Job Profile", {
	refresh(frm) {
		const T = talent_ai;
		const t = T.t;
		talent_ai_profile.help(frm);
		if (frm.is_new()) return;
		frm.add_custom_button(t("اعتماد", "Approve"), () => talent_ai_profile.approve(frm)).addClass("btn-primary");
		if (frm.doc.job_opening && frm.doc.version) {
			frm.add_custom_button(t("معاينة الأثر", "Impact preview"), () => talent_ai_profile.impact(frm, false), "Talent AI");
		}
		frm.add_custom_button(t("اقتراح معايير AI", "Suggest criteria (AI)"), () => talent_ai_profile.ai_draft(frm), "Talent AI");
		frm.add_custom_button(t("نسخ من قالب المسمى الوظيفي", "Copy from designation template"), () => talent_ai_profile.copy_template(frm), "Talent AI");
		if (frm.doc.job_opening) {
			frm.add_custom_button(t("ترتيب المتقدمين", "Ranking"), () => frappe.set_route("ai-ranking", { opening: frm.doc.job_opening }), "Talent AI");
		}
		frm.set_intro("");
		if (frm.doc.is_ai_draft) frm.set_intro(t("هذه المعايير مسودة اقترحها الذكاء الاصطناعي. راجعها وعدّلها ثم اعتمدها؛ لا تُستخدم قبل الاعتماد.", "These criteria are an AI draft. Review, edit, then approve; nothing is used before approval."), "orange");
		else if (frm.doc.status === "Draft" && frm.doc.version) frm.set_intro(t(`تعديلات غير معتمدة. الفرز ما زال يستخدم النسخة v${frm.doc.version} حتى تعتمد النسخة الجديدة.`, `Unapproved edits. Screening still uses v${frm.doc.version} until the new version is approved.`), "orange");
	},
	criteria_on_form_rendered(frm) { talent_ai_profile.help(frm); },
});

frappe.ui.form.on("AI Job Criterion", {
	weight(frm) { talent_ai_profile.help(frm); },
	criteria_remove(frm) { talent_ai_profile.help(frm); },
	criteria_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		["0", "25", "50", "75", "100"].forEach((l) => { if (!row["rubric_" + l]) row["rubric_" + l] = ""; });
		talent_ai_profile.help(frm);
	},
});

// global so tests and other scripts can reach it (Frappe evaluates form scripts in a function)
const talent_ai_profile = (window.talent_ai_profile = {
	total(frm) {
		return Math.round((frm.doc.criteria || []).reduce((s, c) => s + (Number(c.weight) || 0), 0) * 10) / 10;
	},

	help(frm) {
		const T = talent_ai;
		const t = T.t;
		const f = frm.fields_dict.criteria_help;
		if (!f) return;
		const tot = talent_ai_profile.total(frm);
		const ok = Math.abs(tot - 100) < 0.001;
		const pct = Math.min(100, tot);
		const vers = (frm.doc.versions || []).slice().sort((a, b) => b.version - a.version);
		f.$wrapper.html(`<div class="tai">
			<div class="card" style="margin:0 0 10px"><div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
				<b>${t("مجموع الأوزان", "Weights total")}</b><span class="chip ${ok ? "green" : "red"}"><span class="dot"></span><bdi class="num">${tot}%</bdi> / 100%</span>
				<div class="progress" style="flex:1;min-width:140px"><i style="width:${pct}%;background:${ok ? "var(--green)" : "var(--red)"}"></i></div>
				${ok ? "" : `<span class="hint" style="color:var(--red)">${t("لا يمكن الاعتماد قبل أن يكون المجموع 100% بالضبط", "Approval is blocked until the total is exactly 100%")}</span>`}
				<span class="chip ${frm.doc.status === "Approved" ? "green" : "amber"}">${frm.doc.status === "Approved" ? t("معتمد", "Approved") : t("مسودة", "Draft")} · v${frm.doc.version || 0}</span>
			</div>
			<div class="hint" style="margin-top:6px">${t("كل معيار يُقيَّم على مستويات ثابتة 0 / 25 / 50 / 75 / 100 بوصف مكتوب لكل مستوى. الدرجة = Σ(الوزن × المستوى) / 100 وتُحسب في الكود. الشروط الإلزامية (الجنسية، الطول، الوزن، العمر) تُفحص في الكود ولا يراها النموذج اللغوي.", "Each criterion is judged on fixed levels 0 / 25 / 50 / 75 / 100 with a written rubric. Score = Σ(weight × level) / 100, computed in code. Hard rules (nationality, height, weight, age) are checked in code and never shown to the language model.")}</div>
			<div class="hint">${t("«قاعدة» المستوى في الإجابات المنظمة: أرقام مثل <code>&gt;= 3</code> أو <code>&gt; 5</code>، أو خيارات مفصولة بـ <code>|</code>. الإجابة الفارغة تعني «لم يُجب» وليست صفرًا.", "Level “hint” for structured answers: numbers like <code>&gt;= 3</code> or <code>&gt; 5</code>, or options separated by <code>|</code>. A blank answer means “not answered”, never zero.")}</div></div>
			${vers.length ? `<div class="card" style="margin:0"><b class="lbl">${t("النسخ المعتمدة", "Approved versions")}</b><table><thead><tr><th>v</th><th>${t("اعتمدها", "Approved by")}</th><th>${t("التاريخ", "Date")}</th><th>${t("الأوزان", "Weights")}</th></tr></thead><tbody>${vers.map((v) => `<tr><td class="num">v${v.version}</td><td>${T.esc(v.approved_by)}</td><td>${T.fd(v.approved_on)}</td><td class="num">${T.esc(v.weights)}</td></tr>`).join("")}</tbody></table></div>` : ""}
		</div>`);
	},

	approve(frm) {
		const T = talent_ai;
		const t = T.t;
		if (Math.abs(talent_ai_profile.total(frm) - 100) > 0.001) {
			frappe.msgprint({ title: t("لا يمكن الاعتماد", "Cannot approve"), indicator: "red", message: t(`مجموع الأوزان ${talent_ai_profile.total(frm)}% — يجب أن يكون 100% بالضبط.`, `The weights total ${talent_ai_profile.total(frm)}% — it must be exactly 100%.`) });
			return;
		}
		const go = () => {
			const run = () =>
				frappe.xcall("ido_talent_ai.profile.approve", { name: frm.doc.name }).then((r) => {
					frappe.show_alert({ indicator: "green", message: r.new_version ? t(`اعتُمدت النسخة v${r.version}` + (r.stale ? ` — ${r.stale} نتيجة أصبحت قديمة` : ""), `Version v${r.version} approved` + (r.stale ? ` — ${r.stale} results are now stale` : "")) : t("لا تغيير منذ آخر اعتماد", "No change since the last approval") });
					frm.reload_doc();
				});
			if (frm.doc.job_opening && frm.doc.version) talent_ai_profile.impact(frm, true, run);
			else frappe.confirm(t("اعتماد هذه المعايير؟ بعد الاعتماد يبدأ فرز الطلبات الجديدة بها.", "Approve these criteria? New applications will be screened with them."), run);
		};
		if (frm.is_dirty()) frm.save().then(go);
		else go();
	},

	impact(frm, approving, onapprove) {
		const T = talent_ai;
		const t = T.t;
		const draft = JSON.stringify({ criteria: (frm.doc.criteria || []).map((c) => { const x = Object.assign({}, c); delete x.name; return x; }) });
		const d = new frappe.ui.Dialog({ title: t("معاينة الأثر قبل الاعتماد", "Impact preview before approval"), size: "extra-large" });
		d.$body.html(`<div class="tai"><span class="spin"></span> ${t("جارٍ الحساب…", "Computing…")}</div>`);
		if (approving) d.set_primary_action(t("اعتماد النسخة الجديدة", "Approve the new version"), () => { d.hide(); onapprove(); });
		d.show();
		frappe.xcall("ido_talent_ai.profile.impact_preview", { name: frm.doc.name, draft }).then((r) => {
			const rows = r.rows || [];
			const s = r.summary || {};
			const band = (b, e) => T.chipBand(b, e);
			const body = rows.map((x) => `<tr class="${x.rank_changed || x.band_changed ? "chg" : ""}"><td>${x.applicant ? `<a href="${talent_ai.formUrl("Job Applicant", x.applicant)}">${T.esc(x.applicant_name)}</a>` : T.esc(x.applicant_name)}</td>
				<td class="num">${T.fmt1(x.old_score)} → <b>${T.fmt1(x.new_score)}</b> <span class="${x.delta > 0 ? "up" : x.delta < 0 ? "down" : ""}">${x.delta > 0 ? "+" : ""}${x.delta || ""}</span></td>
				<td>${band(x.old_band, x.eligibility)} → ${band(x.new_band, x.eligibility)}</td>
				<td class="num">${x.old_rank || "—"} → <b>${x.new_rank || "—"}</b></td>
				<td>${x.rankable ? "" : `<span class="hint">${x.eligibility === "not_eligible" ? t("غير مستوفٍ", "not eligible") : t("يحتاج مراجعة", "needs review")}</span>`}</td></tr>`).join("");
			d.$body.html(`<div class="tai">
				<div class="kpis5" style="grid-template-columns:repeat(4,minmax(0,1fr))"><div class="kpi"><small>${t("متقدمون", "Applicants")}</small><b>${T.N(s.applicants || 0)}</b></div><div class="kpi"><small>${t("تغيّرت درجتهم", "Score changed")}</small><b>${T.N(s.score_changed || 0)}</b></div><div class="kpi"><small>${t("تغيّرت فئتهم", "Band changed")}</small><b>${T.N(s.band_changed || 0)}</b></div><div class="kpi"><small>${t("تغيّر ترتيبهم", "Rank changed")}</small><b>${T.N(s.rank_changed || 0)}</b></div></div>
				<div class="note">${t("المستويات المحكوم بها تبقى كما هي (لا يُستدعى النموذج)، وتتغيّر الأوزان والإلزامية فقط. معيار جديد يُحسب «دليل ناقص» حتى يُعاد التقييم. بعد الاعتماد تصبح النتائج الحالية «قديمة» حتى تُعاد.", "Judged levels are kept (no model call); only weights and mandatory flags change. A new criterion counts as missing evidence until re-scored. After approval current results become stale until re-scored.")}</div>
				${rows.length ? `<table><thead><tr><th>${t("المتقدم", "Applicant")}</th><th>${t("الدرجة", "Score")}</th><th>${t("الفئة", "Band")}</th><th>${t("الترتيب", "Rank")}</th><th></th></tr></thead><tbody>${body}</tbody></table>` : `<p class="hint">${t("لا توجد نتائج مكتملة لهذا الشاغر بعد.", "No completed results for this opening yet.")}</p>`}
				${T.disclaimer()}</div>`);
		}).catch((e) => d.$body.html(`<div class="tai"><div class="note danger">${T.esc(e.message || e)}</div></div>`));
	},

	ai_draft(frm) {
		const T = talent_ai;
		const t = T.t;
		const run = () => {
			frappe.dom.freeze(t("الذكاء يقترح معايير… (قد يستغرق دقيقة)", "The AI is drafting criteria… (may take a minute)"));
			frappe.xcall("ido_talent_ai.profile.draft_criteria", { name: frm.doc.name })
				.then((r) => { frappe.show_alert({ indicator: "orange", message: t(`مسودة: ${r.criteria} معايير — راجعها قبل الاعتماد`, `Draft: ${r.criteria} criteria — review before approval`) }); frm.reload_doc(); })
				.finally(() => frappe.dom.unfreeze());
		};
		const save_then = () => (frm.is_dirty() ? frm.save().then(run) : run());
		if ((frm.doc.criteria || []).length) frappe.confirm(t("سيستبدل الاقتراح المعايير الحالية في المسودة (النسخ المعتمدة لا تتغيّر). متابعة؟", "The suggestion replaces the current draft criteria (approved versions are kept). Continue?"), save_then);
		else save_then();
	},

	copy_template(frm) {
		const T = talent_ai;
		const t = T.t;
		frappe.xcall("ido_talent_ai.profile.templates_for", { name: frm.doc.name }).then((rows) => {
			if (!rows.length) {
				frappe.msgprint(t("لا يوجد قالب معتمد لهذا المسمى الوظيفي. أنشئ ملف معايير بدون شاغر وفعّل «قالب» ثم اعتمده.", "No approved template for this designation. Create a profile without an opening, tick “Template”, then approve it."));
				return;
			}
			const d = new frappe.ui.Dialog({
				title: t("نسخ من قالب المسمى الوظيفي", "Copy from designation template"),
				fields: [{ fieldname: "template", fieldtype: "Select", label: t("القالب", "Template"), reqd: 1, options: rows.map((r) => ({ value: r.name, label: `${r.title} (${r.designation || "—"}) v${r.version}` })) }],
				primary_action_label: t("نسخ كمسودة", "Copy as draft"),
				primary_action(v) {
					d.hide();
					const run = () => frappe.xcall("ido_talent_ai.profile.copy_from_template", { name: frm.doc.name, template: v.template }).then(() => frm.reload_doc());
					frm.is_dirty() ? frm.save().then(run) : run();
				},
			});
			d.show();
		});
	},
});

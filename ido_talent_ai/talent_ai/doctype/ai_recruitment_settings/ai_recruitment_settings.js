// AI Recruitment Settings: provider/model/OCR/timeout/retries live in the engine (decision 13).
// The form shows the engine state and pulls the current values; saving pushes changes back.
frappe.ui.form.on("AI Recruitment Settings", {
	refresh(frm) {
		const T = talent_ai;
		frm.add_custom_button(T.t("تحديث من المحرك", "Refresh from engine"), () =>
			frappe.xcall("ido_talent_ai.talent_ai.doctype.ai_recruitment_settings.ai_recruitment_settings.refresh_from_engine").then((r) => {
				frm.reload_doc();
				frappe.show_alert({ indicator: r.health.ok ? "green" : "red", message: r.health.ok ? T.t("المحرك متصل", "Engine connected") : T.t("المحرك غير متاح", "Engine unavailable") });
			})
		);
		talent_ai_settings.status(frm);
	},
});

const talent_ai_settings = {
	status(frm) {
		const T = talent_ai;
		const t = T.t;
		const $w = frm.fields_dict.engine_status.$wrapper;
		$w.html(`<div class="tai"><span class="spin"></span></div>`);
		frappe.xcall("ido_talent_ai.api.engine_settings")
			.then((r) => {
				const s = r.settings || {};
				const h = r.health || {};
				const row = (k, v) => `<tr><td class="hint">${k}</td><td>${v}</td></tr>`;
				const ok = (b, note) => `<span class="chip ${b ? "green" : "red"}"><span class="dot"></span>${b ? t("جاهز", "ready") : t("غير جاهز", "not ready")}</span> <span class="hint">${T.esc(note || "")}</span>`;
				$w.html(`<div class="tai"><div class="card" style="margin:0"><h2>${t("حالة المحرك", "Engine status")} ${ok(h.ok)}</h2><table>
					${row(t("مزوّد الذكاء", "AI provider"), `<code>${T.esc(s.ai_provider)}</code> · <code>${T.esc(s.ai_model)}</code> ${ok(s.provider_ready, s.provider_note)}`)}
					${row(t("قراءة الصور (OCR)", "OCR"), `<code>${T.esc(s.ocr_provider)}</code> ${ok(s.ocr_ready, s.ocr_note)}`)}
					${row(t("الموجّه", "Judge prompt"), `<code>${T.esc(s.judge_prompt)}</code>`)}
					${row(t("المهلة / المحاولات", "Timeout / retries"), `${s.llm_timeout_s}s / ${s.max_retries}`)}
					${row(t("الحقائق المسموح إرسالها", "Facts allowed to be sent"), (s.allowed_facts || []).map((x) => `<code>${T.esc(x)}</code>`).join(" "))}
					${row(t("رابط النتيجة (callback)", "Callback URL"), `<code>${T.esc(s.callback_url || "—")}</code> ${s.callback_secret_set ? `<span class="chip green">${t("موقّع HMAC", "HMAC signed")}</span>` : `<span class="chip red">${t("بلا سر", "no secret")}</span>`}`)}
				</table><div class="hint">${t("المزوّد السحابي مُعطّل حتى يُضاف مفتاح في المحرك. مفتاح المحرك لا يصل إلى المتصفح أبدًا.", "The cloud provider stays disabled until a key is added in the engine. The engine key never reaches the browser.")}</div></div></div>`);
			})
			.catch((e) => $w.html(`<div class="tai"><div class="note danger">${t("تعذّر الاتصال بالمحرك", "Could not reach the engine")}: ${T.esc(e.message || e)}</div></div>`));
	},
};

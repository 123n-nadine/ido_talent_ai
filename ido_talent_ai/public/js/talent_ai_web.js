// Website: on an HRMS job page whose «Apply» goes to the AI form, show the eligibility rules as
// Arabic sentences and a note about the screening questions (the HRMS template is not modified).
(function () {
	if (!/^\/jobs\//.test(window.location.pathname)) return;
	const link = document.querySelector('a[href*="/ai-apply/new?job_title="]');
	if (!link) return;
	const job = new URL(link.href, window.location.origin).searchParams.get("job_title");
	fetch(`/api/method/ido_talent_ai.api.job_requirements?job_title=${encodeURIComponent(job)}`, { headers: { Accept: "application/json" } })
		.then((r) => r.json())
		.then((j) => {
			const m = j.message || {};
			if (!m.requirements) return;
			const ar = (document.documentElement.lang || "ar").startsWith("ar");
			const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
			const box = document.createElement("div");
			box.className = "tai-reqs";
			box.style.cssText = "border:1px solid var(--border-color,#e2e6ef);border-radius:12px;padding:14px 18px;margin:16px 0;background:#fff";
			box.innerHTML = (m.requirements.length ? `<b>${ar ? "شروط التقديم" : "Eligibility requirements"}</b><ul style="margin:8px 0 0;line-height:1.9">${m.requirements.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "") +
				`<p style="margin:10px 0 0;color:var(--text-muted,#667)">${ar ? `ستُسأل ${m.questions} أسئلة قصيرة عن خبرتك ومهاراتك. السيرة الذاتية اختيارية.` : `You will answer ${m.questions} short questions about your experience and skills. The CV is optional.`}</p>`;
			const anchor = document.getElementById("sticky-div");
			if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(box, anchor);
		})
		.catch(() => {});
})();

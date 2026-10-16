frappe.listview_settings["AI Recruitment Job"] = {
	add_fields: ["status", "attempts", "max_attempts"],
	get_indicator(doc) {
		const c = { Queued: "gray", Running: "blue", Completed: "green", Failed: "red" }[doc.status] || "gray";
		return [__(doc.status), c, "status,=," + doc.status];
	},
	onload(listview) {
		frappe.realtime.on("talent_ai_batch", () => {
			if (frappe.get_route_str().startsWith("List/AI Recruitment Job")) listview.refresh();
		});
	},
};

frappe.ui.form.on("Chat Session", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.llm_provider) {
			frappe.db.get_list("LLM Provider", {
				filters: { is_default: 1, is_enabled: 1 },
				fields: ["name"],
				limit: 1,
			}).then((rows) => {
				if (rows && rows.length) {
					frm.set_value("llm_provider", rows[0].name);
				}
			});
		}
	},
});

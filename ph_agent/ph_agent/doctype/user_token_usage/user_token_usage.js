// Copyright (c) 2026, KAINOTOMO PH LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("User Token Usage", {
	refresh: function (frm) {
		// Hide Per-User Cost Overrides section for non-System Manager users
		if (!frappe.user_roles.includes("System Manager")) {
			frm.set_df_property("section_overrides", "hidden", 1);
			frm.set_df_property("input_cost_over_per_1m", "hidden", 1);
			frm.set_df_property("output_cost_over_per_1m", "hidden", 1);
			frm.set_df_property("cache_hit_cost_over_per_1m", "hidden", 1);
		}
	}
});

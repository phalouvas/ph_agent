frappe.ui.form.on("Chat Session", {
	onload_post_render(frm) {
		// This runs after the form is fully rendered
		if (frm.is_new()) {
			// Small delay to ensure all form elements are ready
			setTimeout(() => {
				this.sync_with_provider(frm);
			}, 300);
		}
	},
	
	refresh(frm) {
		// Also sync on refresh for new forms
		if (frm.is_new()) {
			this.sync_with_provider(frm);
		}
	},
	
	llm_provider(frm) {
		// When provider changes, sync streaming and suggestions
		this.sync_with_provider(frm);
	},
	
	sync_with_provider(frm) {
		// Only sync for new/unsaved forms
		if (!frm.is_new() && !frm.doc.__islocal) {
			return;
		}
		
		const provider_name = frm.doc.llm_provider;
		
		if (!provider_name) {
			// Get default provider
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "LLM Provider",
					filters: { is_default: 1, is_enabled: 1 },
					fields: ["name", "supports_streaming", "enable_suggestions", "system_prompt"],
					limit: 1
				},
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						const provider = r.message[0];
						frm.set_value("llm_provider", provider.name);
						frm.set_value("enable_streaming", provider.supports_streaming ? 1 : 0);
						frm.set_value("enable_suggestions", provider.enable_suggestions ? 1 : 0);
						frm.set_value("system_prompt", provider.system_prompt);
					}
				}
			});
		} else {
			// Get provider details
			frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "LLM Provider",
					filters: { name: provider_name },
					fieldname: ["supports_streaming", "enable_suggestions", "system_prompt"]
				},
				callback: function(r) {
					if (r.message) {
						const provider = r.message;
						frm.set_value("enable_streaming", provider.supports_streaming ? 1 : 0);
						frm.set_value("enable_suggestions", provider.enable_suggestions ? 1 : 0);
						frm.set_value("system_prompt", provider.system_prompt);
					}
				}
			});
		}
	},
});

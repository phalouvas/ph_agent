// Copyright (c) 2026, KAINOTOMO PH LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Persona", {
	/**
	 * On form refresh, show provider defaults as field descriptions
	 * so the user knows what values will be inherited.
	 */
	refresh: function (frm) {
		_show_provider_hints(frm);
	},

	/**
	 * When the user picks a different default LLM provider, fetch its
	 * settings and display them as hints on the corresponding fields.
	 */
	default_llm_provider: function (frm) {
		_show_provider_hints(frm);
	},
});

/**
 * Fetch the selected (or default) LLM Provider's settings and show them
 * as field descriptions so the user can see what will be inherited.
 */
function _show_provider_hints(frm) {
	const provider_name =
		frm.doc.default_llm_provider ||
		frm.fields_dict.default_llm_provider?.get_value();

	if (!provider_name) {
		// Try to find the system default provider
		frappe.db
			.get_list("LLM Provider", {
				filters: { is_default: 1, is_enabled: 1 },
				fields: ["name", "temperature", "enable_thinking", "supports_streaming", "enable_suggestions", "system_prompt"],
				limit: 1,
			})
			.then((providers) => {
				if (providers.length) {
					_set_field_hints(frm, providers[0]);
				}
			});
		return;
	}

	frappe.db
		.get_value(
			"LLM Provider",
			provider_name,
			["temperature", "enable_thinking", "supports_streaming", "enable_suggestions", "system_prompt"]
		)
		.then((r) => {
			if (r.message) {
				_set_field_hints(frm, r.message);
			}
		});
}

/**
 * Update field descriptions with inherited provider values.
 */
function _set_field_hints(frm, provider) {
	const hints = {
		temperature: provider.temperature
			? __("Provider default: {0}", [provider.temperature])
			: __("Provider default: 1.0"),
		enable_thinking: provider.enable_thinking
			? __("Provider default: Enabled")
			: __("Provider default: Disabled"),
		enable_streaming: provider.supports_streaming
			? __("Provider default: Enabled")
			: __("Provider default: Disabled"),
		enable_suggestions: provider.enable_suggestions
			? __("Provider default: Enabled")
			: __("Provider default: Disabled"),
		system_prompt: provider.system_prompt
			? __("Provider default: {0}", [provider.system_prompt.substring(0, 80) + (provider.system_prompt.length > 80 ? "…" : "")])
			: __("Provider default: (none)"),
	};

	// Only show hints for fields the user hasn't explicitly set
	if (!frm.doc.temperature && frm.doc.temperature !== 0) {
		frm.set_df_property("temperature", "description", hints.temperature);
	}
	if (!frm.doc.enable_thinking) {
		frm.set_df_property("enable_thinking", "description", hints.enable_thinking);
	}
	if (!frm.doc.enable_streaming) {
		frm.set_df_property("enable_streaming", "description", hints.enable_streaming);
	}
	if (!frm.doc.enable_suggestions) {
		frm.set_df_property("enable_suggestions", "description", hints.enable_suggestions);
	}
	if (!frm.doc.system_prompt) {
		frm.set_df_property("system_prompt", "description", hints.system_prompt);
	}
}

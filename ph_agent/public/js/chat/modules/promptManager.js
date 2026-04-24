/**
 * PH Agent Chat Prompt Manager
 *
 * Manages saved prompts with {{variable}} substitution.
 * Provides UI for browsing, creating, editing, and inserting saved prompts.
 */

window.phAgent.promptManager = window.phAgent.promptManager || (function() {
	// Private variables
	let _chat = null;
	let _container = null;
	let _promptsCache = null;

	// ── Utility ────────────────────────────────────────────────────

	/**
	 * Escape HTML special characters to prevent XSS.
	 * @param {string} text - Text to escape
	 * @returns {string} Escaped text
	 */
	function escapeHtml(text) {
		if (text === null || text === undefined) return "";
		return String(text)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#039;");
	}

	/**
	 * Extract unique {{variable}} names from a prompt template.
	 * @param {string} content - Prompt template text
	 * @returns {string[]} Array of unique variable names
	 */
	function getVariableNames(content) {
		const regex = /\{\{(\w+)\}\}/g;
		const names = [];
		const seen = {};
		let match;
		while ((match = regex.exec(content)) !== null) {
			if (!seen[match[1]]) {
				seen[match[1]] = true;
				names.push(match[1]);
			}
		}
		return names;
	}

	/**
	 * Replace {{variable}} placeholders with provided values.
	 * @param {string} content - Template with {{variable}} placeholders
	 * @param {Object} values - Map of variable name -> replacement text
	 * @returns {string} Filled-in text
	 */
	function fillVariables(content, values) {
		return content.replace(/\{\{(\w+)\}\}/g, (match, name) => {
			return values[name] !== undefined ? values[name] : match;
		});
	}

	/**
	 * Insert text into the chat textarea (shadow DOM aware).
	 * @param {string} text - Text to insert
	 */
	function insertIntoTextarea(text) {
		const root = _chat.shadowRoot || _container;
		const textarea = root.querySelector("textarea");
		if (!textarea) return;

		// Set the native value and dispatch input event so Vue picks it up
		const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
			window.HTMLTextAreaElement.prototype,
			"value"
		).set;
		nativeInputValueSetter.call(textarea, text);
		textarea.dispatchEvent(new Event("input", { bubbles: true }));
		textarea.focus();
	}

	// ── API Calls ──────────────────────────────────────────────────

	/**
	 * Fetch saved prompts from the server.
	 * @param {string|null} category - Optional category filter
	 * @returns {Promise<Array>} List of prompt objects
	 */
	function fetchPrompts(category) {
		const params = {};
		if (category) params.category = category;
		return frappe.call({
			method: "ph_agent.api.chat.list_saved_prompts",
			args: params,
		}).then(r => {
			_promptsCache = r.message || [];
			return _promptsCache;
		});
	}

	/**
	 * Save (create or update) a prompt.
	 * @param {Object} data - { title, content, category, is_favorite, prompt_id? }
	 * @returns {Promise}
	 */
	function savePrompt(data) {
		return frappe.call({
			method: "ph_agent.api.chat.save_prompt",
			args: data,
		});
	}

	/**
	 * Delete a prompt.
	 * @param {string} promptId - Prompt name/ID
	 * @returns {Promise}
	 */
	function deletePrompt(promptId) {
		return frappe.call({
			method: "ph_agent.api.chat.delete_prompt",
			args: { prompt_id: promptId },
		});
	}

	/**
	 * Increment usage count for a prompt.
	 * @param {string} promptId - Prompt name/ID
	 * @returns {Promise}
	 */
	function incrementUsage(promptId) {
		return frappe.call({
			method: "ph_agent.api.chat.increment_prompt_usage",
			args: { prompt_id: promptId },
		});
	}

	// ── Dialogs ────────────────────────────────────────────────────

	/**
	 * Open the main prompt library dialog.
	 */
	function openPromptLibrary() {
		fetchPrompts().then(prompts => {
			let dialogHtml = buildPromptListHtml(prompts);

			const dialog = new frappe.ui.Dialog({
				title: __("Saved Prompts"),
				fields: [
					{
						fieldname: "search",
						fieldtype: "Data",
						label: __("Search prompts"),
						placeholder: __("Search by title or content..."),
					},
					{
						fieldname: "prompt_list",
						fieldtype: "HTML",
						label: __("Prompts"),
					},
				],
				primary_action_label: __("Manage Prompts"),
				primary_action: () => {
					dialog.hide();
					openManageDialog();
				},
			});

			// Set initial HTML
			dialog.fields_dict.prompt_list.$wrapper.html(dialogHtml);

			// Wire search
			dialog.fields_dict.search.$input.on("input", function() {
				const q = $(this).val().toLowerCase();
				const filtered = prompts.filter(p =>
					p.title.toLowerCase().includes(q) ||
					p.content.toLowerCase().includes(q) ||
					(p.category || "").toLowerCase().includes(q)
				);
				dialog.fields_dict.prompt_list.$wrapper.html(buildPromptListHtml(filtered));
				wirePromptClicks(dialog, prompts);
			});

			wirePromptClicks(dialog, prompts);
			dialog.show();
		}).catch(err => {
			console.error("Failed to load prompts:", err);
			frappe.show_alert({
				message: __("Failed to load saved prompts."),
				indicator: "red",
			});
		});
	}

	/**
	 * Build HTML for the prompt list.
	 * @param {Array} prompts - List of prompt objects
	 * @returns {string} HTML string
	 */
	function buildPromptListHtml(prompts) {
		if (!prompts || prompts.length === 0) {
			return `<div class="ph-prompts-empty">
				<p style="text-align:center;padding:40px 20px;color:#6b7280;">
					${__("No saved prompts yet.")}
				</p>
				<p style="text-align:center;padding:0 20px 20px;color:#9ca3af;font-size:12px;">
					${__("Click 'Manage Prompts' below to create your first prompt.")}
				</p>
			</div>`;
		}

		// Group: favorites first, then by category
		const favorites = prompts.filter(p => p.is_favorite);
		const nonFavorites = prompts.filter(p => !p.is_favorite);

		// Group non-favorites by category
		const categorized = {};
		const uncategorized = [];
		nonFavorites.forEach(p => {
			if (p.category) {
				if (!categorized[p.category]) categorized[p.category] = [];
				categorized[p.category].push(p);
			} else {
				uncategorized.push(p);
			}
		});

		let html = '<div class="ph-prompts-list">';

		// Favorites section
		if (favorites.length > 0) {
			html += `<div class="ph-prompts-section">
				<div class="ph-prompts-section-title">⭐ ${__("Favorites")}</div>`;
			favorites.forEach(p => {
				html += buildPromptCard(p);
			});
			html += '</div>';
		}

		// Categorized sections
		Object.keys(categorized).sort().forEach(cat => {
			html += `<div class="ph-prompts-section">
				<div class="ph-prompts-section-title">📁 ${__("Category")}: ${escapeHtml(cat)}</div>`;
			categorized[cat].forEach(p => {
				html += buildPromptCard(p);
			});
			html += '</div>';
		});

		// Uncategorized
		if (uncategorized.length > 0) {
			html += `<div class="ph-prompts-section">
				<div class="ph-prompts-section-title">📄 ${__("Other")}</div>`;
			uncategorized.forEach(p => {
				html += buildPromptCard(p);
			});
			html += '</div>';
		}

		html += '</div>';
		return html;
	}

	/**
	 * Build a single prompt card HTML.
	 * @param {Object} prompt - Prompt object
	 * @returns {string} HTML
	 */
	function buildPromptCard(prompt) {
		const preview = prompt.content.length > 80
			? prompt.content.substring(0, 80) + "…"
			: prompt.content;
		const hasVars = /\{\{\w+\}\}/.test(prompt.content);
		const varBadge = hasVars
			? '<span class="ph-prompt-var-badge">' + __("variables") + "</span>"
			: "";
		const usageBadge = prompt.usage_count > 0
			? `<span class="ph-prompt-usage-badge">${prompt.usage_count}</span>`
			: "";

		return `<div class="ph-prompt-card" data-prompt-id="${escapeHtml(prompt.name)}">
			<div class="ph-prompt-card-title">
				${prompt.is_favorite ? "⭐ " : ""}${escapeHtml(prompt.title)}
				${varBadge}
				${usageBadge}
			</div>
			<div class="ph-prompt-card-preview">${escapeHtml(preview)}</div>
		</div>`;
	}

	/**
	 * Wire click handlers on prompt cards.
	 * @param {Object} dialog - Frappe Dialog instance
	 * @param {Array} prompts - Full prompts list for lookup
	 */
	function wirePromptClicks(dialog, prompts) {
		const container = dialog.fields_dict.prompt_list.$wrapper;
		container.find(".ph-prompt-card").on("click", function() {
			const promptId = $(this).data("prompt-id");
			const prompt = prompts.find(p => p.name === promptId);
			if (prompt) {
				dialog.hide();
				selectPrompt(prompt);
			}
		});
	}

	/**
	 * Handle prompt selection: check for variables, show fill dialog if needed.
	 * @param {Object} prompt - Prompt object
	 */
	function selectPrompt(prompt) {
		const variables = getVariableNames(prompt.content);

		if (variables.length === 0) {
			// No variables — insert directly
			insertIntoTextarea(prompt.content);
			incrementUsage(prompt.name);
			frappe.show_alert({
				message: __("Prompt '{0}' inserted", [prompt.title]),
				indicator: "green",
			});
			return;
		}

		// Has variables — show fill dialog
		openVariableFillDialog(prompt, variables);
	}

	/**
	 * Open dialog to fill {{variable}} values before inserting.
	 * @param {Object} prompt - Prompt object
	 * @param {string[]} variables - Array of variable names
	 */
	function openVariableFillDialog(prompt, variables) {
		// Build preview with highlighted placeholders
		const previewHtml = prompt.content.replace(
			/\{\{(\w+)\}\}/g,
			'<span class="ph-var-placeholder">{{$1}}</span>'
		);

		// Build fields for each variable
		const fields = [
			{
				fieldname: "preview",
				fieldtype: "HTML",
				label: __("Preview"),
			},
		];

		variables.forEach(v => {
			fields.push({
				fieldname: v,
				fieldtype: "Small Text",
				label: v.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
				placeholder: "{{" + v + "}}",
			});
		});

		const dialog = new frappe.ui.Dialog({
			title: __("Fill Variables: {0}", [prompt.title]),
			fields: fields,
			primary_action_label: __("Insert"),
			primary_action: (values) => {
				const filled = fillVariables(prompt.content, values);
				insertIntoTextarea(filled);
				incrementUsage(prompt.name);
				dialog.hide();
				frappe.show_alert({
					message: __("Prompt '{0}' inserted", [prompt.title]),
					indicator: "green",
				});
			},
		});

		// Set preview HTML
		dialog.fields_dict.preview.$wrapper.html(
			`<div class="ph-var-preview-box">${previewHtml}</div>`
		);

		dialog.show();
	}

	/**
	 * Open the full management dialog (CRUD).
	 */
	function openManageDialog() {
		fetchPrompts().then(prompts => {
			let html = buildManageListHtml(prompts);

			const dialog = new frappe.ui.Dialog({
				title: __("Manage Saved Prompts"),
				fields: [
					{
						fieldname: "prompt_list",
						fieldtype: "HTML",
						label: __("Prompts"),
					},
				],
				primary_action_label: __("New Prompt"),
				primary_action: () => {
					dialog.hide();
					openEditDialog(null, () => {
						// Refresh manage dialog after create
						openManageDialog();
					});
				},
			});

			dialog.fields_dict.prompt_list.$wrapper.html(html);

			// Wire edit/delete buttons
			const container = dialog.fields_dict.prompt_list.$wrapper;
			container.find(".ph-prompt-manage-edit").on("click", function() {
				const promptId = $(this).data("prompt-id");
				const prompt = prompts.find(p => p.name === promptId);
				if (prompt) {
					dialog.hide();
					openEditDialog(prompt, () => {
						openManageDialog();
					});
				}
			});

			container.find(".ph-prompt-manage-delete").on("click", function() {
				const promptId = $(this).data("prompt-id");
				const prompt = prompts.find(p => p.name === promptId);
				if (prompt) {
					frappe.confirm(
						__("Are you sure you want to delete the prompt '{0}'?", [prompt.title]),
						() => {
							deletePrompt(promptId).then(() => {
								frappe.show_alert({
									message: __("Prompt deleted"),
									indicator: "green",
								});
								_promptsCache = null;
								// Refresh the manage dialog
								dialog.hide();
								openManageDialog();
							}).catch(err => {
								console.error("Failed to delete prompt:", err);
								frappe.show_alert({
									message: __("Failed to delete prompt"),
									indicator: "red",
								});
							});
						}
					);
				}
			});

			dialog.show();
		}).catch(err => {
			console.error("Failed to load prompts:", err);
			frappe.show_alert({
				message: __("Failed to load saved prompts."),
				indicator: "red",
			});
		});
	}

	/**
	 * Build HTML for the manage prompt list.
	 * @param {Array} prompts - List of prompt objects
	 * @returns {string} HTML
	 */
	function buildManageListHtml(prompts) {
		if (!prompts || prompts.length === 0) {
			return `<div class="ph-prompts-empty">
				<p style="text-align:center;padding:40px 20px;color:#6b7280;">
					${__("No saved prompts yet. Click 'New Prompt' to create one.")}
				</p>
			</div>`;
		}

		let html = '<div class="ph-prompts-manage-list">';
		prompts.forEach(p => {
			const preview = p.content.length > 60
				? p.content.substring(0, 60) + "…"
				: p.content;
			html += `<div class="ph-prompt-manage-row">
				<div class="ph-prompt-manage-info">
					<div class="ph-prompt-manage-title">
						${p.is_favorite ? "⭐ " : ""}${escapeHtml(p.title)}
						${p.category ? `<span class="ph-prompt-cat-badge">${escapeHtml(p.category)}</span>` : ""}
					</div>
					<div class="ph-prompt-manage-preview">${escapeHtml(preview)}</div>
				</div>
				<div class="ph-prompt-manage-actions">
					<button class="btn btn-default btn-xs ph-prompt-manage-edit" data-prompt-id="${escapeHtml(p.name)}">
						${__("Edit")}
					</button>
					<button class="btn btn-danger btn-xs ph-prompt-manage-delete" data-prompt-id="${escapeHtml(p.name)}">
						${__("Delete")}
					</button>
				</div>
			</div>`;
		});
		html += '</div>';
		return html;
	}

	/**
	 * Open edit/create dialog for a single prompt.
	 * @param {Object|null} prompt - Existing prompt to edit, or null for new
	 * @param {Function} onSave - Callback after successful save
	 */
	function openEditDialog(prompt, onSave) {
		const isNew = !prompt;
		const fields = [
			{
				fieldname: "title",
				fieldtype: "Data",
				label: __("Title"),
				reqd: 1,
				default: prompt ? prompt.title : "",
			},
			{
				fieldname: "content",
				fieldtype: "Small Text",
				label: __("Content"),
				reqd: 1,
				default: prompt ? prompt.content : "",
				description: __("Use {{variable_name}} for placeholders that will be filled when inserting."),
			},
			{
				fieldname: "category",
				fieldtype: "Data",
				label: __("Category"),
				default: prompt ? prompt.category : "",
				description: __("Optional category for organizing prompts."),
			},
			{
				fieldname: "is_favorite",
				fieldtype: "Check",
				label: __("Favorite"),
				default: prompt ? prompt.is_favorite : 0,
			},
		];

		const dialog = new frappe.ui.Dialog({
			title: isNew ? __("New Prompt") : __("Edit Prompt"),
			fields: fields,
			primary_action_label: __("Save"),
			primary_action: (values) => {
				if (!values.title || !values.title.trim()) {
					frappe.show_alert({
						message: __("Title is required."),
						indicator: "red",
					});
					return;
				}
				if (!values.content || !values.content.trim()) {
					frappe.show_alert({
						message: __("Content is required."),
						indicator: "red",
					});
					return;
				}

				const data = {
					title: values.title,
					content: values.content,
					category: values.category || "",
					is_favorite: values.is_favorite ? 1 : 0,
				};
				if (!isNew) {
					data.prompt_id = prompt.name;
				}

				savePrompt(data).then(r => {
					dialog.hide();
					_promptsCache = null;
					frappe.show_alert({
						message: isNew ? __("Prompt created") : __("Prompt saved"),
						indicator: "green",
					});
					if (onSave) onSave();
				}).catch(err => {
					console.error("Failed to save prompt:", err);
					frappe.show_alert({
						message: __("Failed to save prompt."),
						indicator: "red",
					});
				});
			},
		});

		dialog.show();
	}

	// ── Public API ─────────────────────────────────────────────────

	return {
		/**
		 * Initialize the prompt manager.
		 * @param {HTMLElement} chat - Vue Advanced Chat component
		 * @param {HTMLElement} container - Container element
		 */
		init: function(chat, container) {
			_chat = chat;
			_container = container;

			// Add tooltip and class to the custom action button after shadow DOM is ready
			setTimeout(() => {
				const root = _chat.shadowRoot || _container;
				// Find the custom action button (has the deleted/trash icon SVG)
				const actionBtn = root.querySelector("#vac-icon-deleted")?.closest(".vac-svg-button");
				if (actionBtn) {
					actionBtn.classList.add("ph-saved-prompts-btn");
					actionBtn.setAttribute("title", __("Saved Prompts"));
				}
			}, 1000);
		},

		/**
		 * Open the prompt library dialog.
		 */
		openPromptLibrary: openPromptLibrary,

		/**
		 * Open the manage prompts dialog.
		 */
		openManageDialog: openManageDialog,

		/**
		 * Get variable names from a template string.
		 * @param {string} content - Template text
		 * @returns {string[]} Variable names
		 */
		getVariableNames: getVariableNames,

		/**
		 * Clear the prompts cache (forces refresh on next open).
		 */
		clearCache: function() {
			_promptsCache = null;
		},
	};
})();

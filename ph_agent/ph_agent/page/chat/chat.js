frappe.pages["chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "AI Chat",
		single_column: true,
	});

	// ── Persona Selector ────────────────────────────────────────────
	let personaSelector = null;
	let personaList = [];

	function loadPersonas() {
		return frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Persona",
				filters: { user: frappe.session.user },
				fields: ["name", "persona_name", "icon", "color", "is_default"],
				order_by: "modified desc",
			},
		}).then((r) => {
			personaList = r.message || [];
			return personaList;
		});
	}

	function renderPersonaSelector() {
		if (!personaList.length) return;

		const currentPersona = window.phAgent?.state?.getActivePersona?.();
		const current = personaList.find(p => p.name === currentPersona) || personaList.find(p => p.is_default) || personaList[0];

		if (current && current.name !== currentPersona) {
			window.phAgent.state.setActivePersona(current.name);
		}

		if (!personaSelector) {
			personaSelector = $(`
				<select class="form-control persona-selector" style="display:inline-block;width:auto;min-width:140px;margin-left:8px;font-size:12px;height:28px;padding:2px 8px;">
				</select>
			`);
			personaSelector.on("change", function () {
				const selected = $(this).val();
				window.phAgent.state.setActivePersona(selected);
				// Reload rooms for the new persona
				if (window.phAgent?.roomService) {
					window.phAgent.roomService.loadRooms().then((rooms) => {
						const state = window.phAgent.state;
						const stateRooms = state.getRooms();
						if (stateRooms.length > 0) {
							const chat = document.querySelector("vue-advanced-chat");
							if (chat) {
								chat.setAttribute("room-id", "");
								state.setActiveRoomId(null);
								const fetchMessagesEvent = new CustomEvent("fetch-messages", {
									detail: [stateRooms[0]]
								});
								chat.dispatchEvent(fetchMessagesEvent);
							}
						}
					});
				}
			});
			// Insert after the primary action button
			$(page.page_actions).find(".btn-primary").after(personaSelector);
		}

		// Populate options
		const optionsHtml = personaList.map(p => {
			const selected = p.name === current?.name ? "selected" : "";
			const icon = p.icon && p.icon !== "user" ? p.icon : "";
			const label = icon ? `${icon} ${p.persona_name}` : p.persona_name;
			return `<option value="${p.name}" ${selected}>${label}</option>`;
		}).join("");
		personaSelector.html(optionsHtml);
	}

	// Load personas first, then set up the rest
	loadPersonas().then(() => {
		renderPersonaSelector();
	});

	page.set_primary_action(__("New Chat"), () => {
		if (window.phAgent && window.phAgent.roomService) {
			window.phAgent.roomService.createNewSession();
		} else if (window._phChatCreateSession) {
			// Fallback to old global function if modules not loaded
			window._phChatCreateSession();
		}
	}, "add");

	// ── Temporary Mode Toggle ───────────────────────────────────────
	const tempBtn = $(`
		<button class="btn btn-default btn-sm btn-temp-mode" style="margin-left: 8px; font-size: 12px; padding: 2px 8px; height: 28px;" title="${__("Toggle Temporary (Incognito) Mode")}">
			👻 <span>${__("Temporary")}</span>
		</button>
	`);
	tempBtn.on("click", function () {
		const state = window.phAgent?.state;
		if (!state) return;
		const newMode = !state.getIsTemporaryMode();
		state.setIsTemporaryMode(newMode);
		$(this).toggleClass("btn-info", newMode).toggleClass("btn-default", !newMode);
		const label = newMode ? __("Temporary ON") : __("Temporary");
		$(this).find("span").text(label);
		frappe.show_alert({
			message: newMode ? __("Temporary mode ON — sessions will be auto-deleted on navigation") : __("Temporary mode OFF"),
			indicator: newMode ? "orange" : "green"
		});
	});
	// Initialize button state from persisted preference
	if (window.phAgent?.state?.getIsTemporaryMode?.()) {
		tempBtn.removeClass("btn-default").addClass("btn-info");
		tempBtn.find("span").text(__("Temporary ON"));
	}
	$(page.page_actions).find(".btn-primary").after(tempBtn);

	// Add summary button as a custom button in the page actions area
	// First, let's add it manually to the page actions container
	
	// Create summary button (hidden by default; shown when token % > 20)
	const summaryButton = $(`
		<button class="btn btn-default btn-sm btn-summary-conversation" style="margin-left: 8px; display: none;">
			<i class="fa fa-refresh" style="margin-right: 4px;"></i>
			${__("Summarize")}
		</button>
	`);
	
	// Add click handler — uses roomService.summarizeSession if available
	summaryButton.on("click", () => {
		const session = window.phAgent?.state?.getActiveRoomId?.();
		if (!session) {
			frappe.show_alert({
				message: __("No active chat session. Please create or select a chat first."),
				indicator: "orange"
			});
			return;
		}
		if (window.phAgent?.roomService?.summarizeSession) {
			const $summaryBtn = $(".page-actions .btn-summary-conversation");
			$summaryBtn.prop("disabled", true).html(`
				<span class="fa fa-spinner fa-spin"></span>
				<span>${__("Summarizing...")}</span>
			`);
			window.phAgent.roomService.summarizeSession(session)
				.then(() => {
					frappe.show_alert({
						message: __("Conversation summarized successfully"),
						indicator: "green"
					});
				})
				.catch((err) => {
					console.error("Failed to summarize conversation:", err);
					frappe.show_alert({
						message: __("Failed to summarize conversation"),
						indicator: "red"
					});
				})
				.finally(() => {
					$summaryBtn.prop("disabled", false).html(`
						<i class="fa fa-refresh" style="margin-right: 4px;"></i>
						${__("Summarize")}
					`);
				});
		}
	});
	
	// Add button to page actions (after the primary action)
	$(page.page_actions).append(summaryButton);

	// Mount container inside page main area
	const $container = $('<div style="height: calc(100vh - 120px);"></div>');
	const $status = $('<div id="ph-chat-status" style="height:24px;padding:0 8px;font-size:12px;color:#4f72b8;font-weight:500;line-height:24px;display:flex;align-items:center;gap:6px;justify-content:space-between;"><div style="display:flex;align-items:center;gap:6px;"><span class="ph-status-spinner" style="display:none;width:12px;height:12px;border:2px solid #c5d0e8;border-top-color:#4f72b8;border-radius:50%;animation:ph-spin 0.7s linear infinite;flex-shrink:0;"></span><span class="ph-status-text"></span><button class="ph-stop-btn" title="Stop generation" style="display:none;margin-left:4px;padding:2px 8px;font-size:11px;font-weight:600;line-height:16px;border:none;border-radius:3px;background:#e53e3e;color:#fff;cursor:pointer;flex-shrink:0;">&#9632; Stop</button></div><div class="ph-token-counter" style="font-size:11px;color:#6b7280;display:flex;align-items:center;">Tokens: <span class="ph-token-count">0</span>/<span class="ph-token-limit">0</span> (<span class="ph-token-percent">0</span>%)</div></div><style>@keyframes ph-spin{to{transform:rotate(360deg)}}.ph-stop-btn:hover{background:#c53030!important}</style>');
	
	$(page.main).append($container);
	$(page.main).append($status);

	// Load chat modules before initializing the chat
	if (window.phAgent && window.phAgent.loadAllModules) {
		window.phAgent.loadAllModules().then(() => {
			// Load vue-advanced-chat locally (via page_js hook) with CDN fallback
			if (window["vue-advanced-chat"]) {
				window["vue-advanced-chat"].register();
				initPhChat($container[0], page, $status);
			} else {
				// Fallback in case page_js didn't load the script
				$.getScript(
					"/assets/ph_agent/js/lib/vue-advanced-chat.umd.js",
					() => {
						window["vue-advanced-chat"].register();
						initPhChat($container[0], page, $status);
					}
				);
			}
		}).catch(error => {
			console.error("Failed to load chat modules:", error);
			// Fallback to original initialization even if modules fail to load
			if (window["vue-advanced-chat"]) {
				window["vue-advanced-chat"].register();
				initPhChat($container[0], page, $status);
			} else {
				$.getScript(
					"/assets/ph_agent/js/lib/vue-advanced-chat.umd.js",
					() => {
						window["vue-advanced-chat"].register();
						initPhChat($container[0], page, $status);
					}
				);
			}
		});
	} else {
		// Fallback if loader.js didn't load properly
		console.warn("phAgent loader not available, falling back to direct initialization");
		if (window["vue-advanced-chat"]) {
			window["vue-advanced-chat"].register();
			initPhChat($container[0], page, $status);
		} else {
			$.getScript(
				"/assets/ph_agent/js/lib/vue-advanced-chat.umd.js",
				() => {
					window["vue-advanced-chat"].register();
					initPhChat($container[0], page, $status);
				}
			);
		}
	}
};

/**
 * Initialize the PH Chat interface using modular architecture
 * @param {HTMLElement} container - Container element for the chat
 * @param {Object} page - Frappe page object
 * @param {jQuery} $status - Status bar jQuery element
 */
function initPhChat(container, page, $status) {
	const currentUserId = frappe.session.user;
	const agentId = "ph_agent";

	// ── Token-based Summmarize button visibility ────────────────────
	function updateSummarizeButtonVisibility() {
		const $btn = $(".page-actions .btn-summary-conversation");
		if (!$btn.length) return;
		const roomId = window.phAgent?.state?.getActiveRoomId?.();
		if (!roomId) { $btn.hide(); return; }
		window.phAgent.roomService.getTokenInfo(roomId).then((info) => {
			if (info.percentage > 20 && info.current_tokens > 0) {
				$btn.show();
			} else {
				$btn.hide();
			}
		}).catch(() => { $btn.hide(); });
	}

	// Watch for token updates to show/hide Summarize button
	frappe.realtime.on("token_update", (data) => {
		if (data.session !== window.phAgent?.state?.getActiveRoomId?.()) return;
		const $btn = $(".page-actions .btn-summary-conversation");
		if (!$btn.length) return;
		if (data.percentage > 20 && data.current_tokens > 0) {
			$btn.show();
		} else {
			$btn.hide();
		}
	});

	// ── Create Vue Advanced Chat web component ──────────────────────
	const chat = document.createElement("vue-advanced-chat");
	chat.setAttribute("height", "100%");
	chat.setAttribute("current-user-id", currentUserId);
	chat.setAttribute("show-audio", "false");
	chat.setAttribute("rooms-loaded", "false");
	chat.setAttribute("messages-loaded", "false");
	chat.setAttribute("room-actions", JSON.stringify([{ name: "deleteRoom", title: __("Delete") }]));
	chat.setAttribute("message-actions", JSON.stringify([
		{ name: "editMessage", title: __("Edit"), onlyMe: true },
		{ name: "deleteMessage", title: __("Delete") },
		{ name: "selectMessages", title: __("Select") },
		{ name: "copyMessage", title: __("Copy") },
		{ name: "regenerateMessage", title: __("Regenerate") },
	]));
	chat.setAttribute("message-selection-actions", JSON.stringify([{ name: "deleteMessages", title: __("Delete") }]));
	chat.setAttribute("room-info-enabled", "true");
	chat.setAttribute("textarea-action-enabled", "true");
	container.appendChild(chat);

	// Prevent Frappe global keyboard shortcuts (e.g. Shift+/ = "?") from
	// firing while the user is typing inside the chat component.
	container.addEventListener("keydown", (e) => e.stopPropagation());

	// ── Initialize modules with dependencies ────────────────────────
	
	// Initialize state manager
	const state = window.phAgent.state;
	
	// Initialize room service with current user, agent ID, and default persona
	const defaultPersona = state.getActivePersona();
	const roomService = window.phAgent.roomService;
	roomService.init(chat, currentUserId, agentId, defaultPersona);
	
	// Initialize UI helpers
	const uiHelpers = window.phAgent.uiHelpers;
	uiHelpers.init(chat, container, $status);
	
	// Initialize event handlers
	const eventHandlers = window.phAgent.eventHandlers;
	eventHandlers.init(chat, container, page, $status);
	
	// Initialize real-time listeners
	const realtimeListeners = window.phAgent.realtimeListeners;
	realtimeListeners.init(chat, container, $status, agentId);
	
	// Initialize prompt manager
	const promptManager = window.phAgent.promptManager;
	promptManager.init(chat, container);
	
	// Bind event handlers to the chat component
	eventHandlers.bindAll();
	
	// Register real-time listeners
	realtimeListeners.registerAllListeners();
	
	// Set up global function for creating new sessions (for backward compatibility)
	window._phChatCreateSession = () => roomService.createNewSession();
	
	// ── beforeunload: delete active temporary session on page close ──
	window.addEventListener("beforeunload", function () {
		const activeRoomId = state.getActiveRoomId();
		if (!activeRoomId) return;
		const activeRoom = state.getRoomById(activeRoomId);
		if (!activeRoom || !activeRoom.isTemporary) return;
		
		// Use sendBeacon — guaranteed delivery even when tab closes
		const url = "/api/method/ph_agent.api.chat.delete_session";
		const csrfToken = frappe.csrf_token;
		const data = new URLSearchParams({ session: activeRoomId });
		if (csrfToken) {
			data.append("csrf_token", csrfToken);
		}
		navigator.sendBeacon(url, data);
	});
	
	// ── Load initial rooms ──────────────────────────────────────────
	roomService.loadRooms().then((rooms) => {
		// Set initial active room if rooms exist
		const stateRooms = state.getRooms();
		if (stateRooms.length > 0) {
			realtimeListeners.setActiveRoomId(stateRooms[0].roomId);
			
			// Trigger fetch-messages event for the first room
			const fetchMessagesEvent = new CustomEvent("fetch-messages", {
				detail: [stateRooms[0]]
			});
			chat.dispatchEvent(fetchMessagesEvent);
			
			// Show Summarize button if token % > 20
			updateSummarizeButtonVisibility();
		}
	}).catch(error => {
		console.error("Failed to load initial rooms:", error);
		// Still mark rooms as loaded to avoid infinite loading spinner
		chat.setAttribute("rooms-loaded", "true");
	});
	
	// ── Set up periodic suggestion rendering ────────────────────────
	// Use MutationObserver to render pending suggestions when DOM updates
	const root = chat.shadowRoot || container;
	new MutationObserver(() => {
		const allSuggestions = state.getAllMessageSuggestions();
		if (Object.keys(allSuggestions).length > 0) {
			const updatedSuggestions = uiHelpers.renderPendingSuggestions(allSuggestions);
			// Update state with any suggestions that were successfully rendered
			Object.keys(allSuggestions).forEach(messageId => {
				if (!updatedSuggestions[messageId]) {
					// This suggestion was successfully rendered, remove it from state
					state.removeMessageSuggestions(messageId);
				}
			});
		}

		uiHelpers.applySummaryMessageStyles(state.getMessages());
	}).observe(root, { childList: true, subtree: true });
}
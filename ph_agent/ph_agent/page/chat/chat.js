frappe.pages["chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "AI Chat",
		single_column: true,
	});

	// ── Persona Selector ────────────────────────────────────────────
	let personaSelector = null;
	let personaCompactBtn = null;
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

	function _switchPersona(name) {
		window.phAgent.state.setActivePersona(name);
		if (window.phAgent?.roomService) {
			window.phAgent.roomService.loadRooms().then(() => {
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
	}

	function _personaIcon(p) {
		return (p.icon && p.icon !== "user") ? p.icon : "👤";
	}

	function renderPersonaSelector() {
		if (!personaList.length) return;

		const currentPersona = window.phAgent?.state?.getActivePersona?.();
		const current = personaList.find(p => p.name === currentPersona) || personaList.find(p => p.is_default) || personaList[0];

		if (current && current.name !== currentPersona) {
			window.phAgent.state.setActivePersona(current.name);
		}

		const isMobile = window.innerWidth <= 480;

		if (isMobile) {
			// ── Compact icon button on mobile ──────────────────────
			if (personaSelector) personaSelector.hide();

			if (!personaCompactBtn) {
				personaCompactBtn = $(`<button class="btn btn-default btn-sm btn-persona-compact"></button>`);
				personaCompactBtn.on("click", function (e) {
					e.stopPropagation();
					$(".ph-persona-dropdown").remove();

					const $menu = $(`<div class="ph-persona-dropdown" style="position:fixed;z-index:9999;background:#fff;border:1px solid #d1d5db;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.18);min-width:180px;padding:4px 0;"></div>`);
					personaList.forEach(p => {
						const icon = _personaIcon(p);
						const isActive = p.name === (window.phAgent?.state?.getActivePersona?.() || current?.name);
						const $item = $(`<div class="ph-persona-dropdown-item${isActive ? ' active' : ''}"><span>${icon}</span><span>${p.persona_name}</span>${isActive ? '<span class="check-mark">✓</span>' : ""}</div>`);
						$item.on("click", function () {
							$menu.remove();
							_switchPersona(p.name);
							personaCompactBtn.attr("title", p.persona_name).text(icon);
						});
						$menu.append($item);
					});

					// Position below the button
					const rect = personaCompactBtn[0].getBoundingClientRect();
					const menuLeft = Math.max(4, Math.min(rect.left, window.innerWidth - 188));
					$menu.css({ top: rect.bottom + 4, left: menuLeft });
					$("body").append($menu);

					// Close on outside click
					setTimeout(() => {
						$(document).one("click.personaDropdown", function () { $menu.remove(); });
					}, 0);
				});
				$(page.page_actions).find(".standard-actions").append(personaCompactBtn);
			}

			personaCompactBtn.show()
				.attr("title", current?.persona_name || "")
				.text(_personaIcon(current));

		} else {
			// ── Full select on desktop/tablet ──────────────────────
			if (personaCompactBtn) personaCompactBtn.hide();

			if (!personaSelector) {
				personaSelector = $(`<select class="form-control persona-selector" style="display:inline-block;width:auto;min-width:140px;margin-left:8px;font-size:12px;height:28px;padding:2px 8px;"></select>`);
				personaSelector.on("change", function () {
					_switchPersona($(this).val());
				});
				$(page.page_actions).find(".standard-actions").append(personaSelector);
			}

			personaSelector.show();
			const optionsHtml = personaList.map(p => {
				const selected = p.name === current?.name ? "selected" : "";
				const icon = _personaIcon(p);
				return `<option value="${p.name}" ${selected}>${icon} ${p.persona_name}</option>`;
			}).join("");
			personaSelector.html(optionsHtml);
		}
	}

	// Load personas first, then set up the rest
	loadPersonas().then(() => {
		renderPersonaSelector();
		// Re-render on resize (debounced) — handles orientation changes
		let _personaResizeTimer;
		$(window).on("resize.personaSelector", function () {
			clearTimeout(_personaResizeTimer);
			_personaResizeTimer = setTimeout(renderPersonaSelector, 150);
		});
	});

	page.set_primary_action(__("New Chat"), () => {
		if (window.phAgent && window.phAgent.roomService) {
			window.phAgent.roomService.createNewSession();
		} else if (window._phChatCreateSession) {
			// Fallback to old global function if modules not loaded
			window._phChatCreateSession();
		}
	}, "add");

	// ── Temporary Mode Toggle (via Frappe native add_button) ────────
	// add_button creates the button + auto-adds a menu item for mobile overflow
	const tempBtn = page.add_button("👻 " + __("Temporary"), function () {
		const state = window.phAgent?.state;
		if (!state) return;
		const activeRoomId = state.getActiveRoomId();
		if (!activeRoomId) {
			frappe.show_alert({
				message: __("No active session to toggle"),
				indicator: "orange"
			});
			return;
		}
		
		const room = state.getRoomById(activeRoomId);
		const newMode = !(room && room.isTemporary);
		
		frappe.call({
			method: "frappe.client.set_value",
			args: {
				doctype: "Chat Session",
				name: activeRoomId,
				fieldname: "is_temporary",
				value: newMode ? 1 : 0,
			},
			callback: function(r) {
				if (r.message) {
					// Update the room object in local state
					const updatedRoom = state.getRoomById(activeRoomId);
					if (updatedRoom) {
						updatedRoom.isTemporary = newMode;
						// Update room name with/without 👻 badge
						if (newMode && !updatedRoom.roomName.startsWith("👻")) {
							updatedRoom.roomName = "👻 " + updatedRoom.roomName + " (Temporary)";
						} else if (!newMode) {
							updatedRoom.roomName = updatedRoom.roomName.replace(/^👻 /, "").replace(" (Temporary)", "");
						}
						state.updateRoom(activeRoomId, { roomName: updatedRoom.roomName });
						const chat = document.querySelector("vue-advanced-chat");
						if (chat) chat.rooms = state.getRooms();
					}
					// Sync the button
					if (window._phSyncTempModeButton) {
						window._phSyncTempModeButton(newMode);
					}
					frappe.show_alert({
						message: newMode ? __("Current session marked as temporary — will be deleted on navigation") : __("Current session is no longer temporary"),
						indicator: newMode ? "orange" : "green"
					});
				}
			}
		});
	}, { btn_class: "btn-temp-mode" });
	// Restore inner span so mobile CSS can hide text while keeping icon
	tempBtn.html(`👻 <span data-text>${__("Temporary")}</span>`);
	// Move after primary action for correct visual order
	tempBtn.insertAfter(page.btn_primary);
	// Initialize button state from persisted preference
	if (window.phAgent?.state?.getIsTemporaryMode?.()) {
		tempBtn.removeClass("btn-default").addClass("btn-info");
		tempBtn.find("[data-text]").text(__("Temporary ON"));
	}

	// ── Summary Button (via Frappe native add_button) ────────────────
	// Hidden by default; shown when token % > 20
	const summaryButton = page.add_button("", () => {
		const session = window.phAgent?.state?.getActiveRoomId?.();
		if (!session) {
			frappe.show_alert({
				message: __("No active chat session. Please create or select a chat first."),
				indicator: "orange"
			});
			return;
		}
		if (window.phAgent?.roomService?.summarizeSession) {
			const $summaryBtn = $(".btn-summary-conversation");
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
						<i class="fa fa-refresh"></i>
						<span data-text>${__("Summarize")}</span>
					`);
				});
		}
	}, { btn_class: "btn-summary-conversation" });
	summaryButton.html(`<i class="fa fa-refresh"></i><span data-text>${__("Summarize")}</span>`);
	summaryButton.hide();
	summaryButton.insertAfter(tempBtn);

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

	// ── Summarize button visibility ─────────────────────────────────
	// Always visible when a session is active (not gated by token %)
	function updateSummarizeButtonVisibility() {
		const $btn = $(".btn-summary-conversation");
		if (!$btn.length) return;
		const roomId = window.phAgent?.state?.getActiveRoomId?.();
		if (roomId) {
			$btn.show();
		} else {
			$btn.hide();
		}
	}

	// Token updates no longer gate visibility — button stays visible
	// as long as a session is active.

	// ── Create Vue Advanced Chat web component ──────────────────────
	const chat = document.createElement("vue-advanced-chat");

	// ── Temporary mode button sync helper ───────────────────────────
	// Exposed globally so eventHandlers can call it on room switch.
	window._phSyncTempModeButton = function(isTemporary) {
		const $btn = $(".btn-temp-mode");
		if (!$btn.length) return;
		if (isTemporary) {
			$btn.removeClass("btn-default").addClass("btn-info");
			$btn.html(`👻 <span data-text>${__("Temporary ON")}</span>`);
		} else {
			$btn.removeClass("btn-info").addClass("btn-default");
			$btn.html(`👻 <span data-text>${__("Temporary")}</span>`);
		}
	};
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
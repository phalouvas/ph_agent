frappe.pages["chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "AI Chat",
		single_column: true,
	});

	page.set_primary_action(__("New Chat"), () => {
		if (window.phAgent && window.phAgent.roomService) {
			window.phAgent.roomService.createNewSession();
		} else if (window._phChatCreateSession) {
			// Fallback to old global function if modules not loaded
			window._phChatCreateSession();
		}
	}, "add");

	// Add summary button as a custom button in the page actions area
	// First, let's add it manually to the page actions container
	
	// Create summary button
	const summaryButton = $(`
		<button class="btn btn-default btn-sm" style="margin-left: 8px;">
			<i class="fa fa-refresh" style="margin-right: 4px;"></i>
			${__("Summarize")}
		</button>
	`);
	
	// Add click handler
	summaryButton.on("click", () => {
		// Get active session from state module
		const session = window.phAgent?.state?.getActiveRoomId?.();
		
		if (session) {
			frappe.call({
				method: "ph_agent.api.chat.summarize_conversation",
				args: {
					session: session
				},
				callback: function(response) {
					if (response.message && response.message.status === "success") {
						frappe.show_alert({
							message: __("Conversation summarized successfully"),
							indicator: "green"
						});
					}
				},
				error: function(err) {
					console.error("Failed to summarize conversation:", err);
					frappe.show_alert({
						message: __("Failed to summarize conversation"),
						indicator: "red"
					});
				}
			});
		} else {
			frappe.show_alert({
				message: __("No active chat session. Please create or select a chat first."),
				indicator: "orange"
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
	container.appendChild(chat);

	// Prevent Frappe global keyboard shortcuts (e.g. Shift+/ = "?") from
	// firing while the user is typing inside the chat component.
	container.addEventListener("keydown", (e) => e.stopPropagation());

	// ── Initialize modules with dependencies ────────────────────────
	
	// Initialize state manager
	const state = window.phAgent.state;
	
	// Initialize room service with current user and agent IDs
	const roomService = window.phAgent.roomService;
	roomService.init(chat, currentUserId, agentId);
	
	// Initialize UI helpers
	const uiHelpers = window.phAgent.uiHelpers;
	uiHelpers.init(chat, container, $status);
	
	// Initialize event handlers
	const eventHandlers = window.phAgent.eventHandlers;
	eventHandlers.init(chat, container, page, $status);
	
	// Initialize real-time listeners
	const realtimeListeners = window.phAgent.realtimeListeners;
	realtimeListeners.init(chat, container, $status, agentId);
	
	// Bind event handlers to the chat component
	eventHandlers.bindAll();
	
	// Register real-time listeners
	realtimeListeners.registerAllListeners();
	
	// Set up global function for creating new sessions (for backward compatibility)
	window._phChatCreateSession = () => roomService.createNewSession();
	
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
	}).observe(root, { childList: true, subtree: true });
}
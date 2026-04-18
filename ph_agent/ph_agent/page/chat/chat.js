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

	// Mount container inside page main area
	const $container = $('<div style="height: calc(100vh - 120px);"></div>');
	const $status = $('<div id="ph-chat-status" style="height:24px;padding:0 8px;font-size:12px;color:#4f72b8;font-weight:500;line-height:24px;display:flex;align-items:center;gap:6px;"><span class="ph-status-spinner" style="display:none;width:12px;height:12px;border:2px solid #c5d0e8;border-top-color:#4f72b8;border-radius:50%;animation:ph-spin 0.7s linear infinite;flex-shrink:0;"></span><span class="ph-status-text"></span><button class="ph-stop-btn" title="Stop generation" style="display:none;margin-left:4px;padding:2px 8px;font-size:11px;font-weight:600;line-height:16px;border:none;border-radius:3px;background:#e53e3e;color:#fff;cursor:pointer;flex-shrink:0;">&#9632; Stop</button></div><style>@keyframes ph-spin{to{transform:rotate(360deg)}}.ph-stop-btn:hover{background:#c53030!important}</style>');
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
	console.log("initPhChat called");
	const currentUserId = frappe.session.user;
	const agentId = "ph_agent";

	// ── Create Vue Advanced Chat web component ──────────────────────
	const chat = document.createElement("vue-advanced-chat");
	console.log("Chat element created:", chat);
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
	console.log("Chat element appended to container");

	// Prevent Frappe global keyboard shortcuts (e.g. Shift+/ = "?") from
	// firing while the user is typing inside the chat component.
	container.addEventListener("keydown", (e) => e.stopPropagation());

	// ── Initialize modules with dependencies ────────────────────────
	
	// Initialize state manager
	const state = window.phAgent.state;
	console.log("State manager initialized:", state);
	
	// Initialize room service with current user and agent IDs
	const roomService = window.phAgent.roomService;
	roomService.init(chat, currentUserId, agentId);
	console.log("Room service initialized");
	
	// Initialize UI helpers
	const uiHelpers = window.phAgent.uiHelpers;
	uiHelpers.init(chat, container, $status);
	console.log("UI helpers initialized");
	
	// Initialize event handlers
	const eventHandlers = window.phAgent.eventHandlers;
	eventHandlers.init(chat, container, page, $status);
	console.log("Event handlers initialized");
	
	// Initialize real-time listeners
	const realtimeListeners = window.phAgent.realtimeListeners;
	realtimeListeners.init(chat, container, $status, agentId);
	console.log("Real-time listeners initialized");
	
	// Bind event handlers to the chat component
	eventHandlers.bindAll();
	console.log("Event handlers bound");
	
	// Register real-time listeners
	realtimeListeners.registerAllListeners();
	console.log("Real-time listeners registered");
	
	// Set up global function for creating new sessions (for backward compatibility)
	window._phChatCreateSession = () => roomService.createNewSession();
	
	// ── Load initial rooms ──────────────────────────────────────────
	console.log("Starting to load rooms...");
	roomService.loadRooms().then((rooms) => {
		console.log("Rooms loaded successfully:", rooms);
		// Set initial active room if rooms exist
		const stateRooms = state.getRooms();
		console.log("State rooms:", stateRooms);
		console.log("Chat rooms property:", chat.rooms);
		console.log("Chat element:", chat);
		if (stateRooms.length > 0) {
			realtimeListeners.setActiveRoomId(stateRooms[0].roomId);
			console.log("Set active room ID:", stateRooms[0].roomId);
			
			// Trigger fetch-messages event for the first room
			console.log("Triggering fetch-messages for first room:", stateRooms[0]);
			const fetchMessagesEvent = new CustomEvent("fetch-messages", {
				detail: [stateRooms[0]]
			});
			chat.dispatchEvent(fetchMessagesEvent);
			console.log("fetch-messages event dispatched");
		} else {
			console.log("No rooms found in state");
		}
	}).catch(error => {
		console.error("Failed to load initial rooms:", error);
		// Still mark rooms as loaded to avoid infinite loading spinner
		chat.setAttribute("rooms-loaded", "true");
		console.log("Set rooms-loaded to true due to error");
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
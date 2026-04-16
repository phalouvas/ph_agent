frappe.pages["chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "AI Chat",
		single_column: true,
	});

	page.set_primary_action(__("New Chat"), () => {
		if (window._phChatCreateSession) window._phChatCreateSession();
	}, "add");

	// Mount container inside page main area
	const $container = $('<div style="height: calc(100vh - 100px);"></div>');
	$(page.main).append($container);

	// Load vue-advanced-chat from CDN, then initialise
	$.getScript(
		"https://cdn.jsdelivr.net/npm/vue-advanced-chat@2.0.4/dist/vue-advanced-chat.umd.js",
		() => {
			window["vue-advanced-chat"].register();
			initPhChat($container[0], page);
		}
	);
};

function initPhChat(container, page) {
	const currentUserId = frappe.session.user;
	const agentId = "ph_agent";

	// ── Web component ──────────────────────────────────────────────
	const chat = document.createElement("vue-advanced-chat");
	chat.setAttribute("height", "100%");
	chat.setAttribute("current-user-id", currentUserId);
	chat.setAttribute("show-audio", "false");
	chat.setAttribute("rooms-loaded", "false");
	chat.setAttribute("messages-loaded", "false");
	chat.setAttribute("room-actions", JSON.stringify([{ name: "deleteRoom", title: __("Delete") }]));
	container.appendChild(chat);

	let rooms = [];
	let messages = [];
	let activeRoomId = null;

	// ── Helper: format a Chat Message record ──────────────────────
	function fmtMsg(m) {
		const dt = new Date((m.creation || "").replace(" ", "T"));
		return {
			_id: m.name,
			content: m.content,
			senderId: m.sender_type === "User" ? currentUserId : agentId,
			username: m.sender_type === "User" ? (frappe.boot.user.full_name || currentUserId) : "AI Agent",
			timestamp: dt.toTimeString().slice(0, 5),
			date: dt.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),
			saved: true,
		};
	}

	// ── Load rooms (sessions) ──────────────────────────────────────
	function loadRooms() {
		chat.setAttribute("rooms-loaded", "false");
		frappe.db
			.get_list("Chat Session", {
				filters: { user: currentUserId, status: ["!=", "Archived"] },
				fields: ["name", "title", "modified"],
				order_by: "modified desc",
				limit: 50,
			})
			.then((sessions) => {
				rooms = sessions.map((s) => ({
					roomId: s.name,
					roomName: s.title,
					users: [
						{ _id: currentUserId, username: frappe.boot.user.full_name || currentUserId },
						{ _id: agentId, username: "AI Agent" },
					],
				}));
				chat.rooms = rooms;
				chat.setAttribute("rooms-loaded", "true");
			});
	}

	loadRooms();

	// ── Create new session ─────────────────────────────────────────
	function createNewSession() {
		frappe.call({
			method: "ph_agent.api.chat.create_session",
			callback: (r) => {
				if (!r.message) return;
				const newRoom = {
					roomId: r.message.session,
					roomName: r.message.title,
					users: [
						{ _id: currentUserId, username: frappe.boot.user.full_name || currentUserId },
						{ _id: agentId, username: "AI Agent" },
					],
				};
				rooms = [newRoom, ...rooms];
				chat.rooms = rooms;
				chat.setAttribute("room-id", r.message.session);
			},
		});
	}
	window._phChatCreateSession = createNewSession;

	// ── Event: room selected → load messages ──────────────────────
	chat.addEventListener("fetch-messages", ({ detail: [{ room }] }) => {
		if (!room.roomId) return;
		activeRoomId = room.roomId;
		chat.setAttribute("messages-loaded", "false");
		frappe.call({
			method: "ph_agent.api.chat.get_history",
			args: { session: room.roomId },
			callback: (r) => {
				messages = (r.message || []).map(fmtMsg);
				chat.messages = messages;
				chat.setAttribute("messages-loaded", "true");
			},
		});
	});

	// ── Event: user sends a message ───────────────────────────────
	chat.addEventListener("send-message", ({ detail: [{ roomId, content }] }) => {
		// Optimistic user bubble
		const tempId = "temp_" + Date.now();
		messages = [
			...messages,
			{
				_id: tempId,
				content,
				senderId: currentUserId,
				username: frappe.boot.user.full_name || currentUserId,
				timestamp: new Date().toTimeString().slice(0, 5),
				date: new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),
				saved: false,
			},
		];
		chat.messages = messages;

		frappe.call({
			method: "ph_agent.api.chat.send_message",
			args: { session: roomId, content },
			callback: (r) => {
				if (r.message) {
					// Mark user message as saved
					messages = messages.map((m) => (m._id === tempId ? { ...m, saved: true } : m));
					chat.messages = messages;
				}
			},
		});
	});

	// ── Event: + button → new session ─────────────────────────────
	chat.addEventListener("add-room", () => createNewSession());

	// ── Event: room action (delete) ───────────────────────────────
	chat.addEventListener("room-action-handler", ({ detail: [{ roomId, action }] }) => {
		if (action.name === "deleteRoom") {
			frappe.confirm(__("Delete this chat session and all messages?"), () => {
				frappe.call({
					method: "ph_agent.api.chat.delete_session",
					args: { session: roomId },
					callback: () => {
						rooms = rooms.filter((r) => r.roomId !== roomId);
						chat.rooms = rooms;
						if (activeRoomId === roomId) {
							messages = [];
							chat.messages = messages;
							activeRoomId = null;
						}
					},
				});
			});
		}
	});

	// ── Real-time: agent reply arrives ────────────────────────────
	frappe.realtime.on("new_message", (data) => {
		if (data.session !== activeRoomId) return;
		const dt = new Date((data.creation || "").replace(" ", "T"));
		messages = [
			...messages,
			{
				_id: data.name,
				content: data.content,
				senderId: agentId,
				username: "AI Agent",
				timestamp: dt.toTimeString().slice(0, 5),
				date: dt.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),
				saved: true,
			},
		];
		chat.messages = messages;
	});
}

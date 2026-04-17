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
	const $container = $('<div style="height: calc(100vh - 120px);"></div>');
	const $status = $('<div id="ph-chat-status" style="height:24px;padding:0 8px;font-size:12px;color:#4f72b8;font-weight:500;line-height:24px;display:flex;align-items:center;gap:6px;"><span class="ph-status-spinner" style="display:none;width:12px;height:12px;border:2px solid #c5d0e8;border-top-color:#4f72b8;border-radius:50%;animation:ph-spin 0.7s linear infinite;flex-shrink:0;"></span><span class="ph-status-text"></span><button class="ph-stop-btn" title="Stop generation" style="display:none;margin-left:4px;padding:2px 8px;font-size:11px;font-weight:600;line-height:16px;border:none;border-radius:3px;background:#e53e3e;color:#fff;cursor:pointer;flex-shrink:0;">&#9632; Stop</button></div><style>@keyframes ph-spin{to{transform:rotate(360deg)}}.ph-stop-btn:hover{background:#c53030!important}</style>');
	$(page.main).append($container);
	$(page.main).append($status);

	// Load vue-advanced-chat from CDN, then initialise
	$.getScript(
		"https://cdn.jsdelivr.net/npm/vue-advanced-chat@2.0.4/dist/vue-advanced-chat.umd.js",
		() => {
			window["vue-advanced-chat"].register();
			initPhChat($container[0], page, $status);
		}
	);
};

function initPhChat(container, page, $status) {
	const currentUserId = frappe.session.user;
	const agentId = "ph_agent";

	// ── Web component ──────────────────────────────────────────────
	const chat = document.createElement("vue-advanced-chat");
	chat.setAttribute("height", "100%");
	chat.setAttribute("current-user-id", currentUserId);
	chat.setAttribute("show-audio", "false");
	chat.setAttribute("rooms-loaded", "false");
	chat.setAttribute("messages-loaded", "false");
	chat.setAttribute("room-actions", JSON.stringify([{ name: "deleteRoom", title: __("Delete") }]));	chat.setAttribute("room-info-enabled", "true");	container.appendChild(chat);

	// Prevent Frappe global keyboard shortcuts (e.g. Shift+/ = "?") from
	// firing while the user is typing inside the chat component.
	container.addEventListener("keydown", (e) => e.stopPropagation());

	let rooms = [];

	// ── Status bar helpers ────────────────────────────────────────
	const $stopBtn = $status.find(".ph-stop-btn");
	let isProcessing = false;

	function setProcessing(active) {
		isProcessing = active;
		$stopBtn.css("display", active ? "inline-block" : "none");
	}

	function setStatus(text) {
		$status.find(".ph-status-text").text(text || "");
		$status.find(".ph-status-spinner").css("display", text ? "inline-block" : "none");
		setProcessing(!!text);
	}
	let messages = [];
	let activeRoomId = null;
	let roomProviders = {}; // roomId -> llm_provider

	// ── Helper: format a Chat Message record ──────────────────────
	function fmtMsg(m) {
		const dt = new Date((m.creation || "").replace(" ", "T"));
		const files = (m.files || []).map((f) => ({
			name: f.file_name,
			size: f.file_size,
			type: (f.file_name || "").split(".").pop().toLowerCase(),
			url: f.file_url,
		}));
		return {
			_id: m.name,
			content: m.content,
			senderId: m.sender_type === "User" ? currentUserId : agentId,
			username: m.sender_type === "User" ? (frappe.boot.user.full_name || currentUserId) : "AI Agent",
			timestamp: dt.toTimeString().slice(0, 5),
			date: dt.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),
			saved: true,
			files: files.length ? files : undefined,
		};
	}

	// ── Helper: upload a single file to Frappe ────────────────────
	function uploadFile(file) {
		return new Promise((resolve, reject) => {
			const formData = new FormData();
			formData.append("file", file.blob, file.name);
			formData.append("is_private", "1");
			$.ajax({
				url: "/api/method/upload_file",
				type: "POST",
				data: formData,
				processData: false,
				contentType: false,
				headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
				success: (r) => resolve(r.message),
				error: reject,
			});
		});
	}

	// ── Load rooms (sessions) ──────────────────────────────────────
	function loadRooms() {
		chat.setAttribute("rooms-loaded", "false");
		frappe.db
			.get_list("Chat Session", {
				filters: { user: currentUserId, status: ["!=", "Archived"] },
				fields: ["name", "title", "modified", "llm_provider"],
				order_by: "modified desc",
				limit: 50,
			})
			.then((sessions) => {
				rooms = sessions.map((s) => {
					roomProviders[s.name] = s.llm_provider;
					return {
						roomId: s.name,
						roomName: s.title + " — " + s.llm_provider,
						users: [
							{ _id: currentUserId, username: frappe.boot.user.full_name || currentUserId },
							{ _id: agentId, username: "AI Agent" },
						],
					};
				});
				chat.rooms = rooms;
				chat.setAttribute("rooms-loaded", "true");
			});
	}

	loadRooms();

	// ── Create new session ─────────────────────────────────────────
	function createNewSession() {
		// Fetch enabled providers, then show a dialog
		frappe.db
			.get_list("LLM Provider", {
				filters: { is_enabled: 1 },
				fields: ["name", "is_default"],
				order_by: "is_default desc, name asc",
			})
			.then((providers) => {
				if (!providers.length) {
					frappe.msgprint({
						title: __("No LLM Provider Configured"),
						message: __(
							"Please go to <b>PH Agent → LLM Provider</b> and create an enabled provider before starting a chat."
						),
						indicator: "red",
					});
					return;
				}

				const defaultProvider = (providers.find((p) => p.is_default) || providers[0]).name;

				const options = providers.map((p) => ({
					label: p.name + (p.is_default ? " (" + __("default") + ")" : ""),
					value: p.name,
				}));

				const d = new frappe.ui.Dialog({
					title: __("New Chat"),
					fields: [
						{
							fieldname: "provider_name",
							fieldtype: "Select",
							label: __("LLM Provider"),
							options: options.map((o) => o.value).join("\n"),
							default: defaultProvider,
							reqd: 1,
						},
					],
					primary_action_label: __("Start Chat"),
					primary_action(values) {
						d.hide();
						frappe.call({
							method: "ph_agent.api.chat.create_session",
							args: { provider_name: values.provider_name },
							callback: (r) => {
								if (!r.message) return;
							roomProviders[r.message.session] = r.message.llm_provider;
							const newRoom = {
								roomId: r.message.session,
								roomName: r.message.title + " — " + r.message.llm_provider,
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
					},
				});
				d.show();
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
	chat.addEventListener("send-message", ({ detail: [{ roomId, content, files }] }) => {
		// Block new messages while one is already being processed
		if (isProcessing) {
			frappe.show_alert({ message: __("Please wait for the current response to finish."), indicator: "orange" });
			return;
		}
		setProcessing(true);

		// Optimistic user bubble with local file previews
		const tempId = "temp_" + Date.now();
		const localFiles = (files || []).map((f) => ({
			name: f.name,
			size: f.size,
			type: (f.name || "").split(".").pop().toLowerCase(),
			url: f.localUrl,
		}));
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
				files: localFiles.length ? localFiles : undefined,
			},
		];
		chat.messages = messages;

		// Show typing indicator
		rooms = rooms.map((r) =>
			r.roomId === roomId ? { ...r, typingUsers: [{ _id: agentId, username: "AI Agent" }] } : r
		);
		chat.rooms = rooms;

		// Upload files first (if any), then send the message
		const uploadPromises = (files || []).map((f) => uploadFile(f));
		Promise.all(uploadPromises)
			.then((uploaded) => {
				const fileNames = uploaded.map((u) => u.name);
				frappe.call({
					method: "ph_agent.api.chat.send_message",
					args: { session: roomId, content, file_names: fileNames },
					callback: (r) => {
						// Job was queued successfully — mark user message as saved
						if (r.message && r.message.status === "queued") {
							messages = messages.map((m) => (m._id === tempId ? { ...m, saved: true } : m));
							chat.messages = messages;
						}
					},
					error: () => {
						messages = messages.map((m) =>
							m._id === tempId ? { ...m, failure: true } : m
						);
						chat.messages = messages;
						setProcessing(false);
						frappe.show_alert({ message: __("Failed to send message. Please try again."), indicator: "red" });
					},
				});
			})
			.catch(() => {
				messages = messages.map((m) =>
					m._id === tempId ? { ...m, failure: true } : m
				);
				chat.messages = messages;
				setProcessing(false);
				frappe.show_alert({ message: __("File upload failed. Please try again."), indicator: "red" });
			});
	});

	// ── Event: room header clicked → change provider ─────────────
	chat.addEventListener("room-info", ({ detail: [room] }) => {
		const roomId = room.roomId;
		frappe.db
			.get_list("LLM Provider", {
				filters: { is_enabled: 1 },
				fields: ["name", "is_default"],
				order_by: "is_default desc, name asc",
			})
			.then((providers) => {
				if (!providers.length) return;
				const currentProvider = roomProviders[roomId] || "";
				const d = new frappe.ui.Dialog({
					title: __("Change LLM Provider"),
					fields: [
						{
							fieldname: "provider_name",
							fieldtype: "Select",
							label: __("LLM Provider"),
							options: providers.map((p) => p.name).join("\n"),
							default: currentProvider,
							reqd: 1,
						},
					],
					primary_action_label: __("Save"),
					primary_action(values) {
						d.hide();
						if (values.provider_name === currentProvider) return;
						frappe.call({
							method: "ph_agent.api.chat.update_session_provider",
							args: { session: roomId, provider_name: values.provider_name },
							callback: () => {
								roomProviders[roomId] = values.provider_name;
								rooms = rooms.map((r) =>
									r.roomId === roomId
										? { ...r, roomName: r.roomName.split(" — ")[0] + " — " + values.provider_name }
										: r
								);
								chat.rooms = rooms;
							},
						});
					},
				});
				d.show();
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

	// ── Real-time: session title auto-generated ───────────────────
	frappe.realtime.on("session_renamed", (data) => {
		rooms = rooms.map((r) => {
			if (r.roomId !== data.session) return r;
			const provider = roomProviders[r.roomId] || "";
			return { ...r, roomName: data.title + (provider ? " — " + provider : "") };
		});
		chat.rooms = rooms;
	});

	// ── Stop button: cancel ongoing generation ───────────────────
	$stopBtn.on("click", () => {
		if (!activeRoomId || !isProcessing) return;
		$stopBtn.prop("disabled", true);
		frappe.call({
			method: "ph_agent.api.chat.cancel_generation",
			args: { session: activeRoomId },
			callback: () => {
				$stopBtn.prop("disabled", false);
			},
			error: () => {
				$stopBtn.prop("disabled", false);
			},
		});
	});

	// ── Real-time: agent status updates ──────────────────────────
	frappe.realtime.on("agent_status", (data) => {
		if (data.session !== activeRoomId) return;
		setStatus(data.status || "");
		if (!data.status) {
			// Clear typing indicator when status is cleared
			rooms = rooms.map((r) =>
				r.roomId === activeRoomId ? { ...r, typingUsers: [] } : r
			);
			chat.rooms = rooms;
		}
	});

	// ── Real-time: generation cancelled ──────────────────────────
	frappe.realtime.on("generation_cancelled", (data) => {
		if (data.session !== activeRoomId) return;
		rooms = rooms.map((r) =>
			r.roomId === activeRoomId ? { ...r, typingUsers: [] } : r
		);
		chat.rooms = rooms;
		setStatus(__("Generation stopped"));
		setProcessing(false);
		setTimeout(() => setStatus(""), 2000);
	});

	// ── Real-time: agent reply arrives ────────────────────────────
	frappe.realtime.on("new_message", (data) => {
		if (data.session !== activeRoomId) return;
		// Clear typing indicator and status
		rooms = rooms.map((r) =>
			r.roomId === activeRoomId ? { ...r, typingUsers: [] } : r
		);
		chat.rooms = rooms;
		setStatus("");
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

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
	chat.setAttribute("room-actions", JSON.stringify([{ name: "deleteRoom", title: __("Delete") }]));	chat.setAttribute("message-actions", JSON.stringify([
		{ name: "editMessage", title: __("Edit"), onlyMe: true },
		{ name: "deleteMessage", title: __("Delete") },
		{ name: "selectMessages", title: __("Select") },
		{ name: "copyMessage", title: __("Copy") },
		{ name: "regenerateMessage", title: __("Regenerate") },
	]));
	chat.setAttribute("message-selection-actions", JSON.stringify([{ name: "deleteMessages", title: __("Delete") }]));	chat.setAttribute("room-info-enabled", "true");	container.appendChild(chat);

	// Prevent Frappe global keyboard shortcuts (e.g. Shift+/ = "?") from
	// firing while the user is typing inside the chat component.
	container.addEventListener("keydown", (e) => e.stopPropagation());

	// Inject suggestion styles directly into the shadow root so they work inside the shadow DOM
	const _shadowRoot = chat.shadowRoot || container;
	const _suggestionStyle = document.createElement("style");
	_suggestionStyle.textContent = `
		.ph-suggestions {
			border-left: 3px solid var(--primary, #4f72b8);
			background: var(--blue-highlight-color, #e8f0fe);
			border-radius: 0 8px 8px 0;
			display: flex;
			flex-direction: column;
			gap: 6px;
			margin: 4px 16px 10px 16px;
			padding: 8px 12px 10px 12px;
		}
		.ph-suggestions-label {
			color: var(--primary, #4f72b8);
			font-size: 11px;
			font-weight: 600;
			letter-spacing: 0.04em;
			text-transform: uppercase;
		}
		.ph-suggestions-btns {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
		}
		.ph-suggestion-btn {
			background: var(--card-bg, #fff);
			border: 1px solid var(--primary, #4f72b8);
			border-radius: 16px;
			color: var(--primary, #4f72b8);
			cursor: pointer;
			font-size: 12px;
			line-height: 1.4;
			padding: 5px 12px;
			text-align: left;
			transition: background 0.15s, border-color 0.15s, color 0.15s;
			white-space: normal;
			word-break: break-word;
		}
		.ph-suggestion-btn:hover {
			background: var(--primary, #4f72b8);
			border-color: var(--primary, #4f72b8);
			color: #fff;
		}
	`;
	_shadowRoot.appendChild(_suggestionStyle);

	// Hide the Regenerate action on the current user's own messages.
	// The library shows ALL actions for own messages with no built-in exclusion flag.
	// We use a MutationObserver so this works in both shadow DOM and light DOM.
	const _regenRoot = _shadowRoot;
	new MutationObserver(() => {
		_regenRoot.querySelectorAll(".vac-menu-options:not(.vac-menu-left) .vac-menu-item").forEach((el) => {
			if (el.textContent.trim() === __("Regenerate")) {
				el.parentElement.style.display = "none";
			}
		});
		// Re-inject any pending suggestions whenever the DOM updates
		renderPendingSuggestions();
	}).observe(_regenRoot, { childList: true, subtree: true });

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
	let messageSuggestions = {}; // messageId -> suggestions[]

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
			edited: !!m.is_edited,
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
		messageSuggestions = {}; // Clear suggestions when switching rooms
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

	// ── Event: user sends a message ─────────────────────────────
	chat.addEventListener("send-message", ({ detail: [{ roomId, content, files, replyMessage }] }) => {
		// ── New message path ───────────────────────────────────────
		if (isProcessing) {
			frappe.show_alert({ message: __("Please wait for the current response to finish."), indicator: "orange" });
			return;
		}
		setProcessing(true);

		// Clear all existing suggestions — they are obsolete once the user sends a new message
		Object.keys(messageSuggestions).forEach((id) => delete messageSuggestions[id]);
		const container = chat.shadowRoot || chat;
		container.querySelectorAll(".ph-suggestions").forEach((el) => el.remove());

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
						// Job was queued successfully — replace temp ID with real persisted ID
						if (r.message && r.message.status === "queued") {
							messages = messages.map((m) =>
								m._id === tempId ? { ...m, _id: r.message.user_message, saved: true } : m
							);
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

	// ── Event: edit a message ─────────────────────────────────────
	chat.addEventListener("edit-message", ({ detail: [{ roomId, messageId, newContent }] }) => {
		if (isProcessing) {
			frappe.show_alert({ message: __("Please wait for the current response to finish."), indicator: "orange" });
			return;
		}
		setProcessing(true);
		frappe.call({
			method: "ph_agent.api.chat.edit_message",
			args: { message_id: messageId, content: newContent },
			callback: (r) => {
				if (!r.message || r.message.status !== "queued") return;
				// Update the edited user message and remove all subsequent messages
				const deletedSet = new Set(r.message.deleted_ids || []);
				messages = messages
					.map((m) => (m._id === messageId ? { ...m, content: newContent, edited: true } : m))
					.filter((m) => !deletedSet.has(m._id));
				chat.messages = messages;
				// Show typing indicator while agent re-runs
				rooms = rooms.map((r) =>
					r.roomId === roomId ? { ...r, typingUsers: [{ _id: agentId, username: "AI Agent" }] } : r
				);
				chat.rooms = rooms;
			},
			error: () => {
				setProcessing(false);
				frappe.show_alert({ message: __("Failed to edit message."), indicator: "red" });
			},
		});
	});

	// ── Event: delete a single message ───────────────────────────
	chat.addEventListener("delete-message", ({ detail: [{ roomId, message }] }) => {
		frappe.confirm(__("Delete this message?"), () => {
			frappe.call({
				method: "ph_agent.api.chat.delete_message",
				args: { message_id: message._id },
				callback: () => {
					messages = messages.filter((m) => m._id !== message._id);
					chat.messages = messages;
				},
				error: () => {
					frappe.show_alert({ message: __("Failed to delete message."), indicator: "red" });
				},
			});
		});
	});

	// ── Event: bulk-delete selected messages ─────────────────────
	chat.addEventListener("message-selection-action-handler", ({ detail: [{ roomId, action, messages: selectedMsgs }] }) => {
		if (action.name === "deleteMessages") {
			frappe.confirm(__("Delete {0} selected message(s)?", [selectedMsgs.length]), () => {
				const ids = selectedMsgs.map((m) => m._id);
				frappe.call({
					method: "ph_agent.api.chat.delete_messages",
					args: { message_ids: ids },
					callback: () => {
						messages = messages.filter((m) => !ids.includes(m._id));
						chat.messages = messages;
					},
					error: () => {
						frappe.show_alert({ message: __("Failed to delete selected messages."), indicator: "red" });
					},
				});
			});
		}
	});

	// ── Event: custom message action (regenerate) ─────────────────
	chat.addEventListener("message-action-handler", ({ detail: [{ roomId, action, message }] }) => {
		if (action.name === "copyMessage") {
			// Copy message content to clipboard
			const textToCopy = message.content || "";
			if (navigator.clipboard && window.isSecureContext) {
				// Modern clipboard API (requires HTTPS or localhost)
				navigator.clipboard.writeText(textToCopy)
					.then(() => {
						frappe.show_alert({ message: __("Copied to clipboard"), indicator: "green" });
					})
					.catch((err) => {
						// Fallback to execCommand for older browsers or permission issues
						fallbackCopyTextToClipboard(textToCopy);
					});
			} else {
				// Fallback for older browsers
				fallbackCopyTextToClipboard(textToCopy);
			}
		} else if (action.name === "regenerateMessage") {
			if (message.senderId !== agentId) return;
			if (isProcessing) {
				frappe.show_alert({ message: __("Please wait for the current response to finish."), indicator: "orange" });
				return;
			}
                         			// Show spinner in place immediately
			const originalContent = message.content;
			messages = messages.map((m) =>
				m._id === message._id ? { ...m, content: "🔄 Regenerating…", regenerating: true } : m
			);
			chat.messages = messages;
			setProcessing(true);
			rooms = rooms.map((r) =>
				r.roomId === roomId ? { ...r, typingUsers: [{ _id: agentId, username: "AI Agent" }] } : r
			);
			chat.rooms = rooms;
			frappe.call({
				method: "ph_agent.api.chat.regenerate_message",
				args: { message_id: message._id },
				error: () => {
					// Revert spinner on error
					messages = messages.map((m) =>
						m._id === message._id ? { ...m, content: originalContent, regenerating: false } : m
					);
					chat.messages = messages;
					setProcessing(false);
					rooms = rooms.map((r) =>
						r.roomId === roomId ? { ...r, typingUsers: [] } : r
					);
					chat.rooms = rooms;
					frappe.show_alert({ message: __("Failed to regenerate message."), indicator: "red" });
				},
			});
		}
	});

	// Fallback copy function using document.execCommand
	function fallbackCopyTextToClipboard(text) {
		const textArea = document.createElement("textarea");
		textArea.value = text;
		// Make the textarea out of viewport
		textArea.style.position = "fixed";
		textArea.style.left = "-999999px";
		textArea.style.top = "-999999px";
		document.body.appendChild(textArea);
		textArea.focus();
		textArea.select();
		try {
			const successful = document.execCommand("copy");
			if (successful) {
				frappe.show_alert({ message: __("Copied to clipboard"), indicator: "green" });
			} else {
				frappe.show_alert({ message: __("Failed to copy to clipboard"), indicator: "red" });
			}
		} catch (err) {
			frappe.show_alert({ message: __("Failed to copy to clipboard"), indicator: "red" });
		}
		document.body.removeChild(textArea);
	}

	// ── Suggestion helpers ────────────────────────────────────────
	function insertSuggestionIntoInput(suggestionText) {
		const root = chat.shadowRoot || container;
		const textarea = root.querySelector("textarea");
		if (!textarea) return;
		// Set the native value and dispatch input event so the Vue component picks it up
		const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
		nativeInputValueSetter.call(textarea, suggestionText);
		textarea.dispatchEvent(new Event("input", { bubbles: true }));
		textarea.focus();
	}

	function removeSuggestionsForMessage(messageId) {
		const root = chat.shadowRoot || container;
		const existing = root.querySelector(`.ph-suggestions[data-msg-id="${messageId}"]`);
		if (existing) existing.remove();
	}

	function injectSuggestions(messageId, suggestions) {
		const root = chat.shadowRoot || container;

		// Idempotent: if already injected, skip to avoid MutationObserver loop
		if (root.querySelector(`.ph-suggestions[data-msg-id="${messageId}"]`)) return true;

		// vue-advanced-chat renders: <div :id="message._id" class="vac-message-wrapper">
		const msgEl = root.querySelector(`#${messageId}`);
		if (!msgEl) {
			return false;
		}

		const wrapper = document.createElement("div");
		wrapper.className = "ph-suggestions";
		wrapper.setAttribute("data-msg-id", messageId);

		const label = document.createElement("span");
		label.className = "ph-suggestions-label";
		label.textContent = __("Suggested follow-ups");
		wrapper.appendChild(label);

		const btnRow = document.createElement("div");
		btnRow.className = "ph-suggestions-btns";
		wrapper.appendChild(btnRow);

		suggestions.forEach((text) => {
			const btn = document.createElement("button");
			btn.className = "ph-suggestion-btn";
			btn.textContent = text;
			btn.addEventListener("click", () => insertSuggestionIntoInput(text));
			btnRow.appendChild(btn);
		});

		// Insert after the message wrapper element
		msgEl.parentNode.insertBefore(wrapper, msgEl.nextSibling);

		// Scroll so the suggestions are visible
		wrapper.scrollIntoView({ behavior: "smooth", block: "nearest" });
		return true;
	}

	function renderPendingSuggestions() {
		const pendingIds = Object.keys(messageSuggestions);
		if (pendingIds.length === 0) return;
		pendingIds.forEach((msgId) => {
			const injected = injectSuggestions(msgId, messageSuggestions[msgId]);
			if (injected) {
				// Remove from map so the observer stops retrying for this message
				delete messageSuggestions[msgId];
			}
		});
	}

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

	// ── Real-time: message edited ─────────────────────────────────
	frappe.realtime.on("message_edited", (data) => {
		if (data.session !== activeRoomId) return;
		const deletedSet = new Set(data.deleted_ids || []);
		messages = messages
			.map((m) => (m._id === data.message_id ? { ...m, content: data.content, edited: true } : m))
			.filter((m) => !deletedSet.has(m._id));
		chat.messages = messages;
	});

	// ── Real-time: single message deleted ─────────────────────────
	frappe.realtime.on("message_deleted", (data) => {
		if (data.session !== activeRoomId) return;
		delete messageSuggestions[data.message_id];
		removeSuggestionsForMessage(data.message_id);
		messages = messages.filter((m) => m._id !== data.message_id);
		chat.messages = messages;
	});

	// ── Real-time: batch messages deleted ─────────────────────────
	frappe.realtime.on("messages_deleted", (data) => {
		if (data.session !== activeRoomId) return;
		messages = messages.filter((m) => !data.message_ids.includes(m._id));
		chat.messages = messages;
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
		const newMsg = {
			_id: data.name,
			content: data.content,
			senderId: agentId,
			username: "AI Agent",
			timestamp: dt.toTimeString().slice(0, 5),
			date: dt.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),
			saved: true,
		};
		if (data.old_message_id) {
			// Remove suggestions for the old (regenerated) message
			delete messageSuggestions[data.old_message_id];
			removeSuggestionsForMessage(data.old_message_id);
			// Replace the regenerating message in place
			messages = messages.map((m) => (m._id === data.old_message_id ? newMsg : m));
		} else {
			messages = [...messages, newMsg];
		}
		chat.messages = messages;
	});

	// ── Real-time: follow-up suggestions ready ────────────────────
	frappe.realtime.on("suggestions_ready", (data) => {
		if (data.session !== activeRoomId) return;
		if (!data.suggestions || !data.suggestions.length) return;
		// Try to inject immediately; if the DOM element isn't ready yet, store for retry via MutationObserver
		const injected = injectSuggestions(data.message_id, data.suggestions);
		if (!injected) {
			messageSuggestions[data.message_id] = data.suggestions;
		}
	});
}

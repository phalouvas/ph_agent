/**
 * PH Agent Chat Event Handlers
 * 
 * Event handlers for the Vue Advanced Chat component events.
 * Each handler delegates to appropriate service functions.
 */

// Initialize eventHandlers object if it doesn't exist
window.phAgent.eventHandlers = window.phAgent.eventHandlers || (function() {
    // Private variables
    let _chat = null;
    let _container = null;
    let _page = null;
    let _$status = null;
    
    // Public API
    return {
        // --- Initialization ---
        
        /**
         * Initialize event handlers with required dependencies
         * @param {HTMLElement} chat - Vue Advanced Chat component
         * @param {HTMLElement} container - Container element
         * @param {Object} page - Frappe page object
         * @param {jQuery} $status - Status bar jQuery element
         */
        init: function(chat, container, page, $status) {
            _chat = chat;
            _container = container;
            _page = page;
            _$status = $status;
        },
        
        // --- Event Binding ---
        
        /**
         * Bind all event handlers to the chat component
         */
        bindAll: function() {
            if (!_chat) {
                return;
            }
            
            // Remove any existing event listeners first
            this.unbindAll();
            
            // Bind all event handlers
            _chat.addEventListener("fetch-messages", this.handleFetchMessages.bind(this));
            _chat.addEventListener("send-message", this.handleSendMessage.bind(this));
            _chat.addEventListener("edit-message", this.handleEditMessage.bind(this));
            _chat.addEventListener("delete-message", this.handleDeleteMessage.bind(this));
            _chat.addEventListener("message-selection-action-handler", this.handleMessageSelectionAction.bind(this));
            _chat.addEventListener("message-action-handler", this.handleMessageAction.bind(this));
            _chat.addEventListener("room-info", this.handleRoomInfo.bind(this));
            _chat.addEventListener("add-room", this.handleAddRoom.bind(this));
            _chat.addEventListener("room-action-handler", this.handleRoomAction.bind(this));
            _chat.addEventListener("open-file", this.handleOpenFile.bind(this));
            _chat.addEventListener("textarea-action-handler", this.handleTextareaAction.bind(this));
        },
        
        /**
         * Remove all event handlers from the chat component
         */
        unbindAll: function() {
            if (!_chat) return;
            
            // Note: We can't actually remove anonymous bound functions easily
            // In a real implementation, we'd need to store references to the bound functions
            // For now, we'll rely on the fact that we're rebinding all events on init
        },
        
        // --- Event Handlers ---
        
        /**
         * Handle fetch-messages event (room selected)
         * @param {Event} event - Event object with room details
         */
        handleFetchMessages: function(event) {
            const detail = event.detail;
            
            // Support two detail formats:
            // 1. Vue Advanced Chat emits: event.detail = [{ room: {...}, options: {...} }]
            //    -> Use detail[0].room
            // 2. Manual dispatch uses:     event.detail = [{ roomId: '...', ... }]
            //    -> Use detail[0]
            const room = detail[0]?.room || detail[0];
            
            if (!room || !room.roomId) {
                return;
            }
            
            const state = window.phAgent.state;
            const roomService = window.phAgent.roomService;
            const utils = window.phAgent.utils;
            
            // Update state
            state.setActiveRoomId(room.roomId);
            // Also update realtime listeners with the new active room
            if (window.phAgent.realtimeListeners) {
                window.phAgent.realtimeListeners.setActiveRoomId(room.roomId);
            }
            state.clearMessageSuggestions(); // Clear suggestions when switching rooms
            
            // When switching away from a room that's mid-generation, the
            // agent_status("") event from the old room will be filtered out
            // (data.session !== _activeRoomId).  Clear the status bar and
            // processing flag here so the "Calling AI…" indicator doesn't
            // persist forever on the new room.
            window.phAgent.uiHelpers.setStatus("");
            state.setIsProcessing(false);
            if (window.phAgent.realtimeListeners && window.phAgent.realtimeListeners.resetResponseState) {
                window.phAgent.realtimeListeners.resetResponseState();
            }
            
            _chat.setAttribute("messages-loaded", "false");
            
            // Load token information for this session
            roomService.getTokenInfo(room.roomId)
                .then((tokenInfo) => {
                    // Update token counter in status bar
                    const $tokenCounter = _$status.find(".ph-token-counter");
                    const $tokenCount = _$status.find(".ph-token-count");
                    const $tokenLimit = _$status.find(".ph-token-limit");
                    const $tokenPercent = _$status.find(".ph-token-percent");
                    
                    // Format numbers with commas
                    const formattedCurrent = tokenInfo.current_tokens.toLocaleString();
                    const formattedLimit = tokenInfo.context_length.toLocaleString();
                    
                    $tokenCount.text(formattedCurrent);
                    $tokenLimit.text(formattedLimit);
                    $tokenPercent.text(tokenInfo.percentage);
                    
                    // Add warning class if over 75%
                    if (tokenInfo.percentage > 75) {
                        $tokenCounter.css("color", "#f59e0b"); // Amber color for warning
                    } else if (tokenInfo.percentage > 90) {
                        $tokenCounter.css("color", "#ef4444"); // Red color for critical
                    } else {
                        $tokenCounter.css("color", "#6b7280"); // Gray color for normal
                    }
                })
                .catch((err) => {
                    // Silently handle token info errors
                });
            
            frappe.call({
                method: "ph_agent.api.chat.get_history",
                args: { session: room.roomId },
                callback: (r) => {
                    // Guard: only apply messages if this room is still the active one
                    const currentActive = window.phAgent.state.getActiveRoomId();
                    if (currentActive !== room.roomId) {
                        return;
                    }
                    
                    const currentUserId = roomService.getCurrentUserId();
                    const agentId = roomService.getAgentId();
                    
                    const messages = (r.message || []).map(msg => 
                        utils.fmtMsg(msg, currentUserId, agentId)
                    );
                    
                    // Update state
                    state.setMessages(messages);
                    
                    // Update chat component
                    _chat.messages = messages;
                    _chat.setAttribute("messages-loaded", "true");

                    const uiHelpers = window.phAgent.uiHelpers;
                    uiHelpers.applySummaryMessageStyles(messages);
                },
                error: (err) => {
                    _chat.setAttribute("messages-loaded", "true"); // Still mark as loaded
                }
            });
        },
        
        /**
         * Handle send-message event
         * @param {Event} event - Event object with message details
         */
        handleSendMessage: function(event) {
            const { roomId, content, files, replyMessage } = event.detail[0];
            
            const state = window.phAgent.state;
            const roomService = window.phAgent.roomService;
            const utils = window.phAgent.utils;
            
            // Check if already processing
            if (state.getIsProcessing()) {
                frappe.show_alert({ 
                    message: __("Please wait for the current response to finish."), 
                    indicator: "orange" 
                });
                return;
            }
            
            // Set processing state
            state.setIsProcessing(true);
            
            // Reset response-completed flag so realtime listeners handle
            // the new generation's placeholder correctly
            const realtimeListeners = window.phAgent.realtimeListeners;
            if (realtimeListeners && realtimeListeners.resetResponseState) {
                realtimeListeners.resetResponseState();
            }
            
            // Clear all existing suggestions
            state.clearMessageSuggestions();
            const root = _chat.shadowRoot || _container;
            root.querySelectorAll(".ph-suggestions").forEach((el) => el.remove());
            
            // Get current user info
            const currentUserId = roomService.getCurrentUserId();
            const agentId = roomService.getAgentId();
            
            // Create optimistic user message
            const tempId = "temp_" + Date.now();
            
            // Common MIME type to extension mapping (shared with handleOpenFile)
            const mimeTypeToExtension = {
                'application/pdf': 'pdf',
                'application/msword': 'doc',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                'application/vnd.ms-excel': 'xls',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                'application/vnd.ms-powerpoint': 'ppt',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
                'text/plain': 'txt',
                'text/csv': 'csv',
                'text/html': 'html',
                'application/json': 'json',
                'application/xml': 'xml',
                'application/epub+zip': 'epub',
                'image/jpeg': 'jpg',
                'image/jpg': 'jpg',
                'image/png': 'png',
                'image/gif': 'gif',
                'image/svg+xml': 'svg'
            };
            
            const localFiles = (files || []).map((f) => {
                // Try to get URL from different possible properties
                // Vue Advanced Chat might provide file objects with different structures
                const fileObj = f.file || f;
                let fileName = f.name || fileObj.name || "file";
                const fileUrl = f.url || f.localUrl || fileObj.url || 
                               (fileObj.blob && URL.createObjectURL(fileObj.blob)) ||
                               (fileObj instanceof Blob && URL.createObjectURL(fileObj));
                
                // Get file type from file object (MIME type like "application/pdf")
                const mimeType = f.type || fileObj.type || "";
                // Extract extension from MIME type or filename
                let extension = "";
                if (mimeType && mimeType.includes('/')) {
                    // Check MIME type mapping first
                    if (mimeTypeToExtension[mimeType]) {
                        extension = mimeTypeToExtension[mimeType];
                    } else {
                        // Extract from MIME type (e.g., "application/pdf" -> "pdf")
                        extension = mimeType.split('/').pop();
                    }
                } else if (fileName.includes('.')) {
                    // Extract from filename
                    extension = fileName.split(".").pop().toLowerCase();
                } else {
                    // Default to empty string
                    extension = "";
                }
                
                // Ensure filename has extension
                if (!fileName.includes('.') && extension) {
                    fileName = fileName + '.' + extension;
                }
                
                return {
                    name: fileName,
                    size: f.size || fileObj.size || 0,
                    type: extension, // Use extension for type
                    extension: extension,
                    url: fileUrl,
                };
            });
            
            const optimisticMessage = {
                _id: tempId,
                content,
                senderId: currentUserId,
                username: frappe.boot.user.full_name || currentUserId,
                timestamp: new Date().toTimeString().slice(0, 5),
                date: new Date().toLocaleDateString("en-GB", { 
                    day: "numeric", 
                    month: "long", 
                    year: "numeric" 
                }),
                saved: false,
                files: localFiles.length ? localFiles : undefined,
            };
            
            // Add optimistic message to state
            state.addMessage(optimisticMessage);
            _chat.messages = state.getMessages();
            
            // Show typing indicator
            const rooms = state.getRooms().map((r) =>
                r.roomId === roomId ? { 
                    ...r, 
                    typingUsers: [{ _id: agentId, username: "AI Agent" }] 
                } : r
            );
            state.setRooms(rooms);
            _chat.rooms = rooms;
            
            // Upload files first (if any), then send the message
            
            const uploadPromises = (files || []).map((f) => {
                // Handle different file object structures
                let fileToUpload = f;
                if (f.file) {
                    // Vue Advanced Chat might use {file: FileObject} structure
                    fileToUpload = { blob: f.file, name: f.name || f.file.name };
                } else if (f instanceof File || f instanceof Blob) {
                    // Direct File or Blob object
                    fileToUpload = { blob: f, name: f.name };
                }
                return utils.uploadFile(fileToUpload);
            });
            
            Promise.all(uploadPromises)
                .then((uploaded) => {
                    // Ensure we get plain string file names (not Proxies)
                    const fileNames = uploaded.map((u) => {
                        const name = u.name;
                        // Extract plain value if it's a Proxy/object
                        if (name && typeof name === 'object') {
                            return String(name);
                        }
                        return name;
                    });
                    
                    // Update optimistic message with Frappe file URLs
                    // This allows immediate download instead of waiting for message reload
                    const updatedMessages = state.getMessages().map((msg) => {
                        if (msg._id === tempId && msg.files) {
                            // Update each file with Frappe URL if available
                            const updatedFiles = msg.files.map((file, index) => {
                                if (index < uploaded.length && uploaded[index]) {
                                    const uploadedFile = uploaded[index];
                                    // Get Frappe file URL from upload response
                                    const frappeUrl = uploadedFile.file_url || uploadedFile.url;
                                    if (frappeUrl) {
                                        
                                        // Extract filename from file_url if available (includes extension)
                                        let fileName = file.name;
                                        if (frappeUrl.includes('/files/') || frappeUrl.includes('/private/files/')) {
                                            // Extract filename from URL (e.g., "/files/ACC-SINV-2026-00225-1.pdf" -> "ACC-SINV-2026-00225-1.pdf")
                                            const urlParts = frappeUrl.split('/');
                                            const extractedName = urlParts[urlParts.length - 1];
                                            if (extractedName && extractedName.includes('.')) {
                                                fileName = extractedName;
                                            }
                                        }
                                        
                                        // Common MIME type to extension mapping (shared)
                                        const mimeTypeToExtension = {
                                            'application/pdf': 'pdf',
                                            'application/msword': 'doc',
                                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                                            'application/vnd.ms-excel': 'xls',
                                            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                                            'application/vnd.ms-powerpoint': 'ppt',
                                            'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
                                            'text/plain': 'txt',
                                            'text/csv': 'csv',
                                            'text/html': 'html',
                                            'application/json': 'json',
                                            'application/xml': 'xml',
                                            'application/epub+zip': 'epub',
                                            'image/jpeg': 'jpg',
                                            'image/jpg': 'jpg',
                                            'image/png': 'png',
                                            'image/gif': 'gif',
                                            'image/svg+xml': 'svg'
                                        };
                                        
                                        // Get extension from MIME type or filename
                                        let extension = "";
                                        if (uploadedFile.file_type) {
                                            // Check MIME type mapping first
                                            if (mimeTypeToExtension[uploadedFile.file_type]) {
                                                extension = mimeTypeToExtension[uploadedFile.file_type];
                                            } else {
                                                extension = uploadedFile.file_type.split('/').pop().toLowerCase();
                                            }
                                        } else if (fileName.includes('.')) {
                                            extension = fileName.split('.').pop().toLowerCase();
                                        }
                                        
                                        // If no filename from URL, use uploadedFile.file_name or file.name
                                        if (!fileName || !fileName.includes('.')) {
                                            fileName = uploadedFile.file_name || file.name;
                                            
                                            // If filename still doesn't have extension but we have extension from MIME type,
                                            // construct filename with extension
                                            if (!fileName.includes('.') && extension) {
                                                fileName = fileName + '.' + extension;
                                            }
                                        }
                                        
                                        const updatedFile = {
                                            ...file,
                                            url: frappeUrl,
                                            name: fileName,
                                            type: extension,
                                            extension: extension
                                        };
                                        return updatedFile;
                                    }
                                }
                                return file;
                            });
                            const updatedMsg = { ...msg, files: updatedFiles };
                            return updatedMsg;
                        }
                        return msg;
                    });
                    state.setMessages(updatedMessages);
                    _chat.messages = updatedMessages;
                    
                    // IMPORTANT: Frappe might not handle arrays properly in frappe.call
                    // Try different approaches:
                    // 1. JSON string
                    const filesJson = JSON.stringify(fileNames);
                    
                    // 2. Comma-separated string (simpler for Frappe)
                    const filesCsv = fileNames.join(',');
                    
                    // Try CSV first (simpler)
                    const args = { 
                        session: roomId, 
                        content, 
                        file_names: filesCsv,  // Comma-separated string
                        reply_to: replyMessage?._id 
                    };
                    
                    frappe.call({
                        method: "ph_agent.api.chat.send_message",
                        args: args,
                        callback: (r) => {
                            if (!r.message) {
                                state.setIsProcessing(false);
                                return;
                            }
                            
                            // Update the temporary message ID with the real database ID
                            if (r.message.user_message) {
                                const messages = state.getMessages().map((msg) =>
                                    msg._id === tempId ? { ...msg, _id: r.message.user_message, saved: true } : msg
                                );
                                state.setMessages(messages);
                                _chat.messages = messages;
                            }
                            
                            // The agent response will come via real-time event (new_message)
                            // Processing state will be cleared in handleNewMessage
                            // DO NOT set setIsProcessing(false) here
                            
                            // Remove typing indicator
                            const updatedRooms = state.getRooms().map((r) =>
                                r.roomId === roomId ? { 
                                    ...r, 
                                    typingUsers: [] 
                                } : r
                            );
                            state.setRooms(updatedRooms);
                            _chat.rooms = updatedRooms;
                        },
                        error: (err) => {
                            state.setIsProcessing(false);
                            
                            // Remove typing indicator on error
                            const updatedRooms = state.getRooms().map((r) =>
                                r.roomId === roomId ? { 
                                    ...r, 
                                    typingUsers: [] 
                                } : r
                            );
                            state.setRooms(updatedRooms);
                            _chat.rooms = updatedRooms;
                        }
                    });
                })
                .catch((error) => {
                    state.setIsProcessing(false);
                });
        },
        
        /**
         * Handle edit-message event
         * @param {Event} event - Event object with edit details
         */
        handleEditMessage: function(event) {
            const { roomId, messageId, newContent } = event.detail[0];
            
            // Check if trying to edit a temporary message (not yet saved to database)
            if (messageId.startsWith("temp_")) {
                frappe.show_alert({ 
                    message: __("Cannot edit message while it's being sent. Please wait a moment and try again."), 
                    indicator: "orange" 
                });
                return;
            }
            
            frappe.call({
                method: "ph_agent.api.chat.edit_message",
                args: { message_id: messageId, content: newContent },
                callback: (r) => {
                    if (r.message && (r.message.status === "ok" || r.message.status === "queued")) {
                        // Update message in state
                        const state = window.phAgent.state;
                        state.updateMessage(messageId, { 
                            content: newContent,
                            edited: true 
                        });
                        
                        // Update chat component
                        _chat.messages = state.getMessages();
                        
                        frappe.show_alert({ 
                            message: __("Message updated"), 
                            indicator: "green" 
                        });
                    }
                },
                error: (err) => {
                    frappe.show_alert({ 
                        message: __("Failed to update message"), 
                        indicator: "red" 
                    });
                }
            });
        },
        
        /**
         * Handle delete-message event
         * @param {Event} event - Event object with delete details
         */
        handleDeleteMessage: function(event) {
            const { roomId, message } = event.detail[0];
            
            frappe.call({
                method: "ph_agent.api.chat.delete_message",
                args: { message_id: message._id },
                callback: (r) => {
                    if (r.message && r.message.status === "ok") {
                        // Remove message from state
                        const state = window.phAgent.state;
                        state.removeMessage(message._id);
                        
                        // Update chat component
                        _chat.messages = state.getMessages();
                        
                        frappe.show_alert({ 
                            message: __("Message deleted"), 
                            indicator: "green" 
                        });
                    }
                },
                error: (err) => {
                    frappe.show_alert({ 
                        message: __("Failed to delete message"), 
                        indicator: "red" 
                    });
                }
            });
        },
        
        /**
         * Handle message-selection-action-handler event
         * @param {Event} event - Event object with selection details
         */
        handleMessageSelectionAction: function(event) {
            const { roomId, action, messages: selectedMsgs } = event.detail[0];
            
            // Extract action name from action object (action is {name: 'deleteMessages', title: 'Delete'})
            const actionName = action.name || action;
            
            if (actionName === "deleteMessages") {
                // Delete all selected messages
                const deletePromises = selectedMsgs.map(msg =>
                    new Promise((resolve, reject) => {
                        frappe.call({
                            method: "ph_agent.api.chat.delete_message",
                            args: { message_id: msg._id },
                            callback: (r) => resolve(r.message && r.message.status === "ok"),
                            error: reject
                        });
                    })
                );
                
                Promise.all(deletePromises)
                    .then(results => {
                        if (results.every(r => r)) {
                            // Remove all selected messages from state
                            const state = window.phAgent.state;
                            selectedMsgs.forEach(msg => state.removeMessage(msg._id));
                            
                            // Update chat component
                            _chat.messages = state.getMessages();
                            
                            frappe.show_alert({ 
                                message: __("Messages deleted"), 
                                indicator: "green" 
                            });
                        }
                    })
                    .catch(err => {
                        frappe.show_alert({ 
                            message: __("Failed to delete messages"), 
                            indicator: "red" 
                        });
                    });
            }
        },
        
        /**
         * Handle message-action-handler event
         * @param {Event} event - Event object with action details
         */
        handleMessageAction: function(event) {
            const { roomId, action, message } = event.detail[0];
            const state = window.phAgent.state;
            const utils = window.phAgent.utils;
            
            // Extract action name from action object (action is {name: 'editMessage', title: 'Edit', ...})
            const actionName = action.name || action;
            
            switch (actionName) {
                case "editMessage":
                    // The chat component handles the edit UI
                    // We just need to update the message when done (handled by edit-message event)
                    break;
                    
                case "deleteMessage":
                    // Already handled by delete-message event
                    break;
                    
                case "selectMessages":
                    // The chat component handles selection UI
                    break;
                    
                case "copyMessage":
                    utils.copyTextToClipboard(message.content);
                    break;
                    
                case "regenerateMessage":
                    // Handle message regeneration
                    this.handleRegenerateMessage(roomId, message);
                    break;
                    
                default:
                    // Unknown message action
            }
        },
        
        /**
         * Handle message regeneration
         * @param {string} roomId - Room ID
         * @param {Object} message - Message to regenerate
         */
        handleRegenerateMessage: function(roomId, message) {
            const state = window.phAgent.state;
            
            if (state.getIsProcessing()) {
                frappe.show_alert({ 
                    message: __("Please wait for the current response to finish."), 
                    indicator: "orange" 
                });
                return;
            }
            
            state.setIsProcessing(true);
            
            // Remove the old message from frontend state immediately
            state.removeMessage(message._id);
            // Update chat component to reflect removal
            _chat.messages = state.getMessages();
            
            frappe.call({
                method: "ph_agent.api.chat.regenerate_message",
                args: { message_id: message._id },
                callback: (r) => {
                    state.setIsProcessing(false);
                    
                    if (r.message && r.message.status === "queued") {
                        frappe.show_alert({ 
                            message: __("Regenerating message..."), 
                            indicator: "green" 
                        });
                    }
                },
                error: (err) => {
                    state.setIsProcessing(false);
                    frappe.show_alert({ 
                        message: __("Failed to regenerate message"), 
                        indicator: "red" 
                    });
                }
            });
        },
        
        /**
         * Handle room-info event
         * @param {Event} event - Event object with room details
         */
        handleRoomInfo: function(event) {
            const room = event.detail[0];
            const roomService = window.phAgent.roomService;
            
            roomService.getRoomInfo(room.roomId)
                .then((roomInfo) => {
                    // Fetch enabled providers and session thinking mode in parallel
                    return Promise.all([
                        frappe.db.get_list("LLM Provider", {
                            filters: { is_enabled: 1 },
                            fields: ["name", "is_default"],
                            order_by: "is_default desc, name asc",
                        }),
                        frappe.db.get_value("Chat Session", room.roomId, "enable_thinking")
                    ]).then(([providers, sessionRes]) => {
                        const providerOptions = providers.map((p) => ({
                            label: p.name + (p.is_default ? " (" + __("default") + ")" : ""),
                            value: p.name,
                        }));
                        const sessionThinking = sessionRes.message?.enable_thinking || false;
                        
                        const dialog = new frappe.ui.Dialog({
                            title: __("Room Information"),
                            fields: [
                                {
                                    fieldname: "title",
                                    fieldtype: "Data",
                                    label: __("Title"),
                                    default: roomInfo.title,
                                    read_only: false,
                                },
                                {
                                    fieldname: "provider",
                                    fieldtype: "Select",
                                    label: __("LLM Provider"),
                                    options: providerOptions.map((o) => o.value).join("\n"),
                                    default: roomInfo.provider,
                                    read_only: false,
                                },
                                {
                                    fieldname: "enable_thinking",
                                    fieldtype: "Check",
                                    label: __("Override Thinking Mode"),
                                    default: sessionThinking,
                                    description: __("When checked, enables thinking/reasoning regardless of provider setting. When unchecked, inherits from LLM Provider."),
                                },
                                {
                                    fieldname: "created",
                                    fieldtype: "Data",
                                    label: __("Created"),
                                    default: new Date(roomInfo.created).toLocaleString(),
                                    read_only: true,
                                },
                                {
                                    fieldname: "modified",
                                    fieldtype: "Data",
                                    label: __("Last Modified"),
                                    default: new Date(roomInfo.modified).toLocaleString(),
                                    read_only: true,
                                },
                            ],
                            primary_action_label: __("Save"),
                            primary_action: (values) => {
                                dialog.hide();
                                
                                // Collect only changed values
                                const args = { session: room.roomId };
                                if (values.title !== roomInfo.title) {
                                    args.title = values.title;
                                }
                                if (values.provider !== roomInfo.provider) {
                                    args.provider_name = values.provider;
                                }
                                if (values.enable_thinking !== sessionThinking) {
                                    args.enable_thinking = values.enable_thinking ? 1 : 0;
                                }
                                
                                if (!args.title && !args.provider_name && args.enable_thinking === undefined) {
                                    return;
                                }
                                
                                frappe.call({
                                    method: "ph_agent.api.chat.update_session_settings",
                                    args: args,
                                    callback: (r) => {
                                        if (r.message && r.message.status === "ok") {
                                            const state = window.phAgent.state;
                                            const roomId = room.roomId;
                                            const finalTitle = args.title || roomInfo.title;
                                            const finalProvider = args.provider_name || roomInfo.provider;
                                            
                                            if (args.provider_name) {
                                                state.setRoomProvider(roomId, finalProvider);
                                            }
                                            
                                            state.updateRoom(roomId, {
                                                roomName: finalTitle + " — " + finalProvider
                                            });
                                            
                                            window.phAgent.roomService.getChat().rooms = state.getRooms();
                                            
                                            frappe.show_alert({ 
                                                message: __("Room settings updated"), 
                                                indicator: "green" 
                                            });
                                        }
                                    },
                                    error: (err) => {
                                        frappe.show_alert({ 
                                            message: __("Failed to update room settings"), 
                                            indicator: "red" 
                                        });
                                    }
                                });
                            }
                        });
                        dialog.show();
                    });
                })
                .catch(err => {
                    frappe.show_alert({ 
                        message: __("Failed to load room information"), 
                        indicator: "red" 
                    });
                });
        },
        
        /**
         * Handle add-room event
         */
        handleAddRoom: function() {
            const roomService = window.phAgent.roomService;
            roomService.createNewSession()
                .catch(err => {
                    if (err.message !== "Dialog cancelled") {
                    }
                });
        },
        
        /**
         * Handle room-action-handler event
         * @param {Event} event - Event object with action details
         */
        handleRoomAction: function(event) {
            const { roomId, action } = event.detail[0];
            const roomService = window.phAgent.roomService;
            
            // Extract action name from action object (action is {name: 'deleteRoom', title: 'Delete'})
            const actionName = action.name || action;
            
            switch (actionName) {
                case "deleteRoom":
                    frappe.confirm(
                        __("Are you sure you want to delete this chat session? This action cannot be undone."),
                        () => {
                            // User confirmed
                            roomService.deleteRoom(roomId)
                                .then(() => {
                                    frappe.show_alert({ 
                                        message: __("Chat session deleted"), 
                                        indicator: "green" 
                                    });
                                })
                                .catch(err => {
                                    frappe.show_alert({ 
                                        message: __("Failed to delete chat session"), 
                                        indicator: "red" 
                                    });
                                });
                        },
                        () => {
                            // User cancelled
                        }
                    );
                    break;
                    
                default:
                    // Unknown room action
            }
        },
        
        /**
         * Handle open-file event (when user clicks on a file to download)
         * @param {Event} event - Event object with file details
         */
        handleOpenFile: function(event) {
            const { message, file } = event.detail[0];
            

            

            
            // Check if this is a download action
            if (file.action === "download") {
                // Try to get file name and URL from different possible property names
                // Check all possible property names that could contain file info
                let fileName = file.name || file.fileName || file.file_name || 
                              (file.file && file.file.name) || "unknown_file";
                let downloadUrl = file.url || file.fileUrl || file.file_url ||
                                 (file.file && file.file.url);
                
                // If fileName doesn't have an extension, try to extract from downloadUrl
                // This handles cases where file_name in database doesn't include extension
                if (fileName && !fileName.includes('.') && downloadUrl) {
                    // Try to extract filename from URL
                    // For Frappe download API: /api/method/...?file_url=/files/filename.pdf
                    // For direct file URL: /files/filename.pdf
                    let extractedName = null;
                    
                    // First, check if it's a Frappe download API URL with file_url parameter
                    const fileUrlMatch = downloadUrl.match(/file_url=([^&]+)/);
                    if (fileUrlMatch) {
                        // Extract the file_url parameter value
                        let fileUrl = fileUrlMatch[1];
                        // Decode URL encoding
                        try {
                            fileUrl = decodeURIComponent(fileUrl);
                        } catch (e) {
                            // Keep as-is if decoding fails
                        }
                        // Extract filename from the file_url
                        const filenameMatch = fileUrl.match(/\/([^\/]+)$/);
                        if (filenameMatch) {
                            extractedName = filenameMatch[1];
                        }
                    }
                    
                    // If not found in file_url parameter, try to extract from the path
                    if (!extractedName) {
                        const urlMatch = downloadUrl.match(/\/([^\/?]+)(?:\?|$)/);
                        if (urlMatch) {
                            extractedName = urlMatch[1];
                            // If it's encoded, decode it
                            try {
                                extractedName = decodeURIComponent(extractedName);
                            } catch (e) {
                                // Keep as-is if decoding fails
                            }
                        }
                    }
                    
                    if (extractedName) {
                        // Only use extracted name if it has an extension
                        if (extractedName.includes('.')) {
                            fileName = extractedName;
                        }
                    }
                }
                
                // Get file extension from various possible sources
                let fileExtension = file.extension || file.type || 
                                   (file.file && file.file.type && file.file.type.split('/').pop());
                

                
                // Common MIME type to extension mapping
                const mimeTypeToExtension = {
                    'application/pdf': 'pdf',
                    'application/msword': 'doc',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                    'application/vnd.ms-excel': 'xls',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                    'application/vnd.ms-powerpoint': 'ppt',
                    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
                    'text/plain': 'txt',
                    'text/csv': 'csv',
                    'text/html': 'html',
                    'application/json': 'json',
                    'application/xml': 'xml',
                    'application/epub+zip': 'epub',
                    'image/jpeg': 'jpg',
                    'image/jpg': 'jpg',
                    'image/png': 'png',
                    'image/gif': 'gif',
                    'image/svg+xml': 'svg'
                };
                
                // If fileName doesn't have extension but we have fileExtension, add it
                if (fileName && fileExtension && !fileName.includes('.')) {
                    // Remove any leading dot from extension and convert to lowercase
                    fileExtension = fileExtension.replace(/^\./, '').toLowerCase();
                    
                    // Check if fileExtension is a MIME type (contains '/')
                    if (fileExtension.includes('/')) {
                        // It's a MIME type, look up extension
                        const mappedExtension = mimeTypeToExtension[fileExtension];
                        if (mappedExtension) {
                            fileExtension = mappedExtension;
                        } else {
                            // Extract from MIME type (e.g., "application/pdf" -> "pdf")
                            fileExtension = fileExtension.split('/').pop();
                        }
                    }
                    
                    // Check if fileExtension looks like a valid extension (not a filename)
                    // Valid extensions are usually short (1-10 chars) and mostly alphabetic
                    // They shouldn't contain numbers, hyphens, or underscores (except for some like "7z")
                    const looksLikeExtension = fileExtension && 
                                              fileExtension.length <= 10 && 
                                              /^[a-z0-9]+$/i.test(fileExtension) &&
                                              !fileExtension.includes('-') &&
                                              !fileExtension.includes('_') &&
                                              /[a-z]/i.test(fileExtension); // Must contain at least one letter
                    
                    // Only add extension if it looks like a valid extension
                    if (fileExtension && looksLikeExtension && fileExtension !== fileName.toLowerCase()) {
                        fileName = fileName + '.' + fileExtension;
                    }
                }
                // If fileName already has extension but it doesn't match fileExtension, fix it
                else if (fileName && fileName.includes('.') && fileExtension) {
                    const currentExt = fileName.split('.').pop().toLowerCase();
                    // Clean up fileExtension
                    let expectedExt = fileExtension.replace(/^\./, '').toLowerCase();
                    if (expectedExt.includes('/')) {
                        expectedExt = expectedExt.split('/').pop();
                    }
                    
                    if (currentExt !== expectedExt) {
                        // Replace the extension
                        const baseName = fileName.substring(0, fileName.lastIndexOf('.'));
                        fileName = baseName + '.' + expectedExt;
                    } else {
                        // Just ensure it's lowercase
                        const parts = fileName.split('.');
                        parts[parts.length - 1] = parts[parts.length - 1].toLowerCase();
                        fileName = parts.join('.');
                    }
                }
                

                
                // For Frappe file attachments, we need to use the download API for private files
                if (downloadUrl) {
                    // Remove any leading/trailing whitespace
                    downloadUrl = downloadUrl.trim();
                    
                    // Check if it's already a full download API URL
                    if (downloadUrl.includes("/api/method/frappe.core.doctype.file.file.download_file")) {
                        // Already a download API URL, use as-is
                    }
                    // Check if this is a Frappe file path (starts with /files/ or files/)
                    else if (downloadUrl.startsWith("/files/") || downloadUrl.startsWith("files/")) {
                        // Ensure it starts with /files/
                        if (downloadUrl.startsWith("files/")) {
                            downloadUrl = "/" + downloadUrl;
                        }
                        
                        // For private files in Frappe, we need to use the download API
                        // The file URL might be something like "/files/filename.pdf"
                        // We need to convert it to "/api/method/frappe.core.doctype.file.file.download_file?file_url=/files/filename.pdf"
                        const encodedFileUrl = encodeURIComponent(downloadUrl);
                        downloadUrl = `/api/method/frappe.core.doctype.file.file.download_file?file_url=${encodedFileUrl}`;
                    }
                    // Check if it's a relative path without /files/
                    else if (!downloadUrl.startsWith("http") && !downloadUrl.startsWith("/") && !downloadUrl.startsWith("blob:")) {
                        // Might be a relative file path, prepend with /
                        downloadUrl = "/" + downloadUrl;
                    }
                }
                
                // If it's a valid URL, download it with proper filename
                if (downloadUrl && (downloadUrl.startsWith("http") || downloadUrl.startsWith("/"))) {
                    // Create a temporary anchor element to trigger download with filename
                    const a = document.createElement('a');
                    a.href = downloadUrl;
                    
                    // Only set download attribute if filename has an extension
                    // Otherwise, let the server's Content-Disposition header determine the filename
                    if (fileName.includes('.')) {
                        a.download = fileName; // This sets the filename for the download
                    }
                    
                    a.target = '_blank'; // Open in new tab for safety
                    a.style.display = 'none';
                    
                    // Add to document, click, and remove
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } else if (downloadUrl && downloadUrl.startsWith("blob:")) {
                    // Blob URLs are temporary and can't be downloaded directly
                    frappe.show_alert({
                        message: __("File is still being processed. Please wait a moment and try again."),
                        indicator: "orange"
                    });
                } else {
                    frappe.show_alert({
                        message: __("Unable to download file. File URL not found or file is still processing."),
                        indicator: "red"
                    });
                }
            } else if (file.action === "preview") {
                // Preview action - let Vue Advanced Chat handle it
                // The library will show media preview for images/videos
            }
        },
        
        // --- Textarea Action Handler ---
        
        /**
         * Handle textarea-action-handler event (custom action button in input footer).
         * Opens the saved prompts library.
         * @param {Event} event - Event object
         */
        handleTextareaAction: function(event) {
            if (window.phAgent && window.phAgent.promptManager) {
                window.phAgent.promptManager.openPromptLibrary();
            } else {
                frappe.show_alert({
                    message: __("Prompt manager not available."),
                    indicator: "orange",
                });
            }
        },
        
        // --- Utility Methods ---
        
        /**
         * Get the chat component
         * @returns {HTMLElement} Chat component
         */
        getChat: function() {
            return _chat;
        },
        
        /**
         * Get the container element
         * @returns {HTMLElement} Container element
         */
        getContainer: function() {
            return _container;
        },
        
        /**
         * Get the page object
         * @returns {Object} Frappe page object
         */
        getPage: function() {
            return _page;
        },
        
        /**
         * Get the status bar element
         * @returns {jQuery} Status bar jQuery element
         */
        getStatusBar: function() {
            return _$status;
        }
    };
})();

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent.eventHandlers;
}
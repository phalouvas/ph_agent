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
                console.error("Event handlers not initialized. Call init() first.");
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
            const room = event.detail[0];
            if (!room || !room.roomId) return;
            
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
                    console.error("Failed to load token info:", err);
                });
            
            frappe.call({
                method: "ph_agent.api.chat.get_history",
                args: { session: room.roomId },
                callback: (r) => {
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
                },
                error: (err) => {
                    console.error("Failed to fetch messages:", err);
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
            
            // Clear all existing suggestions
            state.clearMessageSuggestions();
            const root = _chat.shadowRoot || _container;
            root.querySelectorAll(".ph-suggestions").forEach((el) => el.remove());
            
            // Get current user info
            const currentUserId = roomService.getCurrentUserId();
            const agentId = roomService.getAgentId();
            
            // Create optimistic user message
            const tempId = "temp_" + Date.now();
            const localFiles = (files || []).map((f) => ({
                name: f.name,
                size: f.size,
                type: (f.name || "").split(".").pop().toLowerCase(),
                url: f.localUrl,
            }));
            
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
            const uploadPromises = (files || []).map((f) => utils.uploadFile(f));
            Promise.all(uploadPromises)
                .then((uploaded) => {
                    const fileNames = uploaded.map((u) => u.name);
                    
                    frappe.call({
                        method: "ph_agent.api.chat.send_message",
                        args: { 
                            session: roomId, 
                            content, 
                            files: fileNames,
                            reply_to: replyMessage?._id 
                        },
                        callback: (r) => {
                            if (!r.message) {
                                console.error("Failed to send message");
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
                            console.error("Failed to send message:", err);
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
                    console.error("Failed to upload files:", error);
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
                    console.error("Failed to edit message:", err);
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
                    console.error("Failed to delete message:", err);
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
                        console.error("Failed to delete messages:", err);
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
                    console.warn("Unknown message action:", action);
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
                    console.error("Failed to regenerate message:", err);
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
                                fieldtype: "Data",
                                label: __("LLM Provider"),
                                default: roomInfo.provider,
                                read_only: true,
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
                        primary_action_label: __("Update Title"),
                        primary_action: (values) => {
                            dialog.hide();
                            roomService.updateRoomTitle(room.roomId, values.title)
                                .then(() => {
                                    frappe.show_alert({ 
                                        message: __("Room title updated"), 
                                        indicator: "green" 
                                    });
                                })
                                .catch(err => {
                                    console.error("Failed to update room title:", err);
                                    frappe.show_alert({ 
                                        message: __("Failed to update room title"), 
                                        indicator: "red" 
                                    });
                                });
                        },
                    });
                    dialog.show();
                })
                .catch(err => {
                    console.error("Failed to get room info:", err);
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
                        console.error("Failed to create new session:", err);
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
                                    console.error("Failed to delete room:", err);
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
                    console.warn("Unknown room action:", action);
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
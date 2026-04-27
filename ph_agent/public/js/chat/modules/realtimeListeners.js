/**
 * PH Agent Chat Real-time Listeners
 * 
 * Real-time WebSocket event listeners for the chat interface.
 * Handles 7 different real-time events from the server.
 */

// Initialize realtimeListeners object if it doesn't exist
window.phAgent.realtimeListeners = window.phAgent.realtimeListeners || (function() {
    // Private variables
    let _chat = null;
    let _container = null;
    let _$status = null;
    let _$stopBtn = null;
    let _activeRoomId = null;
    let _agentId = null;
    
    // Public API
    return {
        // --- Initialization ---
        
        /**
         * Initialize real-time listeners with required dependencies
         * @param {HTMLElement} chat - Vue Advanced Chat component
         * @param {HTMLElement} container - Container element
         * @param {jQuery} $status - Status bar jQuery element
         * @param {string} agentId - Agent ID (default: "ph_agent")
         */
        init: function(chat, container, $status, agentId = "ph_agent") {
            _chat = chat;
            _container = container;
            _$status = $status;
            _$stopBtn = $status.find(".ph-stop-btn");
            _agentId = agentId;
            
            // Setup stop button handler
            this.setupStopButtonHandler();
            
            // Register all real-time listeners
            this.registerAllListeners();
        },
        
        /**
         * Set the active room ID for filtering real-time events
         * @param {string} roomId - Active room ID
         */
        setActiveRoomId: function(roomId) {
            _activeRoomId = roomId;
        },
        
        /**
         * Get the active room ID
         * @returns {string} Active room ID
         */
        getActiveRoomId: function() {
            return _activeRoomId;
        },
        
        // --- Real-time Listener Registration ---
        
        /**
         * Register all real-time listeners
         */
        registerAllListeners: function() {
            // Remove any existing listeners first
            this.unregisterAllListeners();
            
            // Register all real-time listeners
            frappe.realtime.on("session_renamed", this.handleSessionRenamed.bind(this));
            frappe.realtime.on("agent_status", this.handleAgentStatus.bind(this));
            frappe.realtime.on("generation_cancelled", this.handleGenerationCancelled.bind(this));
            frappe.realtime.on("message_edited", this.handleMessageEdited.bind(this));
            frappe.realtime.on("message_deleted", this.handleMessageDeleted.bind(this));
            frappe.realtime.on("messages_deleted", this.handleMessagesDeleted.bind(this));
            frappe.realtime.on("new_message", this.handleNewMessage.bind(this));
            frappe.realtime.on("suggestions_ready", this.handleSuggestionsReady.bind(this));
            frappe.realtime.on("message_chunk", this.handleMessageChunk.bind(this));
            frappe.realtime.on("reasoning_chunk", this.handleReasoningChunk.bind(this));
            frappe.realtime.on("token_update", this.handleTokenUpdate.bind(this));
            frappe.realtime.on("token_warning", this.handleTokenWarning.bind(this));
            frappe.realtime.on("approval_needed", this.handleApprovalNeeded.bind(this));
            frappe.realtime.on("approval_resolved", this.handleApprovalResolved.bind(this));
        },
        
        /**
         * Unregister all real-time listeners
         */
        unregisterAllListeners: function() {
            frappe.realtime.off("session_renamed");
            frappe.realtime.off("agent_status");
            frappe.realtime.off("generation_cancelled");
            frappe.realtime.off("message_edited");
            frappe.realtime.off("message_deleted");
            frappe.realtime.off("messages_deleted");
            frappe.realtime.off("new_message");
            frappe.realtime.off("suggestions_ready");
            frappe.realtime.off("message_chunk");
            frappe.realtime.off("reasoning_chunk");
            frappe.realtime.off("approval_needed");
            frappe.realtime.off("approval_resolved");
        },
        
        // --- Stop Button Handler ---
        
        /**
         * Setup stop button click handler
         */
        setupStopButtonHandler: function() {
            // Remove existing handler first
            _$stopBtn.off("click");
            
            // Add new handler
            _$stopBtn.on("click", this.handleStopButtonClick.bind(this));
        },
        
        /**
         * Handle stop button click
         */
        handleStopButtonClick: function() {
            const state = window.phAgent.state;
            const isProcessing = state.getIsProcessing();
            
            if (!_activeRoomId || !isProcessing) {
                return;
            }
            
            _$stopBtn.prop("disabled", true);
            
            frappe.call({
                method: "ph_agent.api.chat.cancel_generation",
                args: { session: _activeRoomId },
                callback: (r) => {
                    _$stopBtn.prop("disabled", false);
                },
                error: (err) => {
                    console.error("cancel_generation API error:", err);
                    _$stopBtn.prop("disabled", false);
                }
            });
        },
        
        // --- Real-time Event Handlers ---
        
        /**
         * Handle session_renamed event
         * @param {Object} data - Event data with session and title
         */
        handleSessionRenamed: function(data) {
            const state = window.phAgent.state;
            
            const rooms = state.getRooms().map((room) => {
                if (room.roomId !== data.session) return room;
                
                const provider = state.getRoomProvider(room.roomId) || "";
                return { 
                    ...room, 
                    roomName: data.title + (provider ? " — " + provider : "") 
                };
            });
            
            state.setRooms(rooms);
            _chat.rooms = rooms;
        },
        
        /**
         * Handle agent_status event
         * @param {Object} data - Event data with session and status
         */
        handleAgentStatus: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const uiHelpers = window.phAgent.uiHelpers;
            const state = window.phAgent.state;
            
            uiHelpers.setStatus(data.status || "");
            
            if (!data.status) {
                // Clear typing indicator when status is cleared
                const rooms = state.getRooms().map((room) =>
                    room.roomId === _activeRoomId ? { ...room, typingUsers: [] } : room
                );
                state.setRooms(rooms);
                _chat.rooms = rooms;
                
                // Clear processing state so the send button re-enables.
                // This is a defensive fallback: the backend always emits
                // agent_status("") before new_message, but if new_message
                // is delayed or buffered, isProcessing would stay true
                // and the user would be stuck unable to send a new message.
                state.setIsProcessing(false);
            }
        },
        
        /**
         * Handle generation_cancelled event
         * @param {Object} data - Event data with session
         */
        handleGenerationCancelled: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const state = window.phAgent.state;
            const uiHelpers = window.phAgent.uiHelpers;
            
            // Clear typing indicator
            const rooms = state.getRooms().map((room) =>
                room.roomId === _activeRoomId ? { ...room, typingUsers: [] } : room
            );
            state.setRooms(rooms);
            _chat.rooms = rooms;
            
            // Update status
            uiHelpers.setStatus(__("Generation stopped"));
            state.setIsProcessing(false);
            
            // Clear status after delay
            setTimeout(() => uiHelpers.setStatus(""), 2000);
        },
        
        /**
         * Handle message_edited event
         * @param {Object} data - Event data with session, message_id, content, and deleted_ids
         */
        handleMessageEdited: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const state = window.phAgent.state;
            const deletedSet = new Set(data.deleted_ids || []);
            
            const messages = state.getMessages()
                .map((message) => 
                    message._id === data.message_id 
                        ? { ...message, content: data.content, edited: true } 
                        : message
                )
                .filter((message) => !deletedSet.has(message._id));
            
            state.setMessages(messages);
            _chat.messages = messages;
        },
        
        /**
         * Handle message_deleted event
         * @param {Object} data - Event data with session and message_id
         */
        handleMessageDeleted: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const state = window.phAgent.state;
            const uiHelpers = window.phAgent.uiHelpers;
            
            // Remove suggestions for the deleted message
            state.removeMessageSuggestions(data.message_id);
            uiHelpers.removeSuggestionsForMessage(data.message_id);
            
            // Remove the message
            const messages = state.getMessages().filter((message) => 
                message._id !== data.message_id
            );
            state.setMessages(messages);
            _chat.messages = messages;
        },
        
        /**
         * Handle messages_deleted event
         * @param {Object} data - Event data with session and message_ids array
         */
        handleMessagesDeleted: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const state = window.phAgent.state;
            const deletedIds = new Set(data.message_ids || []);
            
            const messages = state.getMessages().filter((message) => 
                !deletedIds.has(message._id)
            );
            
            state.setMessages(messages);
            _chat.messages = messages;
        },
        
        /**
         * Handle new_message event (agent reply arrives)
         * @param {Object} data - Event data with session, name, content, creation, old_message_id
         */
        handleNewMessage: function(data) {
            if (data.session !== _activeRoomId) {
                return;
            }
            
            const state = window.phAgent.state;
            const uiHelpers = window.phAgent.uiHelpers;
            const utils = window.phAgent.utils;
            
            // Format the new message
            const dt = new Date((data.creation || "").replace(" ", "T"));
            const newMsg = {
                _id: data.name,
                content: data.content,
                senderId: _agentId,
                username: "AI Agent",
                timestamp: dt.toTimeString().slice(0, 5),
                date: dt.toLocaleDateString("en-GB", { 
                    day: "numeric", 
                    month: "long", 
                    year: "numeric" 
                }),
                saved: true,
            };

            if (data.message_type) {
                newMsg.message_type = data.message_type;
            }
            
            if (data.is_streaming_placeholder || data.content === "⏳ Generating response...") {
                
                if (data.old_message_id) {
                    // Remove suggestions for the old (regenerated) message
                    state.removeMessageSuggestions(data.old_message_id);
                    uiHelpers.removeSuggestionsForMessage(data.old_message_id);
                    
                    // Replace the old message with placeholder
                    const messages = state.getMessages().map((message) =>
                        message._id === data.old_message_id ? newMsg : message
                    );
                    // If old message wasn't found (already removed), add the placeholder
                    const oldMessageExists = state.getMessages().some(m => m._id === data.old_message_id);
                    if (!oldMessageExists) {
                        messages.push(newMsg);
                    }
                    state.setMessages(messages);
                } else {
                    // For new message placeholder, add message
                    state.addMessage(newMsg);
                }
                
                // Show typing indicator for agent
                const rooms = state.getRooms().map((room) => {
                    if (room.roomId !== _activeRoomId) return room;
                    
                    const typingUsers = room.typingUsers || [];
                    if (!typingUsers.includes(_agentId)) {
                        typingUsers.push(_agentId);
                    }
                    
                    return { ...room, typingUsers };
                });
                state.setRooms(rooms);
                _chat.rooms = rooms;
                
                // Keep processing state active (stop button should remain visible)
                state.setIsProcessing(true);
            } else {
                // For final/regular messages (with actual content), clear typing indicator and status
                const rooms = state.getRooms().map((room) =>
                    room.roomId === _activeRoomId ? { ...room, typingUsers: [] } : room
                );
                state.setRooms(rooms);
                _chat.rooms = rooms;
                
                uiHelpers.setStatus("");
                
                // Clear processing state (stop button should now be hidden)
                state.setIsProcessing(false);
                
                // Remove any frontend-created reasoning elements (the HTML content
                // now includes the reasoning block, so the DOM element is a duplicate)
                const root = uiHelpers.getRoot();
                const msgEl = root.querySelector(`[id="${data.name}"]`);
                if (msgEl) {
                    const frontendReasoning = msgEl.querySelector('.ph-reasoning-block');
                    if (frontendReasoning) {
                        frontendReasoning.remove();
                    }
                }
                
                if (data.old_message_id) {
                    // Remove suggestions for the old (regenerated) message
                    state.removeMessageSuggestions(data.old_message_id);
                    uiHelpers.removeSuggestionsForMessage(data.old_message_id);
                    
                    // Replace the regenerating message in place
                    const messages = state.getMessages().map((message) =>
                        message._id === data.old_message_id ? newMsg : message
                    );
                    state.setMessages(messages);
                } else {
                    // Check if message already exists (e.g., placeholder was sent)
                    const existingIndex = state.getMessages().findIndex(m => m._id === data.name);
                    if (existingIndex !== -1) {
                        // Update existing message
                        state.updateMessage(data.name, { content: data.content });
                    } else {
                        // Add new message
                        state.addMessage(newMsg);
                    }
                }
            }
            
            _chat.messages = state.getMessages();
            uiHelpers.applySummaryMessageStyles(state.getMessages());
        },
        
        /**
         * Handle message_chunk event for streaming responses
         * @param {Object} data - Event data with session, message_id, chunk, and is_final
         */
        handleMessageChunk: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const state = window.phAgent.state;
            const uiHelpers = window.phAgent.uiHelpers;
            
            // Find the message by ID
            const message = state.getMessageById(data.message_id);
            if (!message) return;
            
            if (data.is_final) {
                // Final chunk - clear typing indicator and status
                const rooms = state.getRooms().map((room) =>
                    room.roomId === _activeRoomId ? { ...room, typingUsers: [] } : room
                );
                state.setRooms(rooms);
                _chat.rooms = rooms;
                
                uiHelpers.setStatus("");
                
                // Clear processing state (stop button should now be hidden)
                state.setIsProcessing(false);
                
                // Remove frontend-created reasoning element — the final new_message
                // event will contain the HTML with the reasoning block embedded
                const root = uiHelpers.getRoot();
                const msgEl = root.querySelector(`[id="${data.message_id}"]`);
                if (msgEl) {
                    const detailsEl = msgEl.querySelector('.ph-reasoning-block');
                    if (detailsEl) {
                        detailsEl.remove();
                    }
                }
                
                // Update chat component with final message
                const newMessages = state.getMessages();
                _chat.messages = newMessages;
            } else {
                // Content chunk - handle placeholder replacement
                if (!data.chunk) return;
                
                let updatedContent;
                const currentContent = message.content || "";
                if (currentContent === "⏳ Generating response..." || currentContent === "") {
                    // First chunk - replace placeholder with actual content
                    updatedContent = data.chunk;
                } else {
                    // Subsequent chunks - append to existing content
                    updatedContent = currentContent + data.chunk;
                }
                
                state.updateMessage(data.message_id, { 
                    content: updatedContent
                });
                
                // Update chat component - force new array reference for Vue reactivity
                const newMessages = state.getMessages();
                _chat.messages = newMessages;
                
                // Auto-scroll during streaming if user is near bottom
                // Wait for Vue to update DOM before checking scroll position
                setTimeout(() => {
                    const uiHelpers = window.phAgent.uiHelpers;
                    const scrolled = uiHelpers.scrollToBottomIfNear(200);
                    if (!scrolled) {
                        // User is scrolled up - trigger scroll detection to show down-arrow
                        uiHelpers.triggerScrollDetection();
                    }
                }, 50);
                
                // Show typing indicator while streaming
                const rooms = state.getRooms().map((room) => {
                    if (room.roomId !== _activeRoomId) return room;
                    
                    // Add typing indicator for agent
                    const typingUsers = room.typingUsers || [];
                    if (!typingUsers.includes(_agentId)) {
                        typingUsers.push(_agentId);
                    }
                    
                    return { ...room, typingUsers };
                });
                state.setRooms(rooms);
                _chat.rooms = rooms;
            }
        },
        
        /**
         * Handle reasoning_chunk event for streaming thinking/reasoning content
         * @param {Object} data - Event data with session, message_id, and chunk
         */
        handleReasoningChunk: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const state = window.phAgent.state;
            const uiHelpers = window.phAgent.uiHelpers;
            const root = uiHelpers.getRoot();
            
            // Find the message wrapper element
            const msgEl = root.querySelector(`[id="${data.message_id}"]`);
            if (!msgEl) return;
            
            // Find or create the reasoning details element
            let detailsEl = msgEl.querySelector('.ph-reasoning-block');
            if (!detailsEl) {
                detailsEl = document.createElement('details');
                detailsEl.className = 'ph-reasoning-block';
                detailsEl.setAttribute('open', '');
                
                const summary = document.createElement('summary');
                summary.textContent = '\u{1F913} Thinking process';
                detailsEl.appendChild(summary);
                
                const contentDiv = document.createElement('div');
                contentDiv.className = 'ph-reasoning-content';
                detailsEl.appendChild(contentDiv);
                
                // Insert reasoning block before the message text content
                const textContainer = msgEl.querySelector('.vac-format-container');
                if (textContainer && textContainer.parentNode) {
                    textContainer.parentNode.insertBefore(detailsEl, textContainer);
                } else {
                    msgEl.appendChild(detailsEl);
                }
            }
            
            // Append chunk to reasoning content
            const contentDiv = detailsEl.querySelector('.ph-reasoning-content');
            if (contentDiv) {
                contentDiv.textContent += data.chunk;
            }
        },
        
        /**
         * Handle suggestions_ready event
         * @param {Object} data - Event data with session, message_id, and suggestions array
         */
        handleSuggestionsReady: function(data) {
            if (data.session !== _activeRoomId) return;
            if (!data.suggestions || !data.suggestions.length) return;
            
            const uiHelpers = window.phAgent.uiHelpers;
            const state = window.phAgent.state;
            
            // Try to inject immediately; if the DOM element isn't ready yet, store for retry
            const injected = uiHelpers.injectSuggestions(data.message_id, data.suggestions);
            if (!injected) {
                // Store for later retry via MutationObserver
                state.setMessageSuggestions(data.message_id, data.suggestions);
            }
        },
        
        /**
         * Handle token_update event
         * @param {Object} data - Event data with session, current_tokens, context_length, etc.
         */
        handleTokenUpdate: function(data) {
            if (data.session !== _activeRoomId) return;
            
            // Update token counter in status bar
            const $tokenCounter = _$status.find(".ph-token-counter");
            const $tokenCount = _$status.find(".ph-token-count");
            const $tokenLimit = _$status.find(".ph-token-limit");
            const $tokenPercent = _$status.find(".ph-token-percent");
            
            if (data.current_tokens !== undefined && data.context_length !== undefined) {
                const percentage = data.context_length > 0 ? Math.round((data.current_tokens / data.context_length) * 100) : 0;
                
                // Format numbers with commas
                const formattedCurrent = data.current_tokens.toLocaleString();
                const formattedLimit = data.context_length.toLocaleString();
                
                $tokenCount.text(formattedCurrent);
                $tokenLimit.text(formattedLimit);
                $tokenPercent.text(percentage);
                
                // Token counter already visible with display: flex
                
                // Progressive threshold colors
                if (percentage > 95) {
                    $tokenCounter.css("color", "#7f1d1d"); // Dark red for emergency
                    $tokenCounter.css("animation", "ph-pulse 1.5s ease-in-out infinite");
                } else if (percentage > 85) {
                    $tokenCounter.css("color", "#ef4444"); // Red for critical
                    $tokenCounter.css("animation", "none");
                } else if (percentage > 70) {
                    $tokenCounter.css("color", "#f59e0b"); // Amber for warning
                    $tokenCounter.css("animation", "none");
                } else {
                    $tokenCounter.css("color", "#6b7280"); // Gray for normal
                    $tokenCounter.css("animation", "none");
                }
            }
        },
        
        /**
         * Handle token_warning event
         * @param {Object} data - Event data with session, current_tokens, context_length, percentage, message
         */
        handleTokenWarning: function(data) {
            if (data.session !== _activeRoomId) return;
            
            // Show warning toast
            frappe.show_alert({
                message: data.message || `Conversation is using ${data.percentage}% of context window. Consider summarizing.`,
                indicator: "orange"
            }, 10); // Show for 10 seconds
            
            // Also update token counter
            this.handleTokenUpdate(data);
        },
        
        /**
         * Handle approval_needed event
         * Notifies the user that a tool requires approval before execution.
         * @param {Object} data - Event data with session, approval_name, tool_name
         */
        handleApprovalNeeded: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const state = window.phAgent.state;
            const uiHelpers = window.phAgent.uiHelpers;
            
            // Update status to indicate waiting for approval
            uiHelpers.setStatus(__("⏳ Waiting for approval..."));
            
            // Clear processing state (stop button hidden, user can continue other conversations)
            state.setIsProcessing(false);
            
            // Show notification to user
            frappe.show_alert({
                message: __("Tool '{0}' needs approval before execution. Go to Tool Approval Request list to review.", [data.tool_name]),
                indicator: "orange"
            }, 15);
        },
        
        /**
         * Handle approval_resolved event
         * Notifies the user that a tool approval request was resolved.
         * @param {Object} data - Event data with session, approval_name, status, tool_name
         */
        handleApprovalResolved: function(data) {
            if (data.session !== _activeRoomId) return;
            
            const uiHelpers = window.phAgent.uiHelpers;
            
            // Clear the waiting status
            uiHelpers.setStatus("");
            
            if (data.status === "Approved") {
                frappe.show_alert({
                    message: __("Tool '{0}' was approved. Response incoming...", [data.tool_name]),
                    indicator: "green"
                }, 5);
            } else if (data.status === "Rejected") {
                frappe.show_alert({
                    message: __("Tool '{0}' was rejected{1}", [data.tool_name, data.reason ? ": " + data.reason : ""]),
                    indicator: "red"
                }, 8);
            }
        },
        
        // --- Utility Methods ---
        
        /**
         * Clean up all listeners and handlers
         */
        cleanup: function() {
            this.unregisterAllListeners();
            _$stopBtn.off("click");
            
            _chat = null;
            _container = null;
            _$status = null;
            _$stopBtn = null;
            _activeRoomId = null;
            _agentId = null;
        },
        
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
         * Get the status bar element
         * @returns {jQuery} Status bar jQuery element
         */
        getStatusBar: function() {
            return _$status;
        },
        
        /**
         * Get the stop button element
         * @returns {jQuery} Stop button jQuery element
         */
        getStopButton: function() {
            return _$stopBtn;
        },
        
        /**
         * Get the agent ID
         * @returns {string} Agent ID
         */
        getAgentId: function() {
            return _agentId;
        }
    };
})();

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent.realtimeListeners;
}
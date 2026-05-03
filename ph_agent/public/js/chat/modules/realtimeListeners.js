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
    let _responseCompleted = false;  // Tracks whether the current response has finished
    let _chunkBuffer = new Map();    // messageId → accumulated chunk string (setTimeout-batched)
    let _rafScheduled = false;       // Prevents duplicate flush scheduling
    let _finalizedMessages = new Set(); // messageIds that have received final content
    
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
            frappe.realtime.on("messages_pruned", this.handleMessagesPruned.bind(this));
        },
        
        /**
         * Reset response-completed flag when starting a new generation.
         * Called from eventHandlers before sending a new message.
         */
        resetResponseState: function() {
            _responseCompleted = false;
            _chunkBuffer.clear();
            _finalizedMessages.clear();
            _rafScheduled = false;
        },
        
        /**
         * Flush the chunk buffer — applies all accumulated chunks to the message
         * state in a single batch, then schedules a scroll update.
         * Called from setTimeout callback or synchronously on stream completion.
         */
        _flushChunkBuffer: function() {
            _rafScheduled = false;
            if (_chunkBuffer.size === 0) return;
            
            const state = window.phAgent.state;
            
            // Apply all buffered chunks — one state update per message
            for (const [messageId, accumulatedContent] of _chunkBuffer.entries()) {
                // Skip if this message has already been finalized by new_message
                if (_finalizedMessages.has(messageId)) {
                    _chunkBuffer.delete(messageId);
                    continue;
                }

                const message = state.getMessageById(messageId);
                if (!message) continue;
                
                let updatedContent;
                const currentContent = message.content || "";
                if (currentContent === "\u23F3 Generating response..." || currentContent === "") {
                    updatedContent = accumulatedContent;
                } else {
                    updatedContent = currentContent + accumulatedContent;
                }
                
                state.updateMessage(messageId, { content: updatedContent });
            }
            _chunkBuffer.clear();
            
            // Single Vue re-render for all buffered updates
            _chat.messages = state.getMessages();
            
            // Schedule scroll after Vue renders the DOM update.
            // setTimeout(0) works in background tabs where rAF would pause.
            setTimeout(function() {
                const uiHelpers = window.phAgent.uiHelpers;
                const scrolled = uiHelpers.scrollToBottomIfNear(80);
                if (!scrolled) {
                    uiHelpers.triggerScrollDetection();
                }
            }, 0);
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
            frappe.realtime.off("messages_pruned");
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
                // Mark response as completed — prevents late-arriving placeholder
                // new_message events from re-setting isProcessing(true).
                _responseCompleted = true;
                
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
            _responseCompleted = true;
            
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
                
                // Only set processing state if the response hasn't already completed.
                // Due to async Redis pub/sub, the placeholder new_message event can
                // arrive AFTER agent_status("") — without this guard it would
                // re-enable the processing lock and trap the user.
                if (!_responseCompleted) {
                    state.setIsProcessing(true);
                }
            } else {
                // Defensive drain: flush any remaining buffered chunks before
                // replacing streamed content with the saved message. Handles the
                // edge case where Redis pub/sub delivers new_message before the
                // final message_chunk(is_final) event.
                this._flushChunkBuffer();
                
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
                    const frontendReasoning = msgEl.querySelector('.ph-reasoning-block[data-frontend="true"]');
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

                    // Track the new message as finalized, clean up old entry
                    _finalizedMessages.add(data.name);
                    _finalizedMessages.delete(data.old_message_id);
                    _chunkBuffer.delete(data.old_message_id);
                } else {
                    // Check if message already exists (e.g., placeholder was sent)
                    const existingIndex = state.getMessages().findIndex(m => m._id === data.name);
                    if (existingIndex !== -1) {
                        // Update existing message
                        state.updateMessage(data.name, { content: data.content });
                        // Mark as finalized so late-arriving streaming chunks
                        // don't append raw text to the processed HTML content.
                        _finalizedMessages.add(data.name);
                        _chunkBuffer.delete(data.name);
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
                // Synchronously drain any remaining buffered chunks before finalizing
                this._flushChunkBuffer();
                
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
                    const detailsEl = msgEl.querySelector('.ph-reasoning-block[data-frontend="true"]');
                    if (detailsEl) {
                        detailsEl.remove();
                    }
                }

                // Update chat component with final message
                const newMessages = state.getMessages();
                _chat.messages = newMessages;
            } else {
                // Content chunk - accumulate in buffer, flush once per animation frame
                if (!data.chunk) return;

                // If the message has already received its final content from
                // new_message, ignore late-arriving streaming chunks — they
                // would append raw Markdown after the processed HTML.
                if (_finalizedMessages.has(data.message_id)) return;

                // Accumulate chunk in buffer (keyed by messageId)
                const existing = _chunkBuffer.get(data.message_id) || "";
                _chunkBuffer.set(data.message_id, existing + data.chunk);
                
                // Schedule a single flush if not already scheduled.
                // Use setTimeout instead of requestAnimationFrame — rAF pauses
                // when the tab is backgrounded, causing chunks to pile up.
                if (!_rafScheduled) {
                    _rafScheduled = true;
                    setTimeout(() => this._flushChunkBuffer(), 0);
                }
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
                detailsEl.setAttribute('data-frontend', 'true');
                
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
                let percentage = 0;
                if (data.context_length > 0) {
                    const pct = (data.current_tokens / data.context_length) * 100;
                    percentage = pct > 0 && pct < 0.1 ? '<0.1' : Math.round(pct * 10) / 10;
                }
                const numericPercentage = parseFloat(percentage) || 0;

                // Format numbers with commas
                const formattedCurrent = data.current_tokens.toLocaleString();
                const formattedLimit = data.context_length.toLocaleString();

                $tokenCount.text(formattedCurrent);
                $tokenLimit.text(formattedLimit);
                $tokenPercent.text(percentage);
                
                // Token counter already visible with display: flex

                // Progressive threshold colors (use numeric value for comparisons)
                if (numericPercentage > 95) {
                    $tokenCounter.css("color", "#7f1d1d"); // Dark red for emergency
                    $tokenCounter.css("animation", "ph-pulse 1.5s ease-in-out infinite");
                } else if (numericPercentage > 85) {
                    $tokenCounter.css("color", "#ef4444"); // Red for critical
                    $tokenCounter.css("animation", "none");
                } else if (numericPercentage > 70) {
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
         * Handle messages_pruned event
         * @param {Object} data - Event data with session, count, percentage, message
         */
        handleMessagesPruned: function(data) {
            if (data.session !== _activeRoomId) return;

            frappe.show_alert({
                message: data.message || `${data.count} old messages were removed to free context space.`,
                indicator: "orange"
            }, 10);
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
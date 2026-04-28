/**
 * PH Agent Chat Room Service
 * 
 * Service functions for room/session operations: loading rooms,
 * creating new sessions, and provider selection.
 */

// Initialize roomService object if it doesn't exist
window.phAgent.roomService = window.phAgent.roomService || (function() {
    // Private variables
    let _chat = null;
    let _currentUserId = null;
    let _agentId = "ph_agent";
    
    // Public API
    return {
        // --- Initialization ---
        
        /**
         * Initialize the room service with required dependencies
         * @param {HTMLElement} chat - Vue Advanced Chat component
         * @param {string} currentUserId - Current user ID
         * @param {string} agentId - Agent ID (default: "ph_agent")
         */
        init: function(chat, currentUserId, agentId = "ph_agent", defaultPersona = null) {
            _chat = chat;
            _currentUserId = currentUserId;
            _agentId = agentId;
            if (defaultPersona) {
                window.phAgent.state.setActivePersona(defaultPersona);
            }
        },
        
        // --- Room Operations ---
        
        /**
         * Load rooms (chat sessions) from Frappe database, filtered by active persona
         * @returns {Promise} Promise that resolves when rooms are loaded
         */
        loadRooms: function() {
            if (!_chat) {
                console.error("Room service not initialized. Call init() first.");
                return Promise.reject(new Error("Room service not initialized"));
            }
            
            _chat.setAttribute("rooms-loaded", "false");
            
            const filters = { user: _currentUserId, status: ["!=", "Archived"] };
            const activePersona = window.phAgent.state.getActivePersona();
            if (activePersona) {
                filters.persona = activePersona;
            }
            
            return frappe.db
                .get_list("Chat Session", {
                    filters: filters,
                    fields: ["name", "title", "modified", "llm_provider", "is_temporary"],
                    order_by: "modified desc",
                    limit: 50,
                })
                .then((sessions) => {
                    const state = window.phAgent.state;
                    const rooms = sessions.map((s) => {
                        // Update room provider in state
                        state.setRoomProvider(s.name, s.llm_provider);
                        
                        let roomName = s.title + " — " + s.llm_provider;
                        if (s.is_temporary) {
                            roomName = "👻 " + roomName + " (Temporary)";
                        }
                        
                        return {
                            roomId: s.name,
                            roomName: roomName,
                            isTemporary: !!s.is_temporary,
                            users: [
                                { _id: _currentUserId, username: frappe.boot.user.full_name || _currentUserId },
                                { _id: _agentId, username: "AI Agent" },
                            ],
                        };
                    });
                    
                    // Update state with loaded rooms
                    state.setRooms(rooms);
                    
                    // Update chat component
                    _chat.rooms = rooms;
                    _chat.setAttribute("rooms-loaded", "true");
                    
                    return rooms;
                })
                .catch(error => {
                    console.error("Failed to load rooms:", error);
                    _chat.setAttribute("rooms-loaded", "true"); // Still mark as loaded to avoid infinite loading
                    throw error;
                });
        },
        
        /**
         * Create a new chat session with the default LLM provider and active persona
         * @returns {Promise} Promise that resolves with new room data
         */
        createNewSession: function() {
            return new Promise((resolve, reject) => {
                const state = window.phAgent.state;
                const activePersona = state.getActivePersona();
                
                // New sessions are always non-temporary by default.
                // The toggle button only updates the *current* session's is_temporary flag.
                const isTemporary = false;
                
                // Fire-and-forget delete the previous temporary session if any
                const prevRoomId = state.getActiveRoomId();
                if (prevRoomId) {
                    const prevRoom = state.getRoomById(prevRoomId);
                    if (prevRoom && prevRoom.isTemporary) {
                        this.deleteRoom(prevRoomId).catch(() => {});
                        state.removeRoom(prevRoomId);
                    }
                }
                
                const args = {};
                if (activePersona) {
                    args.persona = activePersona;
                }
                if (isTemporary) {
                    args.is_temporary = 1;
                }
                
                frappe.call({
                    method: "ph_agent.api.chat.create_session",
                    args: args,
                    callback: (r) => {
                        if (!r.message) {
                            reject(new Error("Failed to create session"));
                            return;
                        }
                        
                        const session = r.message;
                        
                        // Update state
                        state.setRoomProvider(session.session, session.llm_provider);
                        
                        let roomName = session.title + " — " + session.llm_provider;
                        if (session.is_temporary) {
                            roomName = "👻 " + roomName + " (Temporary)";
                        }
                        
                        const newRoom = {
                            roomId: session.session,
                            roomName: roomName,
                            isTemporary: !!session.is_temporary,
                            users: [
                                { _id: _currentUserId, username: frappe.boot.user.full_name || _currentUserId },
                                { _id: _agentId, username: "AI Agent" },
                            ],
                        };
                        
                        // Add new room to state (at beginning of list)
                        const currentRooms = state.getRooms();
                        state.setRooms([newRoom, ...currentRooms]);
                        
                        // Update chat component
                        _chat.rooms = [newRoom, ...currentRooms];
                        _chat.setAttribute("room-id", session.session);
                        
                        // Set as active room and trigger message loading
                        state.setActiveRoomId(session.session);
                        // Sync the temporary mode button with the new session
                        if (window._phSyncTempModeButton) {
                            window._phSyncTempModeButton(!!session.is_temporary);
                        }
                        // Also update realtime listeners with the new active room
                        if (window.phAgent.realtimeListeners) {
                            window.phAgent.realtimeListeners.setActiveRoomId(session.session);
                        }
                        const fetchMessagesEvent = new CustomEvent("fetch-messages", {
                            detail: [newRoom]
                        });
                        _chat.dispatchEvent(fetchMessagesEvent);
                        
                        resolve(newRoom);
                    },
                    error: (err) => {
                        console.error("Failed to create session:", err);
                        reject(err);
                    }
                });
            });
        },
        
        /**
         * Delete a room (chat session)
         * @param {string} roomId - ID of the room to delete
         * @returns {Promise} Promise that resolves when room is deleted
         */
        deleteRoom: function(roomId) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "ph_agent.api.chat.delete_session",
                    args: { session: roomId },
                    callback: (r) => {
                        if (r.message && r.message.status === "ok") {
                            // Remove room from state
                            const state = window.phAgent.state;
                            state.removeRoom(roomId);
                            state.removeRoomProvider(roomId);
                            
                            // Update chat component
                            _chat.rooms = state.getRooms();
                            
                            // If deleted room was active, clear active room
                            if (state.getActiveRoomId() === roomId) {
                                state.setActiveRoomId(null);
                                _chat.setAttribute("room-id", "");
                            }
                            
                            resolve();
                        } else {
                            reject(new Error("Failed to delete room"));
                        }
                    },
                    error: (err) => {
                        console.error("Failed to delete room:", err);
                        reject(err);
                    }
                });
            });
        },
        
        /**
         * Get room information for display in room info dialog
         * @param {string} roomId - ID of the room
         * @returns {Promise} Promise that resolves with room info
         */
        getRoomInfo: function(roomId) {
            return frappe.db.get_value("Chat Session", roomId, [
                    "title", "llm_provider", "creation", "modified",
                    "temperature", "enable_streaming", "enable_suggestions", "enable_thinking",
                    "system_prompt"
                ])
                .then((r) => {
                    if (!r.message) {
                        throw new Error("Room not found");
                    }
                    
                    const session = r.message;
                    return {
                        title: session.title,
                        provider: session.llm_provider,
                        created: session.creation,
                        modified: session.modified,
                        temperature: session.temperature,
                        enable_streaming: session.enable_streaming,
                        enable_suggestions: session.enable_suggestions,
                        enable_thinking: session.enable_thinking,
                        system_prompt: session.system_prompt || "",
                        roomId: roomId
                    };
                });
        },
        
        /**
         * Get token information for a chat session
         * @param {string} roomId - ID of the room
         * @returns {Promise} Promise that resolves with token info
         */
        getTokenInfo: function(roomId) {
            return frappe.db.get_value("Chat Session", roomId, [
                "estimated_conversation_tokens", 
                "input_tokens", 
                "output_tokens",
                "llm_provider"
            ])
                .then((r) => {
                    if (!r.message) {
                        throw new Error("Room not found");
                    }
                    
                    const session = r.message;
                    
                    // Get provider context length
                    return frappe.db.get_value("LLM Provider", session.llm_provider, ["context_length"])
                        .then((providerRes) => {
                            const context_length = providerRes.message?.context_length || 128000;
                            
                            return {
                                current_tokens: session.estimated_conversation_tokens || 0,
                                input_tokens: session.input_tokens || 0,
                                output_tokens: session.output_tokens || 0,
                                context_length: context_length,
                                percentage: (() => {
                                    if (context_length <= 0) return 0;
                                    const pct = ((session.estimated_conversation_tokens || 0) / context_length) * 100;
                                    if (pct > 0 && pct < 0.1) return '<0.1';
                                    return Math.round(pct * 10) / 10;
                                })()
                            };
                        });
                });
        },
        
        /**
         * Update room title
         * @param {string} roomId - ID of the room
         * @param {string} newTitle - New title for the room
         * @returns {Promise} Promise that resolves when title is updated
         */
        updateRoomTitle: function(roomId, newTitle) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "frappe.client.set_value",
                    args: {
                        doctype: "Chat Session",
                        name: roomId,
                        fieldname: "title",
                        value: newTitle
                    },
                    callback: (r) => {
                        if (r.message) {
                            // Update room in state
                            const state = window.phAgent.state;
                            const room = state.getRoomById(roomId);
                            if (room) {
                                const provider = state.getRoomProvider(roomId) || "";
                                state.updateRoom(roomId, {
                                    roomName: newTitle + " — " + provider
                                });
                                
                                // Update chat component
                                _chat.rooms = state.getRooms();
                            }
                            resolve();
                        } else {
                            reject(new Error("Failed to update room title"));
                        }
                    },
                    error: (err) => {
                        console.error("Failed to update room title:", err);
                        reject(err);
                    }
                });
            });
        },
        
        // --- Utility Methods ---
        
        /**
         * Update room's LLM provider
         * @param {string} roomId - ID of the room
         * @param {string} providerName - New provider name
         * @returns {Promise} Promise that resolves when provider is updated
         */
        updateRoomProvider: function(roomId, providerName) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "ph_agent.api.chat.update_session_provider",
                    args: {
                        session: roomId,
                        provider_name: providerName
                    },
                    callback: (r) => {
                        if (r.message && r.message.status === "ok") {
                            // Update room provider in state
                            const state = window.phAgent.state;
                            state.setRoomProvider(roomId, providerName);
                            
                            // Update room display name
                            const room = state.getRoomById(roomId);
                            if (room) {
                                const title = room.roomName.split(" — ")[0] || room.roomName;
                                state.updateRoom(roomId, {
                                    roomName: title + " — " + providerName
                                });
                                _chat.rooms = state.getRooms();
                            }
                            resolve();
                        } else {
                            reject(new Error("Failed to update provider"));
                        }
                    },
                    error: (err) => {
                        console.error("Failed to update provider:", err);
                        reject(err);
                    }
                });
            });
        },
        
        /**
         * Summarize the current conversation via API.
         * @param {string} roomId - Room/session ID to summarize
         * @returns {Promise} Promise that resolves with summary result
         */
        summarizeSession: function(roomId) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "ph_agent.api.chat.summarize_conversation",
                    args: { session: roomId },
                    callback: (r) => {
                        if (r.message && r.message.status === "success") {
                            resolve(r.message);
                        } else {
                            reject(new Error("Summarization failed"));
                        }
                    },
                    error: (err) => reject(err),
                });
            });
        },
        
        /**
         * Get the current chat component
         * @returns {HTMLElement} Chat component
         */
        getChat: function() {
            return _chat;
        },
        
        /**
         * Get the current user ID
         * @returns {string} Current user ID
         */
        getCurrentUserId: function() {
            return _currentUserId;
        },
        
        /**
         * Get the agent ID
         * @returns {string} Agent ID
         */
        getAgentId: function() {
            return _agentId;
        },
        
        /**
         * Set the global create session function (for New Chat button)
         */
        setGlobalCreateSession: function() {
            window._phChatCreateSession = () => this.createNewSession();
        }
    };
})();

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent.roomService;
}
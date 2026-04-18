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
        init: function(chat, currentUserId, agentId = "ph_agent") {
            _chat = chat;
            _currentUserId = currentUserId;
            _agentId = agentId;
        },
        
        // --- Room Operations ---
        
        /**
         * Load rooms (chat sessions) from Frappe database
         * @returns {Promise} Promise that resolves when rooms are loaded
         */
        loadRooms: function() {
            if (!_chat) {
                console.error("Room service not initialized. Call init() first.");
                return Promise.reject(new Error("Room service not initialized"));
            }
            
            _chat.setAttribute("rooms-loaded", "false");
            
            return frappe.db
                .get_list("Chat Session", {
                    filters: { user: _currentUserId, status: ["!=", "Archived"] },
                    fields: ["name", "title", "modified", "llm_provider"],
                    order_by: "modified desc",
                    limit: 50,
                })
                .then((sessions) => {
                    const state = window.phAgent.state;
                    const rooms = sessions.map((s) => {
                        // Update room provider in state
                        state.setRoomProvider(s.name, s.llm_provider);
                        
                        return {
                            roomId: s.name,
                            roomName: s.title + " — " + s.llm_provider,
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
         * Create a new chat session with provider selection
         * @returns {Promise} Promise that resolves with new room data
         */
        createNewSession: function() {
            return new Promise((resolve, reject) => {
                // Fetch enabled providers
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
                            reject(new Error("No LLM providers configured"));
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
                            primary_action: (values) => {
                                d.hide();
                                frappe.call({
                                    method: "ph_agent.api.chat.create_session",
                                    args: { provider_name: values.provider_name },
                                    callback: (r) => {
                                        if (!r.message) {
                                            reject(new Error("Failed to create session"));
                                            return;
                                        }
                                        
                                        const state = window.phAgent.state;
                                        const session = r.message;
                                        
                                        // Update state
                                        state.setRoomProvider(session.session, session.llm_provider);
                                        
                                        const newRoom = {
                                            roomId: session.session,
                                            roomName: session.title + " — " + session.llm_provider,
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
                            },
                            secondary_action: () => {
                                d.hide();
                                reject(new Error("Dialog cancelled"));
                            }
                        });
                        d.show();
                    })
                    .catch(error => {
                        console.error("Failed to fetch providers:", error);
                        reject(error);
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
                    method: "ph_agent.api.chat.archive_session",
                    args: { session_name: roomId },
                    callback: (r) => {
                        if (r.message && r.message.success) {
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
            return frappe.db.get_value("Chat Session", roomId, ["title", "llm_provider", "creation", "modified"])
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
                        roomId: roomId
                    };
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
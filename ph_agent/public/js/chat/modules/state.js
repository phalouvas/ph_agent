/**
 * PH Agent Chat State Manager
 * 
 * Centralized state management for the chat application.
 * Provides getters, setters, and mutation methods for all shared state.
 */

// Initialize state object if it doesn't exist
window.phAgent.state = window.phAgent.state || (function() {
    // Private state variables
    let rooms = [];
    let messages = [];
    let activeRoomId = null;
    let activePersona = null;
    let roomProviders = {}; // roomId -> llm_provider
    let isProcessing = false;
    let messageSuggestions = {}; // messageId -> suggestions[]
    let isTemporaryMode = localStorage.getItem("ph_agent_temp_mode") === "true";
    
    // Public API
    return {
        // --- Getters ---
        getRooms: function() {
            return [...rooms];
        },
        
        getMessages: function() {
            return [...messages];
        },
        
        getActiveRoomId: function() {
            return activeRoomId;
        },
        
        getActivePersona: function() {
            return activePersona;
        },
        
        getRoomProvider: function(roomId) {
            return roomProviders[roomId];
        },
        
        getAllRoomProviders: function() {
            return {...roomProviders};
        },
        
        getIsProcessing: function() {
            return isProcessing;
        },
        
        getIsTemporaryMode: function() {
            return isTemporaryMode;
        },
        
        getMessageSuggestions: function(messageId) {
            return messageSuggestions[messageId] || [];
        },
        
        getAllMessageSuggestions: function() {
            return {...messageSuggestions};
        },
        
        // --- Setters ---
        setRooms: function(newRooms) {
            rooms = [...newRooms];
        },
        
        setMessages: function(newMessages) {
            messages = [...newMessages];
        },
        
        setActiveRoomId: function(roomId) {
            activeRoomId = roomId;
        },
        
        setActivePersona: function(personaName) {
            activePersona = personaName;
        },
        
        setIsProcessing: function(processing) {
            isProcessing = processing;
        },
        
        setIsTemporaryMode: function(mode) {
            isTemporaryMode = !!mode;
            localStorage.setItem("ph_agent_temp_mode", isTemporaryMode ? "true" : "false");
        },
        
        // --- Mutation methods ---
        addRoom: function(room) {
            rooms = [...rooms, room];
            return rooms.length - 1; // Return index of added room
        },
        
        updateRoom: function(roomId, updates) {
            const index = rooms.findIndex(r => r.roomId === roomId);
            if (index !== -1) {
                rooms = [
                    ...rooms.slice(0, index),
                    {...rooms[index], ...updates},
                    ...rooms.slice(index + 1)
                ];
                return true;
            }
            return false;
        },
        
        removeRoom: function(roomId) {
            const index = rooms.findIndex(r => r.roomId === roomId);
            if (index !== -1) {
                rooms = rooms.filter((_, i) => i !== index);
                delete roomProviders[roomId];
                return true;
            }
            return false;
        },
        
        addMessage: function(message) {
            messages = [...messages, message];
            return messages.length - 1; // Return index of added message
        },
        
        updateMessage: function(messageId, updates) {
            const index = messages.findIndex(m => m._id === messageId);
            if (index !== -1) {
                // Create new array for Vue reactivity
                messages = [
                    ...messages.slice(0, index),
                    {...messages[index], ...updates},
                    ...messages.slice(index + 1)
                ];
                return true;
            }
            return false;
        },
        
        removeMessage: function(messageId) {
            const index = messages.findIndex(m => m._id === messageId);
            if (index !== -1) {
                messages = messages.filter((_, i) => i !== index);
                delete messageSuggestions[messageId];
                return true;
            }
            return false;
        },
        
        setRoomProvider: function(roomId, provider) {
            roomProviders[roomId] = provider;
        },
        
        removeRoomProvider: function(roomId) {
            delete roomProviders[roomId];
        },
        
        setMessageSuggestions: function(messageId, suggestions) {
            messageSuggestions[messageId] = [...suggestions];
        },
        
        removeMessageSuggestions: function(messageId) {
            delete messageSuggestions[messageId];
        },
        
        clearMessageSuggestions: function() {
            messageSuggestions = {};
        },
        
        // --- Bulk operations ---
        clearMessages: function() {
            messages = [];
            messageSuggestions = {};
        },
        
        clearAll: function() {
            rooms = [];
            messages = [];
            activeRoomId = null;
            roomProviders = {};
            isProcessing = false;
            messageSuggestions = {};
        },
        
        // --- Utility methods ---
        getRoomById: function(roomId) {
            return rooms.find(r => r.roomId === roomId);
        },
        
        getMessageById: function(messageId) {
            return messages.find(m => m._id === messageId);
        },
        
        getMessagesByRoomId: function(roomId) {
            return messages.filter(m => {
                // In the original code, messages don't have roomId property directly
                // They're filtered by activeRoomId context
                // This will need to be updated based on actual message structure
                return true; // Placeholder - will need actual implementation
            });
        },
        
        // For debugging
        _getInternalState: function() {
            return {
                rooms: rooms,
                messages: messages,
                activeRoomId: activeRoomId,
                roomProviders: roomProviders,
                isProcessing: isProcessing,
                messageSuggestions: messageSuggestions
            };
        }
    };
})();

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent.state;
}
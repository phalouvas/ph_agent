/**
 * PH Agent Chat Utility Functions
 * 
 * Pure utility functions for formatting, file uploads, clipboard operations,
 * and suggestion handling.
 */

// Initialize utils object if it doesn't exist
window.phAgent.utils = window.phAgent.utils || (function() {
    // Public API
    return {
        // --- Message Formatting ---
        
        /**
         * Format a Chat Message record for display in the chat component
         * @param {Object} m - Message object from Frappe
         * @param {string} currentUserId - Current user ID
         * @param {string} agentId - Agent ID (default: "ph_agent")
         * @returns {Object} Formatted message for vue-advanced-chat
         */
        fmtMsg: function(m, currentUserId, agentId = "ph_agent") {
            const dt = new Date((m.creation || "").replace(" ", "T"));
            const files = (m.files || []).map((f) => {
                // Try to get filename from file_url first (includes extension)
                // file_url format: "/files/filename.pdf"
                let fileName = "";
                let extension = "";
                
                if (f.file_url) {
                    // Extract filename from URL (e.g., "/files/ACC-SINV-2026-00225-1.pdf" -> "ACC-SINV-2026-00225-1.pdf")
                    const urlParts = f.file_url.split('/');
                    fileName = urlParts[urlParts.length - 1];
                    console.log("DEBUG fmtMsg: Extracted filename from file_url:", fileName);
                }
                
                // If no file_url or empty filename, fall back to file_name
                if (!fileName && f.file_name) {
                    fileName = f.file_name;
                    console.log("DEBUG fmtMsg: Using file_name as filename:", fileName);
                }
                
                console.log("DEBUG fmtMsg: File object from database:", {
                    file_name: f.file_name,
                    file_type: f.file_type,
                    file_url: f.file_url,
                    file_size: f.file_size,
                    extracted_filename: fileName,
                    full_object: f
                });
                
                // Get extension from filename if it has one
                if (fileName.includes('.')) {
                    extension = fileName.split(".").pop().toLowerCase();
                }
                // If no extension in filename, try to get from file_type (MIME type)
                if (!extension && f.file_type) {
                    // Extract from MIME type (e.g., "application/pdf" -> "pdf")
                    extension = f.file_type.split('/').pop().toLowerCase();
                    // Also update filename to include extension
                    if (fileName && !fileName.includes('.')) {
                        fileName = fileName + '.' + extension;
                        console.log("DEBUG fmtMsg: Added extension to filename:", fileName);
                    }
                }
                
                const fileObj = {
                    name: fileName,
                    size: f.file_size,
                    extension: extension,
                    type: extension, // Keep type for compatibility
                    url: f.file_url,
                    // Vue Advanced Chat might expect these properties
                    file_name: fileName, // Keep original property name
                    file_url: f.file_url, // Keep original property name
                };
                console.log("DEBUG fmtMsg: Created file object:", fileObj);
                return fileObj;
            });
            const formattedMsg = {
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
            
            // Add message_type for styling (Summary messages get special styling)
            if (m.message_type) {
                formattedMsg.message_type = m.message_type;
            }
            
            return formattedMsg;
        },
        
        // --- File Operations ---
        
        /**
         * Upload a single file to Frappe
         * @param {Object} file - File object with blob and name properties
         * @returns {Promise} Promise that resolves with file upload response
         */
        uploadFile: function(file) {
            return new Promise((resolve, reject) => {
                console.log("DEBUG: uploadFile called with:", file);
                
                // Handle different file object structures
                let fileBlob, fileName;
                
                if (file.blob && file.name) {
                    // Standard structure: {blob: Blob, name: string}
                    fileBlob = file.blob;
                    fileName = file.name;
                } else if (file.file && (file.name || file.file.name)) {
                    // Vue Advanced Chat structure: {file: File, name: string}
                    fileBlob = file.file;
                    fileName = file.name || file.file.name;
                } else if (file instanceof File || file instanceof Blob) {
                    // Direct File/Blob object
                    fileBlob = file;
                    fileName = file.name || "uploaded_file";
                } else {
                    console.error("DEBUG: Unsupported file structure:", file);
                    reject(new Error("Unsupported file structure"));
                    return;
                }
                
                console.log("DEBUG: Uploading file:", fileName, "type:", fileBlob.type, "size:", fileBlob.size);
                
                const formData = new FormData();
                formData.append("file", fileBlob, fileName);
                formData.append("is_private", "1");
                $.ajax({
                    url: "/api/method/upload_file",
                    type: "POST",
                    data: formData,
                    processData: false,
                    contentType: false,
                    headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
                    success: (r) => {
                        console.log("DEBUG: upload_file API response:", r.message);
                        // Extract plain values from any Proxy objects
                        const response = r.message;
                        let plainResponse = response;
                        if (response && typeof response === 'object') {
                            // Create a plain object copy
                            plainResponse = {};
                            for (const key in response) {
                                if (Object.prototype.hasOwnProperty.call(response, key)) {
                                    const value = response[key];
                                    // Extract value from Proxy if needed
                                    plainResponse[key] = value && typeof value === 'object' && value.valueOf ? value.valueOf() : value;
                                }
                            }
                        }
                        console.log("DEBUG: Plain upload response - all fields:", plainResponse);
                        // Log specific fields we care about
                        console.log("DEBUG: Upload response key fields:", {
                            name: plainResponse.name,
                            file_name: plainResponse.file_name,
                            file_url: plainResponse.file_url,
                            file_type: plainResponse.file_type,
                            is_private: plainResponse.is_private,
                            docstatus: plainResponse.docstatus
                        });
                        resolve(plainResponse);
                    },
                    error: (xhr, status, error) => {
                        console.error("DEBUG: File upload failed:", error, "status:", status, "xhr:", xhr);
                        reject(error);
                    },
                });
            });
        },
        
        // --- Clipboard Operations ---
        
        /**
         * Fallback copy function using document.execCommand
         * @param {string} text - Text to copy to clipboard
         */
        fallbackCopyTextToClipboard: function(text) {
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
        },
        
        // --- Suggestion Helpers ---
        
        /**
         * Insert suggestion text into chat input
         * @param {string} suggestionText - Text to insert
         * @param {HTMLElement} chat - Chat component element
         * @param {HTMLElement} container - Container element
         */
        insertSuggestionIntoInput: function(suggestionText, chat, container) {
            const root = chat.shadowRoot || container;
            const textarea = root.querySelector("textarea");
            if (!textarea) return;
            // Set the native value and dispatch input event so the Vue component picks it up
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
            nativeInputValueSetter.call(textarea, suggestionText);
            textarea.dispatchEvent(new Event("input", { bubbles: true }));
            textarea.focus();
        },
        
        /**
         * Remove suggestion UI for a specific message
         * @param {string} messageId - ID of the message
         * @param {HTMLElement} chat - Chat component element
         * @param {HTMLElement} container - Container element
         */
        removeSuggestionsForMessage: function(messageId, chat, container) {
            const root = chat.shadowRoot || container;
            const existing = root.querySelector(`.ph-suggestions[data-msg-id="${messageId}"]`);
            if (existing) existing.remove();
        },
        
        /**
         * Inject suggestion UI for a message
         * @param {string} messageId - ID of the message
         * @param {Array<string>} suggestions - Array of suggestion texts
         * @param {HTMLElement} chat - Chat component element
         * @param {HTMLElement} container - Container element
         * @returns {boolean} True if suggestions were injected, false if message element not found
         */
        injectSuggestions: function(messageId, suggestions, chat, container) {
            const root = chat.shadowRoot || container;
            
            // Idempotent: if already injected, skip to avoid MutationObserver loop
            if (root.querySelector(`.ph-suggestions[data-msg-id="${messageId}"]`)) return true;

            // vue-advanced-chat renders: <div :id="message._id" class="vac-message-wrapper">
            // Use attribute selector to avoid CSS ID validation issues (IDs starting with digits are invalid)
            const msgEl = root.querySelector(`[id="${messageId}"]`);
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
                btn.addEventListener("click", () => this.insertSuggestionIntoInput(text, chat, container));
                btnRow.appendChild(btn);
            });

            // Insert after the message wrapper element
            msgEl.parentNode.insertBefore(wrapper, msgEl.nextSibling);

            // Scroll so the suggestions are visible
            wrapper.scrollIntoView({ behavior: "smooth", block: "nearest" });
            return true;
        },
        
        /**
         * Render all pending suggestions from state
         * @param {Object} state - State manager instance
         * @param {HTMLElement} chat - Chat component element
         * @param {HTMLElement} container - Container element
         */
        renderPendingSuggestions: function(state, chat, container) {
            const messageSuggestions = state.getAllMessageSuggestions();
            const pendingIds = Object.keys(messageSuggestions);
            if (pendingIds.length === 0) return;
            
            pendingIds.forEach((msgId) => {
                const injected = this.injectSuggestions(msgId, messageSuggestions[msgId], chat, container);
                if (injected) {
                    // Remove from state so the observer stops retrying for this message
                    state.removeMessageSuggestions(msgId);
                }
            });
        },
        
        // --- General Utilities ---
        
        /**
         * Copy text to clipboard using modern API with fallback
         * @param {string} text - Text to copy
         */
        copyTextToClipboard: function(text) {
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(
                    () => frappe.show_alert({ message: __("Copied to clipboard"), indicator: "green" }),
                    () => this.fallbackCopyTextToClipboard(text)
                );
            } else {
                this.fallbackCopyTextToClipboard(text);
            }
        },
        
        /**
         * Debounce function to limit how often a function can be called
         * @param {Function} func - Function to debounce
         * @param {number} wait - Wait time in milliseconds
         * @returns {Function} Debounced function
         */
        debounce: function(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        },
        
        /**
         * Throttle function to limit function execution rate
         * @param {Function} func - Function to throttle
         * @param {number} limit - Time limit in milliseconds
         * @returns {Function} Throttled function
         */
        throttle: function(func, limit) {
            let inThrottle;
            return function() {
                const args = arguments;
                const context = this;
                if (!inThrottle) {
                    func.apply(context, args);
                    inThrottle = true;
                    setTimeout(() => inThrottle = false, limit);
                }
            };
        }
    };
})();

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent.utils;
}
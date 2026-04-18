/**
 * PH Agent Chat UI Helpers
 * 
 * UI helper functions for the chat interface including:
 * - Suggestion rendering and management
 * - Status bar updates
 * - Clipboard operations
 * - DOM manipulation utilities
 */

// Initialize uiHelpers object if it doesn't exist
window.phAgent.uiHelpers = window.phAgent.uiHelpers || (function() {
    // Private variables
    let _chat = null;
    let _container = null;
    let _$status = null;
    let _suggestionStyle = null;
    let _regenObserver = null;
    
    // Public API
    return {
        // --- Initialization ---
        
        /**
         * Initialize UI helpers with required dependencies
         * @param {HTMLElement} chat - Vue Advanced Chat component
         * @param {HTMLElement} container - Container element
         * @param {jQuery} $status - Status bar jQuery element
         */
        init: function(chat, container, $status) {
            _chat = chat;
            _container = container;
            _$status = $status;
            
            // Inject suggestion styles
            this.injectSuggestionStyles();
            
            // Setup mutation observer for hiding regenerate action on user messages
            this.setupRegenerateObserver();
        },
        
        // --- Suggestion Management ---
        
        /**
         * Inject CSS styles for suggestions into the shadow DOM
         */
        injectSuggestionStyles: function() {
            const root = _chat.shadowRoot || _container;
            
            // Remove existing style if present
            if (_suggestionStyle) {
                _suggestionStyle.remove();
            }
            
            // Create and inject new style
            _suggestionStyle = document.createElement("style");
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
            root.appendChild(_suggestionStyle);
        },
        
        /**
         * Insert suggestion text into the chat input
         * @param {string} suggestionText - Text to insert into input
         */
        insertSuggestionIntoInput: function(suggestionText) {
            const root = _chat.shadowRoot || _container;
            const textarea = root.querySelector("textarea");
            if (!textarea) return;
            
            // Set the native value and dispatch input event so the Vue component picks it up
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 
                "value"
            ).set;
            nativeInputValueSetter.call(textarea, suggestionText);
            textarea.dispatchEvent(new Event("input", { bubbles: true }));
            textarea.focus();
        },
        
        /**
         * Remove suggestions for a specific message
         * @param {string} messageId - ID of the message to remove suggestions for
         */
        removeSuggestionsForMessage: function(messageId) {
            const root = _chat.shadowRoot || _container;
            const existing = root.querySelector(`.ph-suggestions[data-msg-id="${messageId}"]`);
            if (existing) existing.remove();
        },
        
        /**
         * Inject suggestion UI after a message
         * @param {string} messageId - ID of the message to inject suggestions after
         * @param {string[]} suggestions - Array of suggestion texts
         * @returns {boolean} True if injected successfully, false if message element not found
         */
        injectSuggestions: function(messageId, suggestions) {
            const root = _chat.shadowRoot || _container;
            
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
                btn.addEventListener("click", () => this.insertSuggestionIntoInput(text));
                btnRow.appendChild(btn);
            });
            
            // Insert after the message wrapper element
            msgEl.parentNode.insertBefore(wrapper, msgEl.nextSibling);
            
            // Scroll so the suggestions are visible
            wrapper.scrollIntoView({ behavior: "smooth", block: "nearest" });
            return true;
        },
        
        /**
         * Render any pending suggestions that were stored while waiting for DOM
         * @param {Object} messageSuggestions - Map of messageId -> suggestions array
         * @returns {Object} Updated messageSuggestions map with successfully injected items removed
         */
        renderPendingSuggestions: function(messageSuggestions) {
            const pendingIds = Object.keys(messageSuggestions);
            if (pendingIds.length === 0) return messageSuggestions;
            
            const updatedSuggestions = { ...messageSuggestions };
            
            pendingIds.forEach((msgId) => {
                const injected = this.injectSuggestions(msgId, updatedSuggestions[msgId]);
                if (injected) {
                    // Remove from map so the observer stops retrying for this message
                    delete updatedSuggestions[msgId];
                }
            });
            
            return updatedSuggestions;
        },
        
        // --- Status Bar Management ---
        
        /**
         * Set processing state (shows/hides stop button)
         * @param {boolean} active - Whether processing is active
         */
        setProcessing: function(active) {
            const $stopBtn = _$status.find(".ph-stop-btn");
            $stopBtn.css("display", active ? "inline-block" : "none");
        },
        
        /**
         * Set status text and show/hide spinner
         * @param {string} text - Status text to display (empty string hides status)
         */
        setStatus: function(text) {
            _$status.find(".ph-status-text").text(text || "");
            _$status.find(".ph-status-spinner").css("display", text ? "inline-block" : "none");
            this.setProcessing(!!text);
        },
        
        // --- Clipboard Operations ---
        
        /**
         * Fallback clipboard copy function using document.execCommand
         * Used when modern clipboard API is not available
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
                    frappe.show_alert({ 
                        message: __("Copied to clipboard"), 
                        indicator: "green" 
                    });
                } else {
                    frappe.show_alert({ 
                        message: __("Failed to copy to clipboard"), 
                        indicator: "red" 
                    });
                }
            } catch (err) {
                frappe.show_alert({ 
                    message: __("Failed to copy to clipboard"), 
                    indicator: "red" 
                });
            }
            
            document.body.removeChild(textArea);
        },
        
        /**
         * Copy text to clipboard using modern API with fallback
         * @param {string} text - Text to copy to clipboard
         */
        copyTextToClipboard: function(text) {
            if (navigator.clipboard && window.isSecureContext) {
                // Modern clipboard API (requires HTTPS or localhost)
                navigator.clipboard.writeText(text)
                    .then(() => {
                        frappe.show_alert({ 
                            message: __("Copied to clipboard"), 
                            indicator: "green" 
                        });
                    })
                    .catch((err) => {
                        // Fallback to execCommand for permission issues
                        this.fallbackCopyTextToClipboard(text);
                    });
            } else {
                // Fallback for older browsers or non-secure contexts
                this.fallbackCopyTextToClipboard(text);
            }
        },
        
        // --- DOM Manipulation ---
        
        /**
         * Setup mutation observer to hide regenerate action on user messages
         * The library shows ALL actions for own messages with no built-in exclusion flag
         */
        setupRegenerateObserver: function() {
            const root = _chat.shadowRoot || _container;
            
            if (_regenObserver) {
                _regenObserver.disconnect();
            }
            
            _regenObserver = new MutationObserver(() => {
                root.querySelectorAll(".vac-menu-options:not(.vac-menu-left) .vac-menu-item").forEach((el) => {
                    if (el.textContent.trim() === __("Regenerate")) {
                        el.parentElement.style.display = "none";
                    }
                });
            });
            
            _regenObserver.observe(root, { childList: true, subtree: true });
        },
        
        /**
         * Clean up observers and event listeners
         */
        cleanup: function() {
            if (_regenObserver) {
                _regenObserver.disconnect();
                _regenObserver = null;
            }
            
            if (_suggestionStyle) {
                _suggestionStyle.remove();
                _suggestionStyle = null;
            }
            
            _chat = null;
            _container = null;
            _$status = null;
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
         * Get the status bar element
         * @returns {jQuery} Status bar jQuery element
         */
        getStatusBar: function() {
            return _$status;
        },
        
        /**
         * Get the root element (shadow root or container)
         * @returns {HTMLElement} Root element
         */
        getRoot: function() {
            return _chat.shadowRoot || _container;
        }
    };
})();

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent.uiHelpers;
}
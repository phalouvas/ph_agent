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

                /* Summary message styling (shadow DOM) */
                .ph-summary-message .vac-message-card {
                    background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
                    border: 1px solid #7dd3fc;
                    border-left: 4px solid #0ea5e9;
                    border-radius: 8px;
                }
                .ph-summary-message .vac-message-card:hover {
                    background: linear-gradient(135deg, #e0f2fe 0%, #bae6fd 100%);
                    border-color: #38bdf8;
                }
                .ph-summary-message .vac-text-timestamp {
                    color: #0c4a6e;
                }
                .ph-summary-message .vac-format-container:first-child {
                    font-weight: 600;
                }
                .ph-summary-message .vac-message-card {
                    cursor: pointer;
                }
                .ph-summary-message .vac-format-container:first-child::after {
                    content: "▾";
                    display: inline-block;
                    margin-left: 8px;
                    font-size: 11px;
                    color: #0369a1;
                    transition: transform 0.2s ease;
                }
                .ph-summary-message.ph-summary-collapsed .vac-format-container:first-child::after {
                    transform: rotate(-90deg);
                }
                .ph-summary-message.ph-summary-collapsed .vac-format-container:nth-child(2) {
                    display: none;
                }

                /* Reasoning block styling */
                .ph-reasoning-block {
                    margin-bottom: 12px;
                    padding: 8px 12px;
                    background: #f8fafc;
                    border: 1px solid #e2e8f0;
                    border-radius: 8px;
                    border-left: 3px solid #94a3b8;
                    font-size: 0.9em;
                    color: #64748b;
                }
                .ph-reasoning-block summary {
                    cursor: pointer;
                    font-weight: 500;
                    color: #475569;
                    user-select: none;
                }
                .ph-reasoning-block[open] summary {
                    margin-bottom: 8px;
                }
                .ph-reasoning-content {
                    white-space: pre-wrap;
                    word-break: break-word;
                    line-height: 1.5;
                }

                /* Custom action button (saved prompts) - replace default trash icon with bookmark */
                .vac-svg-button.ph-saved-prompts-btn svg,
                .vac-svg-button:has(#vac-icon-deleted) svg {
                    display: none !important;
                }
                .vac-svg-button.ph-saved-prompts-btn::before,
                .vac-svg-button:has(#vac-icon-deleted)::before {
                    content: "🔖" !important;
                    font-size: 18px !important;
                    line-height: 1 !important;
                    display: inline-block !important;
                }
                .vac-svg-button.ph-saved-prompts-btn,
                .vac-svg-button:has(#vac-icon-deleted) {
                    cursor: pointer !important;
                }

                /* Prevent textarea from pushing send button out of view on long input */
                .vac-box-footer {
                    max-height: 200px;
                }
                .vac-textarea {
                    max-height: 150px !important;
                    overflow-y: auto !important;
                }
            `;
            root.appendChild(_suggestionStyle);
        },

        /**
         * Apply summary message class to message wrapper elements.
         * Messages are rendered inside shadow DOM, so we tag wrappers directly.
         * @param {Object[]} messages - Chat messages array
         */
        applySummaryMessageStyles: function(messages) {
            const root = _chat.shadowRoot || _container;
            if (!root) return;

            // If the component created/changed its shadow root after init,
            // make sure our style tag is injected into the current root.
            if (!_suggestionStyle || _suggestionStyle.parentNode !== root) {
                this.injectSuggestionStyles();
            }

            const summaryIds = new Set(
                (messages || [])
                    .filter((msg) => msg && msg.message_type === "Summary")
                    .map((msg) => String(msg._id))
            );

            // Remove stale summary classes first.
            root.querySelectorAll(".ph-summary-message").forEach((el) => {
                if (!summaryIds.has(el.id)) {
                    el.classList.remove("ph-summary-message");
                }
            });

            // Apply class to currently visible summary message wrappers.
            summaryIds.forEach((messageId) => {
                const msgEl = root.querySelector(`[id="${messageId}"]`);
                if (msgEl) {
                    msgEl.classList.add("ph-summary-message");
                }
            });

            // Fallback: mark rendered summary cards by visible title text
            // (handles cases where message_type is missing in frontend payload).
            root.querySelectorAll(".vac-message-wrapper").forEach((wrapper) => {
                const titleEl = wrapper.querySelector(".vac-format-container:first-child");
                const titleText = (titleEl?.textContent || "").trim().toLowerCase();
                if (titleText.includes("summary")) {
                    wrapper.classList.add("ph-summary-message");
                }
            });

            // Add collapsible behavior (default: collapsed) for summary cards.
            root.querySelectorAll(".ph-summary-message").forEach((wrapper) => {
                const card = wrapper.querySelector(".vac-message-card");
                const body = wrapper.querySelector(".vac-format-container:nth-child(2)");
                if (!card || !body) return;

                if (!wrapper.dataset.summaryCollapseInit) {
                    wrapper.classList.add("ph-summary-collapsed");
                    wrapper.dataset.summaryCollapseInit = "1";

                    card.addEventListener("click", () => {
                        wrapper.classList.toggle("ph-summary-collapsed");
                    });
                }
            });
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
        },
        
        // --- Scroll Management ---
        
        /**
         * Get the scrollable chat container element
         * @returns {HTMLElement|null} Scroll container element or null if not found
         */
        getScrollContainer: function() {
            const root = this.getRoot();
            // Try to find the Vue Advanced Chat scroll container
            const scrollContainer = root.querySelector('.vac-container-scroll');
            if (scrollContainer) return scrollContainer;
            
            // Fallback to the container element
            return _container;
        },
        
        /**
         * Check if the user is near the bottom of the chat
         * @param {number} threshold - Distance from bottom in pixels (default: 200)
         * @returns {boolean} True if near bottom, false otherwise
         */
        isNearBottom: function(threshold = 200) {
            const scrollContainer = this.getScrollContainer();
            if (!scrollContainer) return false;
            
            const scrollTop = scrollContainer.scrollTop;
            const scrollHeight = scrollContainer.scrollHeight;
            const clientHeight = scrollContainer.clientHeight;
            
            // Calculate distance from bottom
            const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
            return distanceFromBottom <= threshold;
        },
        
        /**
         * Scroll to bottom if user is near the bottom
         * @param {number} threshold - Distance from bottom in pixels (default: 200)
         * @returns {boolean} True if scrolled, false otherwise
         */
        scrollToBottomIfNear: function(threshold = 200) {
            const scrollContainer = this.getScrollContainer();
            if (!scrollContainer) return false;
            
            if (this.isNearBottom(threshold)) {
                scrollContainer.scrollTo({
                    top: scrollContainer.scrollHeight,
                    behavior: 'smooth'
                });
                return true;
            }
            return false;
        },
        
        /**
         * Trigger scroll detection to update down-arrow button visibility
         * This dispatches a synthetic scroll event to make Vue Advanced Chat
         * update its scrollIcon state
         */
        triggerScrollDetection: function() {
            const scrollContainer = this.getScrollContainer();
            if (!scrollContainer) return;
            
            // Dispatch a synthetic scroll event
            scrollContainer.dispatchEvent(new Event('scroll', { bubbles: true }));
        },
        

    };
})();

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent.uiHelpers;
}
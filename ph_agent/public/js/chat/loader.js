/**
 * PH Agent Chat Module Loader
 * 
 * This file defines the global namespace and provides a utility to load
 * modular JavaScript files for the chat interface.
 */

// Define global namespace for PH Agent chat modules
window.phAgent = window.phAgent || {};

/**
 * Load chat modules in dependency order
 * @param {Array<string>} modulePaths - Array of module paths to load
 * @returns {Promise} Promise that resolves when all modules are loaded
 */
window.phAgent.loadModules = function(modulePaths) {
    return new Promise((resolve, reject) => {
        let loadedCount = 0;
        const totalModules = modulePaths.length;
        
        if (totalModules === 0) {
            resolve();
            return;
        }
        
        function onModuleLoaded() {
            loadedCount++;
            if (loadedCount === totalModules) {
                resolve();
            }
        }
        
        function onModuleError(error) {
            console.error(`Failed to load module: ${error}`);
            reject(error);
        }
        
        // Load each module using frappe.require
        modulePaths.forEach(modulePath => {
            try {
                frappe.require(modulePath, onModuleLoaded, onModuleError);
            } catch (error) {
                onModuleError(error);
            }
        });
    });
};

/**
 * Get the base path for chat modules
 * @returns {string} Base path for chat modules
 */
window.phAgent.getModuleBasePath = function() {
    return '/assets/ph_agent/js/chat/modules/';
};

/**
 * Predefined module loading order for the chat application
 */
window.phAgent.moduleLoadOrder = [
    'state.js',
    'utils.js',
    'roomService.js',
    'eventHandlers.js'
    // 'uiHelpers.js',        // Will be added in Step 3.2
    // 'realtimeListeners.js' // Will be added in Step 3.3
];

/**
 * Load all chat modules in the correct order
 * @returns {Promise} Promise that resolves when all modules are loaded
 */
window.phAgent.loadAllModules = function() {
    const basePath = window.phAgent.getModuleBasePath();
    const modulePaths = window.phAgent.moduleLoadOrder.map(module => basePath + module);
    return window.phAgent.loadModules(modulePaths);
};

// Export for testing/debugging
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.phAgent;
}
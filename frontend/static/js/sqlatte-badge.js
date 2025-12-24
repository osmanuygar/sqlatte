(function() {
    'use strict';

    // Configuration
    const BADGE_CONFIG = {
        apiBase: (function() {
            if (window.location.protocol === 'file:') {
                return 'http://localhost:8000';
            }
            if (window.location.hostname === 'localhost' ||
                window.location.hostname === '127.0.0.1' ||
                window.location.hostname === '') {
                return 'http://localhost:8000';
            }
            return window.location.protocol + '//' + window.location.hostname + ':8000';
        })(),
        position: 'bottom-right',
        autoShowDelay: 1000,
        title: 'SQLatte Assistant ☕',
        placeholder: "Ask a question... (e.g., 'Hello!' or 'Show me customers')",
        customStyle: null,
        openByDefault: false,
        fullscreen: false
    };

    // State
    let isModalOpen = false;
    let selectedTables = [];
    let currentSchema = '';
    let sessionId = null;

    // Results cache for CSV export
    window.sqlatteResultsCache = {};

    /**
     * CSV EXPORT FUNCTIONALITY (NEW!)
     */
    function exportToCSV(resultId) {
        const cached = window.sqlatteResultsCache[resultId];
        if (!cached) {
            alert('Results not found. Please run the query again.');
            return;
        }

        const { columns, data } = cached;

        try {
            // Generate CSV content
            const csv = generateCSV(columns, data);

            // Create download link
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);

            // Generate filename with timestamp
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
            const filename = `sqlatte_export_${timestamp}.csv`;

            link.setAttribute('href', url);
            link.setAttribute('download', filename);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            console.log('✅ CSV exported:', filename);

            // Show success message
            showToast('📥 CSV exported successfully!', 'success');

        } catch (error) {
            console.error('CSV export error:', error);
            alert('Failed to export CSV: ' + error.message);
        }
    }

    function generateCSV(columns, data) {
        let csv = '';

        // Add headers
        csv += columns.map(col => escapeCSVField(col)).join(',') + '\n';

        // Add data rows
        data.forEach(row => {
            csv += row.map(cell => escapeCSVField(String(cell))).join(',') + '\n';
        });

        return csv;
    }

    function escapeCSVField(field) {
        // Handle null/undefined
        if (field === null || field === undefined) {
            return '';
        }

        // Convert to string
        field = String(field);

        // If field contains comma, newline, or quote, wrap in quotes and escape quotes
        if (field.includes(',') || field.includes('\n') || field.includes('"')) {
            return '"' + field.replace(/"/g, '""') + '"';
        }

        return field;
    }

    function showToast(message, type = 'info') {
        // Create toast element
        const toast = document.createElement('div');
        toast.className = `sqlatte-toast sqlatte-toast-${type}`;
        toast.textContent = message;

        document.body.appendChild(toast);

        // Trigger animation
        setTimeout(() => toast.classList.add('sqlatte-toast-show'), 10);

        // Remove after 3 seconds
        setTimeout(() => {
            toast.classList.remove('sqlatte-toast-show');
            setTimeout(() => document.body.removeChild(toast), 300);
        }, 3000);
    }

    /**
     * SESSION MANAGEMENT
     */
    function getOrCreateSession() {
        const storedSessionId = localStorage.getItem('sqlatte_session_id');

        if (storedSessionId) {
            console.log('📦 Using existing session:', storedSessionId.substring(0, 8) + '...');
            sessionId = storedSessionId;
        } else {
            console.log('🆕 New session will be created on first message');
            sessionId = null;
        }

        return sessionId;
    }

    function saveSession(newSessionId) {
        sessionId = newSessionId;
        localStorage.setItem('sqlatte_session_id', newSessionId);
        console.log('💾 Session saved:', newSessionId.substring(0, 8) + '...');
    }

    function clearSession() {
        sessionId = null;
        localStorage.removeItem('sqlatte_session_id');
        console.log('🗑️  Session cleared');
    }

    /**
     * Create widget
     */
    function createWidget() {
        if (document.getElementById('sqlatte-widget')) return;

        getOrCreateSession();

        const widget = document.createElement('div');
        widget.id = 'sqlatte-widget';
        widget.className = 'sqlatte-widget sqlatte-widget-' + BADGE_CONFIG.position;

        const badge = document.createElement('button');
        badge.className = 'sqlatte-badge-btn';
        badge.title = 'Ask SQLatte Anything';
        badge.onclick = toggleModal;

        badge.innerHTML = `
            <svg width="32" height="32" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="sqlatte-widget-cup" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:#A67C52;stop-opacity:1" />
                        <stop offset="100%" style="stop-color:#8B6F47;stop-opacity:1" />
                    </linearGradient>
                </defs>
                <path d="M 60 70 L 68 145 Q 68 152 75 152 L 125 152 Q 132 152 132 145 L 140 70 Z"
                      fill="url(#sqlatte-widget-cup)"/>
                <ellipse cx="100" cy="70" rx="40" ry="9" fill="#D4A574"/>
                <g opacity="0.85">
                    <circle cx="100" cy="30" r="4.5" fill="#D4A574">
                        <animate attributeName="r" values="4.5;5.5;4.5" dur="2s" repeatCount="indefinite"/>
                        <animate attributeName="opacity" values="0.6;1;0.6" dur="2s" repeatCount="indefinite"/>
                    </circle>
                    <circle cx="85" cy="35" r="4" fill="#D4A574">
                        <animate attributeName="r" values="4;5;4" dur="2s" begin="0.2s" repeatCount="indefinite"/>
                    </circle>
                    <circle cx="115" cy="35" r="4" fill="#D4A574">
                        <animate attributeName="r" values="4;5;4" dur="2s" begin="0.4s" repeatCount="indefinite"/>
                    </circle>
                </g>
            </svg>
            <span class="sqlatte-badge-pulse"></span>
        `;

        widget.appendChild(badge);
        document.body.appendChild(widget);
        console.log('✅ Badge widget added to body');

        const modal = createModal();
        document.body.appendChild(modal);
        console.log('✅ Modal added to body (outside widget)');

        injectStyles();

        setTimeout(() => {
            widget.classList.add('sqlatte-widget-visible');
        }, BADGE_CONFIG.autoShowDelay);

        loadTables();

        if (BADGE_CONFIG.openByDefault) {
            setTimeout(() => openModal(), BADGE_CONFIG.autoShowDelay + 500);
        }
    }

    /**
     * Create modal
     */
    function createModal() {
        const modal = document.createElement('div');
        modal.className = 'sqlatte-modal';
        modal.id = 'sqlatte-modal';

        modal.innerHTML = `
            <div class="sqlatte-modal-header">
                <div class="sqlatte-modal-title">
                    <svg width="24" height="24" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
                        <defs>
                            <linearGradient id="modal-cup" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" style="stop-color:#A67C52;stop-opacity:1" />
                                <stop offset="100%" style="stop-color:#8B6F47;stop-opacity:1" />
                            </linearGradient>
                        </defs>
                        <path d="M 60 70 L 68 145 Q 68 152 75 152 L 125 152 Q 132 152 132 145 L 140 70 Z"
                              fill="url(#modal-cup)"/>
                        <ellipse cx="100" cy="70" rx="40" ry="9" fill="#D4A574"/>
                    </svg>
                    <span>${BADGE_CONFIG.title}</span>
                </div>
                <div class="sqlatte-modal-actions">
                    <button class="sqlatte-modal-clear" onclick="SQLatteWidget.clearChat()" title="Clear Chat">🗑️</button>
                    <button class="sqlatte-modal-minimize" onclick="SQLatteWidget.minimize()" title="Minimize">−</button>
                    <button class="sqlatte-modal-close" onclick="SQLatteWidget.close()" title="Close">×</button>
                </div>
            </div>

            <div class="sqlatte-modal-toolbar">
                <label>Tables:</label>
                <select id="sqlatte-table-select" multiple onchange="SQLatteWidget.handleTableChange()">
                    <option value="">Loading...</option>
                </select>
                <small>Ctrl+Click for multiple</small>
            </div>

            <div class="sqlatte-modal-body">
                <div class="sqlatte-chat-area" id="sqlatte-chat-area">
                    <div class="sqlatte-empty-state">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                        </svg>
                        <h3>Welcome to SQLatte!</h3>
                        <p>I remember our conversation! Ask me anything.</p>
                        <p class="text-xs">Try: "Hello!" or select tables above to query your data</p>
                    </div>
                </div>

                <div class="sqlatte-input-area">
                    <textarea
                        id="sqlatte-input"
                        placeholder="${BADGE_CONFIG.placeholder}"
                        rows="2"
                        onkeydown="if(event.key==='Enter' && !event.shiftKey){event.preventDefault();SQLatteWidget.sendMessage();}"
                    ></textarea>
                    <button id="sqlatte-send-btn" onclick="SQLatteWidget.sendMessage()">
                        <span id="sqlatte-btn-text">Send</span>
                    </button>
                </div>
            </div>
        `;

        return modal;
    }

    function toggleModal() {
        if (isModalOpen) {
            closeModal();
        } else {
            openModal();
        }
    }

    function openModal() {
        const modal = document.getElementById('sqlatte-modal');
        if (modal) {
            if (BADGE_CONFIG.fullscreen) {
                modal.classList.add('sqlatte-modal-fullscreen');
            }

            modal.classList.add('sqlatte-modal-open');
            isModalOpen = true;

            setTimeout(() => {
                const input = document.getElementById('sqlatte-input');
                if (input) input.focus();
            }, 300);
        }
    }

    function closeModal() {
        const modal = document.getElementById('sqlatte-modal');
        if (modal) {
            modal.classList.remove('sqlatte-modal-open');
            modal.classList.remove('sqlatte-modal-fullscreen');
            isModalOpen = false;
        }
    }

    function minimizeModal() {
        closeModal();
    }

    function clearChat() {
        if (!confirm('Clear conversation history? This will start a new chat.')) {
            return;
        }

        clearSession();

        const chatArea = document.getElementById('sqlatte-chat-area');
        if (chatArea) {
            chatArea.innerHTML = `
                <div class="sqlatte-empty-state">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <h3>New Conversation</h3>
                    <p>Your previous chat has been cleared.</p>
                    <p class="text-xs">Ask me anything to start fresh!</p>
                </div>
            `;
        }

        console.log('🗑️  Chat cleared, new session will be created');
    }

    async function loadTables() {
        const select = document.getElementById('sqlatte-table-select');
        if (!select) return;

        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/tables`);

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const data = await response.json();
            select.innerHTML = '';

            if (data.tables && data.tables.length > 0) {
                data.tables.forEach(table => {
                    const option = document.createElement('option');
                    option.value = table;
                    option.textContent = table;
                    select.appendChild(option);
                });
            } else {
                select.innerHTML = '<option value="">No tables available</option>';
            }

        } catch (error) {
            console.error('Error loading tables:', error);
            select.innerHTML = '<option value="">Error loading tables</option>';

            addMessage('assistant', `
                <div class="sqlatte-error">
                    <strong>⚠️ Connection Error</strong><br>
                    Could not connect to SQLatte backend.<br><br>
                    <strong>Make sure:</strong><br>
                    1. Backend is running: <code>python run.py</code><br>
                    2. API URL: ${BADGE_CONFIG.apiBase}
                </div>
            `);
        }
    }

    async function handleTableChange() {
        const select = document.getElementById('sqlatte-table-select');
        if (!select) return;

        selectedTables = Array.from(select.selectedOptions).map(opt => opt.value);

        if (selectedTables.length === 0) {
            currentSchema = '';
            return;
        }

        try {
            if (selectedTables.length === 1) {
                const response = await fetch(`${BADGE_CONFIG.apiBase}/schema/${selectedTables[0]}`);
                const data = await response.json();
                currentSchema = data.schema;
            } else {
                const response = await fetch(`${BADGE_CONFIG.apiBase}/schema/multiple`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tables: selectedTables })
                });
                const data = await response.json();
                currentSchema = data.combined_schema;
            }
        } catch (error) {
            console.error('Error loading schema:', error);
        }
    }

    function addMessage(role, content) {
        const chatArea = document.getElementById('sqlatte-chat-area');
        if (!chatArea) return;

        const empty = chatArea.querySelector('.sqlatte-empty-state');
        if (empty) empty.remove();

        const messageDiv = document.createElement('div');
        messageDiv.className = `sqlatte-message sqlatte-message-${role}`;

        const avatar = document.createElement('div');
        avatar.className = 'sqlatte-message-avatar';
        avatar.textContent = role === 'user' ? '👤' : '☕';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'sqlatte-message-content';
        contentDiv.innerHTML = content;

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(contentDiv);
        chatArea.appendChild(messageDiv);

        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function formatTable(columns, data) {
        if (!data || data.length === 0) {
            return '<div class="text-sm" style="opacity: 0.7; margin-top: 8px;">No results returned.</div>';
        }

        // Generate unique ID for this result set
        const resultId = 'result-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);

        // Store data for CSV export
        window.sqlatteResultsCache[resultId] = { columns, data };

        let html = '<div class="sqlatte-results-container">';

        // Export toolbar
        html += `<div class="sqlatte-results-toolbar">`;
        html += `<button class="sqlatte-export-btn" onclick="SQLatteWidget.exportCSV('${resultId}')" title="Export to CSV">`;
        html += `📥 Export CSV</button>`;
        html += `<span class="text-xs" style="opacity: 0.7;">${data.length} rows</span>`;
        html += `</div>`;

        // Table
        html += '<table class="sqlatte-results-table"><thead><tr>';

        columns.forEach(col => {
            const colName = escapeHtml(col);
            html += `<th title="${colName}">${colName}</th>`;
        });
        html += '</tr></thead><tbody>';

        data.forEach(row => {
            html += '<tr>';
            row.forEach(cell => {
                const cellValue = String(cell);
                const escapedValue = escapeHtml(cellValue);
                html += `<td title="${escapedValue}">${escapedValue}</td>`;
            });
            html += '</tr>';
        });

        html += '</tbody></table>';
        html += '</div>';

        return html;
    }

    function renderHTML(html) {
        const sanitized = html
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/javascript:/gi, '')
            .replace(/on\w+\s*=/gi, '');

        return sanitized;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async function sendMessage() {
        const input = document.getElementById('sqlatte-input');
        const sendBtn = document.getElementById('sqlatte-send-btn');

        if (!input || !sendBtn) return;

        const question = input.value.trim();
        if (!question) return;

        sendBtn.disabled = true;
        sendBtn.innerHTML = '<span class="sqlatte-loading"></span>';
        input.disabled = true;

        addMessage('user', escapeHtml(question));
        input.value = '';

        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question: question,
                    table_schema: currentSchema,
                    session_id: sessionId
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Query failed');
            }

            const result = await response.json();

            if (result.session_id) {
                saveSession(result.session_id);
            }

            let responseHTML = '';

            if (result.response_type === 'chat') {
                responseHTML = `<div class="sqlatte-chat-message">${renderHTML(result.message)}</div>`;
            } else if (result.response_type === 'sql' || result.sql) {
                if (result.explanation) {
                    responseHTML += `<div class="sqlatte-explanation"><strong>💡 Explanation:</strong><br>${escapeHtml(result.explanation)}</div>`;
                }

                responseHTML += `<div class="sqlatte-sql-code">${escapeHtml(result.sql)}</div>`;
                responseHTML += formatTable(result.columns, result.data);
            } else {
                const msg = result.message || JSON.stringify(result);
                if (msg.includes('<') && msg.includes('>')) {
                    responseHTML = `<div class="sqlatte-chat-message">${renderHTML(msg)}</div>`;
                } else {
                    responseHTML = `<div class="sqlatte-chat-message">${escapeHtml(msg)}</div>`;
                }
            }

            addMessage('assistant', responseHTML);

        } catch (error) {
            addMessage('assistant', `<div class="sqlatte-error"><strong>❌ Error:</strong> ${escapeHtml(error.message)}</div>`);
        } finally {
            sendBtn.disabled = false;
            sendBtn.innerHTML = '<span id="sqlatte-btn-text">Send</span>';
            input.disabled = false;
            input.focus();
        }
    }

    /**
     * Inject styles - INLINE CSS (with new CSV export styles)
     */
    function injectStyles() {
        if (document.getElementById('sqlatte-widget-styles')) return;

        const style = document.createElement('style');
        style.id = 'sqlatte-widget-styles';
        style.textContent = `
/* SQLatte Widget Styles - With CSV Export */

/* ... (previous styles remain same) ... */

/* Widget Container */
.sqlatte-widget {
    position: fixed;
    z-index: 999999;
    opacity: 0;
    transform: translateY(20px);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.sqlatte-widget.sqlatte-widget-visible {
    opacity: 1;
    transform: translateY(0);
}

/* Positions */
.sqlatte-widget.sqlatte-widget-bottom-right {
    bottom: 20px;
    right: 20px;
}

.sqlatte-widget.sqlatte-widget-bottom-left {
    bottom: 20px;
    left: 20px;
}

.sqlatte-widget.sqlatte-widget-top-right {
    top: 20px;
    right: 20px;
}

.sqlatte-widget.sqlatte-widget-top-left {
    top: 20px;
    left: 20px;
}

/* Badge Button */
.sqlatte-badge-btn {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    border: none;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3), 0 0 0 3px rgba(212, 165, 116, 0.2);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.3s;
    position: relative;
}

.sqlatte-badge-btn:hover {
    transform: translateY(-4px) scale(1.05);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4), 0 0 0 3px rgba(212, 165, 116, 0.4);
}

.sqlatte-badge-btn:active {
    transform: translateY(-2px) scale(1.02);
}

.sqlatte-badge-btn svg {
    filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
}

/* Badge Pulse Animation */
.sqlatte-badge-pulse {
    position: absolute;
    top: -2px;
    right: -2px;
    width: 16px;
    height: 16px;
    background: #4ade80;
    border-radius: 50%;
    border: 3px solid #1a1a1a;
    animation: sqlatte-pulse 2s infinite;
}

@keyframes sqlatte-pulse {
    0%, 100% {
        transform: scale(1);
        opacity: 1;
    }
    50% {
        transform: scale(1.2);
        opacity: 0.8;
    }
}

/* Modal - FULLSCREEN MODE SUPPORT */
.sqlatte-modal {
    position: fixed;
    background: #1a1a1a;
    display: flex;
    flex-direction: column;
    opacity: 0;
    pointer-events: none;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    overflow: hidden;
    z-index: 2147483647;
}

/* Default: Small modal (bottom-right) */
.sqlatte-modal:not(.sqlatte-modal-fullscreen) {
    bottom: 80px;
    right: 20px;
    width: 600px;
    max-width: 90vw;
    height: 600px;
    max-height: 80vh;
    border-radius: 16px;
    box-shadow: 0 24px 48px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(212, 165, 116, 0.2);
    transform: scale(0.9) translateY(20px);
}

/* FULLSCREEN MODE */
.sqlatte-modal.sqlatte-modal-fullscreen {
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    max-width: none !important;
    max-height: none !important;
    border-radius: 0 !important;
    transform: none !important;
    box-shadow: none !important;
    margin: 0 !important;
    padding: 0 !important;
}

.sqlatte-modal.sqlatte-modal-open {
    opacity: 1;
    pointer-events: all;
}

.sqlatte-modal.sqlatte-modal-open:not(.sqlatte-modal-fullscreen) {
    transform: scale(1) translateY(0);
}

/* Modal Header */
.sqlatte-modal-header {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    padding: 16px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.sqlatte-modal-title {
    display: flex;
    align-items: center;
    gap: 10px;
    color: white;
    font-weight: 600;
    font-size: 16px;
}

.sqlatte-modal-title svg {
    filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
}

.sqlatte-modal-actions {
    display: flex;
    gap: 8px;
}

.sqlatte-modal-minimize,
.sqlatte-modal-close,
.sqlatte-modal-clear {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.1);
    border: none;
    color: white;
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
}

.sqlatte-modal-minimize:hover,
.sqlatte-modal-close:hover,
.sqlatte-modal-clear:hover {
    background: rgba(255, 255, 255, 0.2);
}

/* Modal Toolbar */
.sqlatte-modal-toolbar {
    padding: 12px 16px;
    background: #242424;
    border-bottom: 1px solid #333;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.sqlatte-modal-toolbar label {
    font-size: 12px;
    color: #a0a0a0;
    font-weight: 500;
}

.sqlatte-modal-toolbar select {
    flex: 1;
    min-width: 200px;
    padding: 6px 10px;
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 6px;
    color: #e0e0e0;
    font-size: 12px;
    cursor: pointer;
}

.sqlatte-modal-toolbar select:focus {
    outline: none;
    border-color: #D4A574;
}

.sqlatte-modal-toolbar small {
    font-size: 10px;
    color: #707070;
}

/* Modal Body */
.sqlatte-modal-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

/* Chat Area */
.sqlatte-chat-area {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    background: #0f0f0f;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.sqlatte-chat-area::-webkit-scrollbar {
    width: 6px;
}

.sqlatte-chat-area::-webkit-scrollbar-track {
    background: #1a1a1a;
}

.sqlatte-chat-area::-webkit-scrollbar-thumb {
    background: #333;
    border-radius: 3px;
}

/* Empty State */
.sqlatte-empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    color: #a0a0a0;
    text-align: center;
    padding: 20px;
}

.sqlatte-empty-state svg {
    width: 48px;
    height: 48px;
    margin-bottom: 16px;
    opacity: 0.3;
    color: #D4A574;
}

.sqlatte-empty-state h3 {
    font-size: 16px;
    margin-bottom: 6px;
    color: #e0e0e0;
}

.sqlatte-empty-state p {
    font-size: 13px;
    color: #a0a0a0;
    margin: 4px 0;
}

/* Messages */
.sqlatte-message {
    display: flex;
    gap: 10px;
    animation: sqlatte-fadeIn 0.3s ease;
}

@keyframes sqlatte-fadeIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.sqlatte-message.sqlatte-message-user {
    flex-direction: row-reverse;
}

.sqlatte-message-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    flex-shrink: 0;
}

.sqlatte-message.sqlatte-message-user .sqlatte-message-avatar {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.sqlatte-message.sqlatte-message-assistant .sqlatte-message-avatar {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
}

.sqlatte-message-content {
    max-width: 80%;
    background: #242424;
    padding: 10px 14px;
    border-radius: 10px;
    border: 1px solid #333;
    font-size: 13px;
    line-height: 1.5;
    color: #e0e0e0;
}

.sqlatte-message.sqlatte-message-user .sqlatte-message-content {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
}

/* SQL Code */
.sqlatte-sql-code {
    background: #000;
    color: #00ff00;
    padding: 12px;
    border-radius: 6px;
    margin: 8px 0;
    overflow-x: auto;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    border: 1px solid #1a1a1a;
}

/* Explanation */
.sqlatte-explanation {
    color: #a0a0a0;
    font-size: 12px;
    margin: 8px 0;
    padding: 10px;
    background: rgba(212, 165, 116, 0.1);
    border-left: 3px solid #D4A574;
    border-radius: 4px;
}

/* Error */
.sqlatte-error {
    color: #f87171;
    font-size: 12px;
    margin: 8px 0;
    padding: 10px;
    background: rgba(248, 113, 113, 0.1);
    border-left: 3px solid #f87171;
    border-radius: 4px;
}

/* ============================================
   CSV EXPORT STYLES (NEW!)
   ============================================ */

/* Results Container */
.sqlatte-results-container {
    margin: 12px 0;
}

/* Export Toolbar */
.sqlatte-results-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: #242424;
    border: 1px solid #333;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
}

/* Export Button */
.sqlatte-export-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}

.sqlatte-export-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
    background: linear-gradient(135deg, #059669 0%, #047857 100%);
}

.sqlatte-export-btn:active {
    transform: translateY(0);
}

/* Toast Notification */
.sqlatte-toast {
    position: fixed;
    top: 80px;
    right: 20px;
    padding: 12px 20px;
    background: #1a1a1a;
    color: white;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    font-size: 13px;
    font-weight: 500;
    opacity: 0;
    transform: translateX(100px);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    z-index: 999999999;
    border: 1px solid #333;
}

.sqlatte-toast.sqlatte-toast-show {
    opacity: 1;
    transform: translateX(0);
}

.sqlatte-toast.sqlatte-toast-success {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    border-color: #10b981;
}

.sqlatte-toast.sqlatte-toast-error {
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
    border-color: #ef4444;
}

.sqlatte-toast.sqlatte-toast-info {
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    border-color: #3b82f6;
}

/* Results Table - WITH CSV Export */
.sqlatte-results-table {
    width: 100%;
    border-collapse: collapse;
    background: #1a1a1a;
    border: 1px solid #333;
    border-top: none;
    border-radius: 0 0 6px 6px;
    overflow: hidden;
    font-size: 12px;
    display: block;
    max-height: 400px;
    overflow-x: auto;
    overflow-y: auto;
}

.sqlatte-results-table thead {
    display: table;
    width: 100%;
    table-layout: auto;
    position: sticky;
    top: 0;
    z-index: 10;
    background: #242424;
}

.sqlatte-results-table tbody {
    display: table;
    width: 100%;
    table-layout: auto;
}

.sqlatte-results-table::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

.sqlatte-results-table::-webkit-scrollbar-track {
    background: #1a1a1a;
}

.sqlatte-results-table::-webkit-scrollbar-thumb {
    background: #555;
    border-radius: 4px;
}

.sqlatte-results-table::-webkit-scrollbar-thumb:hover {
    background: #666;
}

.sqlatte-results-table th {
    padding: 10px 16px;
    text-align: left;
    font-weight: 600;
    color: #D4A574;
    background: #242424;
    border-bottom: 2px solid #333;
    white-space: nowrap;
    min-width: 120px;
    position: sticky;
    top: 0;
}

.sqlatte-results-table td {
    padding: 8px 16px;
    border-bottom: 1px solid #333;
    color: #e0e0e0;
    min-width: 120px;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: default;
    transition: background 0.2s ease;
}

.sqlatte-results-table td:hover {
    background: rgba(212, 165, 116, 0.15);
    color: #fff;
}

.sqlatte-results-table tbody tr:hover {
    background: rgba(212, 165, 116, 0.05);
}

.sqlatte-results-table tbody tr:hover td:hover {
    background: rgba(212, 165, 116, 0.2);
}

.sqlatte-results-table tr:last-child td {
    border-bottom: none;
}

/* Input Area */
.sqlatte-input-area {
    padding: 12px 16px;
    border-top: 1px solid #333;
    display: flex;
    gap: 8px;
    align-items: flex-end;
    background: #1a1a1a;
}

.sqlatte-input-area textarea {
    flex: 1;
    padding: 10px 12px;
    border: 1px solid #333;
    border-radius: 8px;
    background: #0f0f0f;
    color: #e0e0e0;
    font-size: 13px;
    font-family: inherit;
    resize: none;
    transition: all 0.2s;
}

.sqlatte-input-area textarea:focus {
    outline: none;
    border-color: #D4A574;
    background: #1a1a1a;
}

.sqlatte-input-area textarea::placeholder {
    color: #707070;
}

.sqlatte-input-area button {
    padding: 10px 20px;
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
}

.sqlatte-input-area button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(212, 165, 116, 0.3);
}

.sqlatte-input-area button:active {
    transform: translateY(0);
}

.sqlatte-input-area button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* Loading Spinner */
.sqlatte-loading {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: sqlatte-spin 0.8s linear infinite;
}

@keyframes sqlatte-spin {
    to {
        transform: rotate(360deg);
    }
}

/* Responsive */
@media (max-width: 768px) {
    .sqlatte-modal:not(.sqlatte-modal-fullscreen) {
        width: calc(100vw - 20px);
        height: calc(100vh - 100px);
        bottom: 70px;
        left: 10px;
        right: 10px;
    }

    .sqlatte-widget.sqlatte-widget-bottom-right,
    .sqlatte-widget.sqlatte-widget-bottom-left {
        bottom: 10px;
        right: 10px;
        left: auto;
    }

    .sqlatte-modal-toolbar select {
        min-width: 150px;
    }

    .sqlatte-toast {
        right: 10px;
        left: 10px;
        top: 70px;
    }
}

/* Utility Classes */
.text-xs {
    font-size: 11px;
}

.text-sm {
    font-size: 12px;
}
        `;

        document.head.appendChild(style);
        console.log('✅ Inline CSS injected with CSV export styles');
    }

    function init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', createWidget);
        } else {
            createWidget();
        }
    }

    init();

    window.SQLatteWidget = {
        open: openModal,
        close: closeModal,
        minimize: minimizeModal,
        toggle: toggleModal,
        sendMessage: sendMessage,
        handleTableChange: handleTableChange,
        clearChat: clearChat,
        exportCSV: exportToCSV,  // NEW: CSV export function
        getSessionId: function() { return sessionId; },
        configure: function(options) {
            Object.assign(BADGE_CONFIG, options);

            const widget = document.getElementById('sqlatte-widget');
            const modal = document.getElementById('sqlatte-modal');

            if (widget) widget.remove();
            if (modal) modal.remove();

            setTimeout(createWidget, 100);
        },
        getConfig: function() {
            return { ...BADGE_CONFIG };
        }
    };

    window.SQLatteBadge = window.SQLatteWidget;

})();
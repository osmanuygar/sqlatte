(function() {
    'use strict';

    // Configuration
    const BADGE_CONFIG = {
        // Smart API base detection
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
        openByDefault: false
    };

    // State
    let isModalOpen = false;
    let selectedTables = [];
    let currentSchema = '';

    /**
     * Create widget
     */
    function createWidget() {
        if (document.getElementById('sqlatte-widget')) return;

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

        const modal = createModal();

        widget.appendChild(badge);
        widget.appendChild(modal);

        injectStyles();

        document.body.appendChild(widget);

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
                        <p>Ask me anything! I can help you query data or just chat.</p>
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
            isModalOpen = false;
        }
    }

    function minimizeModal() {
        closeModal();
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
                currentSchema = data.schema;
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

        let html = '<table class="sqlatte-results-table"><thead><tr>';
        columns.forEach(col => {
            html += `<th>${escapeHtml(col)}</th>`;
        });
        html += '</tr></thead><tbody>';

        data.forEach(row => {
            html += '<tr>';
            row.forEach(cell => {
                html += `<td>${escapeHtml(String(cell))}</td>`;
            });
            html += '</tr>';
        });

        html += '</tbody></table>';
        html += `<div class="text-xs" style="opacity: 0.7; margin-top: 8px;">${data.length} rows returned</div>`;

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
                    table_schema: currentSchema
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Query failed');
            }

            const result = await response.json();

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

    function injectStyles() {
        // Check if CSS already loaded
        if (document.getElementById('sqlatte-widget-styles')) return;

        // Load external CSS file
        const link = document.createElement('link');
        link.id = 'sqlatte-widget-styles';
        link.rel = 'stylesheet';
        link.href = BADGE_CONFIG.apiBase + '/static/css/sqlatte-widget.css';

        document.head.appendChild(link);

        console.log('✅ External CSS loaded:', link.href);
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
        configure: function(options) {
            Object.assign(BADGE_CONFIG, options);
            const widget = document.getElementById('sqlatte-widget');
            if (widget) widget.remove();
            setTimeout(createWidget, 100);
        },
        getConfig: function() {
            return { ...BADGE_CONFIG };
        }
    };

    window.SQLatteBadge = window.SQLatteWidget;

})();
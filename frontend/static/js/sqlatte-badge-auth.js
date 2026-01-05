(function() {
    'use strict';

    // Configuration
    const AUTH_WIDGET_CONFIG = {
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
        title: 'SQLatte Auth ☕',
        placeholder: "Ask a question about your data...",
        fullscreen: false,
        storageKey: 'sqlatte_auth_session'
    };

    // State
    let isAuthenticated = false;
    let authSessionId = null;
    let userInfo = null;
    let isModalOpen = false;
    let selectedTables = [];
    let currentSchema = '';

    /**
     * ============================================
     * SESSION MANAGEMENT
     * ============================================
     */

    function saveSession(sessionId, user) {
        authSessionId = sessionId;
        userInfo = user;
        isAuthenticated = true;
        
        localStorage.setItem(AUTH_WIDGET_CONFIG.storageKey, JSON.stringify({
            sessionId: sessionId,
            user: user,
            timestamp: Date.now()
        }));
    }

    function loadSession() {
        const stored = localStorage.getItem(AUTH_WIDGET_CONFIG.storageKey);
        if (!stored) return false;

        try {
            const data = JSON.parse(stored);
            authSessionId = data.sessionId;
            userInfo = data.user;
            isAuthenticated = true;
            return true;
        } catch (e) {
            console.error('Failed to load session:', e);
            return false;
        }
    }

    function clearSession() {
        authSessionId = null;
        userInfo = null;
        isAuthenticated = false;
        localStorage.removeItem(AUTH_WIDGET_CONFIG.storageKey);
    }

    async function validateSession() {
        if (!authSessionId) return false;

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/validate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: authSessionId })
            });

            const data = await response.json();
            return data.valid;
        } catch (error) {
            console.error('Session validation error:', error);
            return false;
        }
    }

    /**
     * ============================================
     * LOGIN FUNCTIONALITY
     * ============================================
     */

    async function login(credentials) {
        const loginBtn = document.getElementById('sqlatte-auth-login-btn');
        const errorDiv = document.getElementById('sqlatte-auth-error');

        loginBtn.disabled = true;
        loginBtn.innerHTML = '<span class="sqlatte-loading"></span> Connecting...';
        errorDiv.style.display = 'none';

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(credentials)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Login failed');
            }

            const result = await response.json();

            if (result.success) {
                saveSession(result.session_id, result.user);
                showToast('✅ Login successful!', 'success');
                closeLoginModal();
                await loadTablesAuth();
                openChatModal();
            } else {
                throw new Error('Login failed');
            }

        } catch (error) {
            console.error('Login error:', error);
            errorDiv.textContent = `❌ ${error.message}`;
            errorDiv.style.display = 'block';
        } finally {
            loginBtn.disabled = false;
            loginBtn.innerHTML = '🔓 Login';
        }
    }

    async function logout() {
        if (!authSessionId) return;

        try {
            await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/logout`, {
                method: 'POST',
                headers: { 'X-Session-ID': authSessionId }
            });

            clearSession();
            showToast('👋 Logged out', 'info');
            closeChatModal();
            selectedTables = [];
            currentSchema = '';

        } catch (error) {
            console.error('Logout error:', error);
        }
    }

    /**
     * ============================================
     * MODAL MANAGEMENT
     * ============================================
     */

    function createLoginModal() {
        const modal = document.createElement('div');
        modal.className = 'sqlatte-auth-modal';
        modal.id = 'sqlatte-auth-login-modal';

        modal.innerHTML = `
            <div class="sqlatte-auth-modal-content">
                <div class="sqlatte-auth-header">
                    <h2>🔐 SQLatte Login</h2>
                    <button class="sqlatte-auth-close" onclick="SQLatteAuthWidget.closeLoginModal()">×</button>
                </div>

                <div class="sqlatte-auth-body">
                    <div id="sqlatte-auth-error" class="sqlatte-auth-error" style="display: none;"></div>

                    <div class="sqlatte-auth-form">
                        <div class="sqlatte-form-group">
                            <label>Database Type</label>
                            <select id="sqlatte-auth-db-type" onchange="SQLatteAuthWidget.updateDBFields()">
                                <option value="trino">Trino</option>
                                <option value="postgresql">PostgreSQL</option>
                                <option value="mysql">MySQL</option>
                            </select>
                        </div>

                        <div class="sqlatte-form-group">
                            <label>Host</label>
                            <input type="text" id="sqlatte-auth-host" placeholder="trino.example.com" required>
                        </div>

                        <div class="sqlatte-form-group">
                            <label>Port</label>
                            <input type="number" id="sqlatte-auth-port" value="443" required>
                        </div>

                        <div class="sqlatte-form-group">
                            <label>Username</label>
                            <input type="text" id="sqlatte-auth-username" placeholder="your-username" required>
                        </div>

                        <div class="sqlatte-form-group">
                            <label>Password</label>
                            <input type="password" id="sqlatte-auth-password" placeholder="your-password" required>
                        </div>

                        <!-- Trino specific -->
                        <div id="sqlatte-auth-trino-fields">
                            <div class="sqlatte-form-group">
                                <label>Catalog</label>
                                <input type="text" id="sqlatte-auth-catalog" placeholder="hive" value="hive">
                            </div>
                            <div class="sqlatte-form-group">
                                <label>Schema</label>
                                <input type="text" id="sqlatte-auth-schema" placeholder="default" value="default">
                            </div>
                            <div class="sqlatte-form-group">
                                <label>HTTP Scheme</label>
                                <select id="sqlatte-auth-http-scheme">
                                    <option value="https">HTTPS</option>
                                    <option value="http">HTTP</option>
                                </select>
                            </div>
                        </div>

                        <!-- PostgreSQL/MySQL specific -->
                        <div id="sqlatte-auth-sql-fields" style="display: none;">
                            <div class="sqlatte-form-group">
                                <label>Database</label>
                                <input type="text" id="sqlatte-auth-database" placeholder="mydatabase">
                            </div>
                            <div class="sqlatte-form-group">
                                <label>Schema</label>
                                <input type="text" id="sqlatte-auth-schema-sql" placeholder="public" value="public">
                            </div>
                        </div>

                        <button id="sqlatte-auth-login-btn" class="sqlatte-auth-login-btn" onclick="SQLatteAuthWidget.handleLogin()">
                            🔓 Login
                        </button>
                    </div>
                </div>
            </div>
        `;

        return modal;
    }

    function createChatModal() {
        const modal = document.createElement('div');
        modal.className = 'sqlatte-auth-modal';
        modal.id = 'sqlatte-auth-chat-modal';

        modal.innerHTML = `
            <div class="sqlatte-modal-content">
                <div class="sqlatte-modal-header">
                    <div class="sqlatte-modal-title">
                        <svg width="24" height="24" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
                            <defs>
                                <linearGradient id="auth-cup" x1="0%" y1="0%" x2="0%" y2="100%">
                                    <stop offset="0%" style="stop-color:#A67C52;stop-opacity:1" />
                                    <stop offset="100%" style="stop-color:#8B6F47;stop-opacity:1" />
                                </linearGradient>
                            </defs>
                            <path d="M 60 70 L 68 145 Q 68 152 75 152 L 125 152 Q 132 152 132 145 L 140 70 Z"
                                  fill="url(#auth-cup)"/>
                            <ellipse cx="100" cy="70" rx="40" ry="9" fill="#D4A574"/>
                        </svg>
                        <span>${AUTH_WIDGET_CONFIG.title}</span>
                        <span class="sqlatte-auth-user-badge" id="sqlatte-auth-user-badge"></span>
                    </div>
                    <div class="sqlatte-modal-actions">
                        <button class="sqlatte-modal-btn" onclick="SQLatteAuthWidget.logout()" title="Logout">🚪</button>
                        <button class="sqlatte-modal-btn" onclick="SQLatteAuthWidget.closeChatModal()" title="Close">×</button>
                    </div>
                </div>

                <div class="sqlatte-modal-toolbar">
                    <label>Tables:</label>
                    <select id="sqlatte-auth-table-select" multiple onchange="SQLatteAuthWidget.handleTableChange()">
                        <option value="">Loading...</option>
                    </select>
                    <small>Ctrl+Click for multiple</small>
                </div>

                <div class="sqlatte-modal-body">
                    <div class="sqlatte-chat-area" id="sqlatte-auth-chat-area">
                        <div class="sqlatte-empty-state">
                            <h3>Welcome!</h3>
                            <p>Connected as: <strong id="sqlatte-auth-username-display"></strong></p>
                            <p>Ask me anything about your data</p>
                        </div>
                    </div>

                    <div class="sqlatte-input-area">
                        <textarea
                            id="sqlatte-auth-input"
                            placeholder="${AUTH_WIDGET_CONFIG.placeholder}"
                            rows="2"
                            onkeydown="if(event.key==='Enter' && !event.shiftKey){event.preventDefault();SQLatteAuthWidget.sendMessage();}"
                        ></textarea>
                        <button id="sqlatte-auth-send-btn" onclick="SQLatteAuthWidget.sendMessage()">
                            Send
                        </button>
                    </div>
                </div>
            </div>
        `;

        return modal;
    }

    function updateDBFields() {
        const dbType = document.getElementById('sqlatte-auth-db-type').value;
        const trinoFields = document.getElementById('sqlatte-auth-trino-fields');
        const sqlFields = document.getElementById('sqlatte-auth-sql-fields');
        const portInput = document.getElementById('sqlatte-auth-port');

        if (dbType === 'trino') {
            trinoFields.style.display = 'block';
            sqlFields.style.display = 'none';
            portInput.value = 443;
        } else if (dbType === 'postgresql') {
            trinoFields.style.display = 'none';
            sqlFields.style.display = 'block';
            portInput.value = 5432;
        } else if (dbType === 'mysql') {
            trinoFields.style.display = 'none';
            sqlFields.style.display = 'block';
            portInput.value = 3306;
        }
    }

    function handleLogin() {
        const dbType = document.getElementById('sqlatte-auth-db-type').value;
        const credentials = {
            database_type: dbType,
            host: document.getElementById('sqlatte-auth-host').value,
            port: parseInt(document.getElementById('sqlatte-auth-port').value),
            username: document.getElementById('sqlatte-auth-username').value,
            password: document.getElementById('sqlatte-auth-password').value,
        };

        if (dbType === 'trino') {
            credentials.catalog = document.getElementById('sqlatte-auth-catalog').value;
            credentials.schema = document.getElementById('sqlatte-auth-schema').value;
            credentials.http_scheme = document.getElementById('sqlatte-auth-http-scheme').value;
        } else {
            credentials.database = document.getElementById('sqlatte-auth-database').value;
            credentials.schema = document.getElementById('sqlatte-auth-schema-sql').value;
        }

        login(credentials);
    }

    /**
     * ============================================
     * TABLE & QUERY MANAGEMENT
     * ============================================
     */

    async function loadTablesAuth() {
        const select = document.getElementById('sqlatte-auth-table-select');
        if (!select) return;

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/tables`, {
                headers: { 'X-Session-ID': authSessionId }
            });

            if (!response.ok) throw new Error('Failed to load tables');

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
        }
    }

    async function handleTableChange() {
        const select = document.getElementById('sqlatte-auth-table-select');
        if (!select) return;

        selectedTables = Array.from(select.selectedOptions).map(opt => opt.value);

        if (selectedTables.length === 0) {
            currentSchema = '';
            return;
        }

        try {
            let response;
            if (selectedTables.length === 1) {
                response = await fetch(
                    `${AUTH_WIDGET_CONFIG.apiBase}/auth/schema/${selectedTables[0]}`,
                    { headers: { 'X-Session-ID': authSessionId } }
                );
            } else {
                response = await fetch(
                    `${AUTH_WIDGET_CONFIG.apiBase}/auth/schema/multiple`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Session-ID': authSessionId
                        },
                        body: JSON.stringify({ tables: selectedTables })
                    }
                );
            }

            const data = await response.json();
            currentSchema = data.schema || data.combined_schema || '';

        } catch (error) {
            console.error('Error loading schema:', error);
        }
    }

    async function sendMessage() {
        const input = document.getElementById('sqlatte-auth-input');
        const sendBtn = document.getElementById('sqlatte-auth-send-btn');

        if (!input || !sendBtn) return;

        const question = input.value.trim();
        if (!question) return;

        sendBtn.disabled = true;
        sendBtn.innerHTML = '<span class="sqlatte-loading"></span>';
        input.disabled = true;

        addMessage('user', escapeHtml(question));
        input.value = '';

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Session-ID': authSessionId
                },
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
                responseHTML = `<div class="sqlatte-chat-message">${escapeHtml(result.message)}</div>`;
            } else if (result.response_type === 'sql') {
                responseHTML = formatTable(result.columns, result.data, result.sql, result.explanation);
            }

            addMessage('assistant', responseHTML);

        } catch (error) {
            addMessage('assistant', `<div class="sqlatte-error"><strong>❌ Error:</strong> ${escapeHtml(error.message)}</div>`);
        } finally {
            sendBtn.disabled = false;
            sendBtn.innerHTML = 'Send';
            input.disabled = false;
            input.focus();
        }
    }

    function addMessage(role, content) {
        const chatArea = document.getElementById('sqlatte-auth-chat-area');
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

    function formatTable(columns, data, sql, explanation) {
        if (!data || data.length === 0) {
            return '<div class="text-sm" style="opacity: 0.7;">No results returned.</div>';
        }

        let html = '';

        if (explanation) {
            html += `<div class="sqlatte-explanation"><strong>💡</strong> ${escapeHtml(explanation)}</div>`;
        }

        if (sql) {
            html += `<div class="sqlatte-sql-code"><pre>${escapeHtml(sql)}</pre></div>`;
        }

        html += '<table class="sqlatte-results-table"><thead><tr>';
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

        return html;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `sqlatte-toast sqlatte-toast-${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.classList.add('sqlatte-toast-show'), 10);
        setTimeout(() => {
            toast.classList.remove('sqlatte-toast-show');
            setTimeout(() => document.body.removeChild(toast), 300);
        }, 3000);
    }

    /**
     * ============================================
     * MODAL CONTROLS
     * ============================================
     */

    function openLoginModal() {
        const modal = document.getElementById('sqlatte-auth-login-modal');
        if (modal) {
            modal.classList.add('sqlatte-auth-modal-open');
        }
    }

    function closeLoginModal() {
        const modal = document.getElementById('sqlatte-auth-login-modal');
        if (modal) {
            modal.classList.remove('sqlatte-auth-modal-open');
        }
    }

    function openChatModal() {
        const modal = document.getElementById('sqlatte-auth-chat-modal');
        if (modal) {
            // Update user badge
            const userBadge = document.getElementById('sqlatte-auth-user-badge');
            const usernameDisplay = document.getElementById('sqlatte-auth-username-display');
            if (userBadge && userInfo) {
                userBadge.textContent = `👤 ${userInfo.username}`;
            }
            if (usernameDisplay && userInfo) {
                usernameDisplay.textContent = userInfo.username;
            }

            modal.classList.add('sqlatte-auth-modal-open');
            isModalOpen = true;

            setTimeout(() => {
                const input = document.getElementById('sqlatte-auth-input');
                if (input) input.focus();
            }, 300);
        }
    }

    function closeChatModal() {
        const modal = document.getElementById('sqlatte-auth-chat-modal');
        if (modal) {
            modal.classList.remove('sqlatte-auth-modal-open');
            isModalOpen = false;
        }
    }

    function toggleWidget() {
        if (isAuthenticated) {
            if (isModalOpen) {
                closeChatModal();
            } else {
                openChatModal();
            }
        } else {
            openLoginModal();
        }
    }

    /**
     * ============================================
     * WIDGET INITIALIZATION
     * ============================================
     */

    function createWidget() {
        if (document.getElementById('sqlatte-auth-widget')) return;

        // Create badge button
        const widget = document.createElement('div');
        widget.id = 'sqlatte-auth-widget';
        widget.className = 'sqlatte-widget sqlatte-widget-' + AUTH_WIDGET_CONFIG.position;

        const badge = document.createElement('button');
        badge.className = 'sqlatte-badge-btn';
        badge.title = 'SQLatte Auth';
        badge.onclick = toggleWidget;

        badge.innerHTML = `
            <svg width="32" height="32" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="sqlatte-auth-cup" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:#A67C52;stop-opacity:1" />
                        <stop offset="100%" style="stop-color:#8B6F47;stop-opacity:1" />
                    </linearGradient>
                </defs>
                <path d="M 60 70 L 68 145 Q 68 152 75 152 L 125 152 Q 132 152 132 145 L 140 70 Z"
                      fill="url(#sqlatte-auth-cup)"/>
                <ellipse cx="100" cy="70" rx="40" ry="9" fill="#D4A574"/>
            </svg>
            <span class="sqlatte-badge-pulse"></span>
        `;

        widget.appendChild(badge);
        document.body.appendChild(widget);

        // Create modals
        const loginModal = createLoginModal();
        const chatModal = createChatModal();
        document.body.appendChild(loginModal);
        document.body.appendChild(chatModal);

        // Inject styles
        injectStyles();

        // Show widget
        setTimeout(() => {
            widget.classList.add('sqlatte-widget-visible');
        }, 500);

        // Check for existing session
        const hasSession = loadSession();
        if (hasSession) {
            validateSession().then(valid => {
                if (valid) {
                    console.log('✅ Session restored');
                    loadTablesAuth();
                } else {
                    console.log('❌ Session expired');
                    clearSession();
                }
            });
        }
    }

    function injectStyles() {
        if (document.getElementById('sqlatte-auth-widget-styles')) return;

        const style = document.createElement('style');
        style.id = 'sqlatte-auth-widget-styles';
        style.textContent = `
/* SQLatte Auth Widget Styles */

.sqlatte-widget {
    position: fixed;
    z-index: 999999;
    opacity: 0;
    transform: translateY(20px);
    transition: all 0.3s;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.sqlatte-widget.sqlatte-widget-visible {
    opacity: 1;
    transform: translateY(0);
}

.sqlatte-widget.sqlatte-widget-bottom-right { bottom: 20px; right: 20px; }
.sqlatte-widget.sqlatte-widget-bottom-left { bottom: 20px; left: 20px; }

.sqlatte-badge-btn {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    border: none;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.3s;
    position: relative;
}

.sqlatte-badge-btn:hover {
    transform: translateY(-4px) scale(1.05);
}

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
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.2); opacity: 0.8; }
}

/* Auth Modal */
.sqlatte-auth-modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.3s;
    z-index: 999999;
    backdrop-filter: blur(4px);
}

.sqlatte-auth-modal.sqlatte-auth-modal-open {
    opacity: 1;
    pointer-events: all;
}

.sqlatte-auth-modal-content,
.sqlatte-modal-content {
    background: #1a1a1a;
    border-radius: 12px;
    border: 1px solid #333;
    width: 90%;
    max-width: 500px;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
}

.sqlatte-modal-content {
    max-width: 650px;
}

.sqlatte-auth-header,
.sqlatte-modal-header {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    padding: 16px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px 12px 0 0;
}

.sqlatte-auth-header h2 {
    margin: 0;
    color: white;
    font-size: 18px;
}

.sqlatte-modal-title {
    display: flex;
    align-items: center;
    gap: 10px;
    color: white;
    font-weight: 600;
    font-size: 16px;
}

.sqlatte-auth-user-badge {
    background: rgba(255, 255, 255, 0.2);
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    margin-left: 10px;
}

.sqlatte-auth-close,
.sqlatte-modal-btn {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.1);
    border: none;
    color: white;
    font-size: 16px;
    cursor: pointer;
    transition: all 0.2s;
}

.sqlatte-auth-close:hover,
.sqlatte-modal-btn:hover {
    background: rgba(255, 255, 255, 0.2);
}

.sqlatte-modal-actions {
    display: flex;
    gap: 8px;
}

.sqlatte-auth-body,
.sqlatte-modal-body {
    padding: 20px;
    overflow-y: auto;
    flex: 1;
}

.sqlatte-auth-form {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.sqlatte-form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.sqlatte-form-group label {
    font-size: 13px;
    font-weight: 600;
    color: #D4A574;
}

.sqlatte-form-group input,
.sqlatte-form-group select {
    padding: 10px 12px;
    background: #0f0f0f;
    border: 1px solid #333;
    border-radius: 6px;
    color: #e0e0e0;
    font-size: 13px;
}

.sqlatte-form-group input:focus,
.sqlatte-form-group select:focus {
    outline: none;
    border-color: #D4A574;
}

.sqlatte-auth-login-btn {
    padding: 12px 20px;
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    margin-top: 10px;
}

.sqlatte-auth-login-btn:hover {
    transform: translateY(-2px);
}

.sqlatte-auth-login-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.sqlatte-auth-error {
    padding: 10px;
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid #ef4444;
    border-radius: 6px;
    color: #ef4444;
    font-size: 13px;
}

/* Toolbar */
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
}

.sqlatte-modal-toolbar small {
    font-size: 10px;
    color: #707070;
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
    min-height: 300px;
}

.sqlatte-empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    color: #a0a0a0;
    text-align: center;
}

.sqlatte-message {
    display: flex;
    gap: 10px;
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
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
}

.sqlatte-message.sqlatte-message-user .sqlatte-message-avatar {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.sqlatte-message-content {
    max-width: 85%;
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
    resize: none;
}

.sqlatte-input-area textarea:focus {
    outline: none;
    border-color: #D4A574;
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
}

.sqlatte-input-area button:disabled {
    opacity: 0.5;
}

/* Results Table */
.sqlatte-results-table {
    width: 100%;
    border-collapse: collapse;
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 6px;
    overflow: hidden;
    font-size: 12px;
    margin: 12px 0;
}

.sqlatte-results-table th {
    padding: 10px;
    text-align: left;
    font-weight: 600;
    color: #D4A574;
    background: #242424;
    border-bottom: 2px solid #333;
}

.sqlatte-results-table td {
    padding: 8px 10px;
    border-bottom: 1px solid #333;
    color: #e0e0e0;
}

.sqlatte-sql-code {
    background: #000;
    padding: 12px;
    border-radius: 6px;
    margin: 12px 0;
    overflow-x: auto;
}

.sqlatte-sql-code pre {
    margin: 0;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    color: #e0e0e0;
}

.sqlatte-explanation {
    color: #a0a0a0;
    font-size: 12px;
    margin: 8px 0;
    padding: 10px;
    background: rgba(212, 165, 116, 0.1);
    border-left: 3px solid #D4A574;
    border-radius: 4px;
}

.sqlatte-error {
    color: #f87171;
    font-size: 12px;
    padding: 10px;
    background: rgba(248, 113, 113, 0.1);
    border-left: 3px solid #f87171;
    border-radius: 4px;
}

/* Toast */
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
    opacity: 0;
    transform: translateX(100px);
    transition: all 0.3s;
    z-index: 999999999;
}

.sqlatte-toast.sqlatte-toast-show {
    opacity: 1;
    transform: translateX(0);
}

.sqlatte-toast.sqlatte-toast-success {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.sqlatte-toast.sqlatte-toast-info {
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
}

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
    to { transform: rotate(360deg); }
}
        `;

        document.head.appendChild(style);
    }

    function init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', createWidget);
        } else {
            createWidget();
        }
    }

    init();

    // Expose public API
    window.SQLatteAuthWidget = {
        updateDBFields: updateDBFields,
        handleLogin: handleLogin,
        logout: logout,
        closeLoginModal: closeLoginModal,
        closeChatModal: closeChatModal,
        sendMessage: sendMessage,
        handleTableChange: handleTableChange,
        configure: function(options) {
            Object.assign(AUTH_WIDGET_CONFIG, options);
        },
        getConfig: function() {
            return { ...AUTH_WIDGET_CONFIG };
        }
    };

})();
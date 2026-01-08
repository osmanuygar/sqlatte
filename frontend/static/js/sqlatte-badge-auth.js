(function() {
    'use strict';

    // ============================================
    // CONFIGURATION
    // ============================================
    const AUTH_WIDGET_CONFIG = {
        apiBase: (function() {
            if (window.location.protocol === 'file:') return 'http://localhost:8000';
            if (window.location.hostname === 'localhost' ||
                window.location.hostname === '127.0.0.1') {
                return 'http://localhost:8000';
            }
            return window.location.protocol + '//' + window.location.hostname + ':8000';
        })(),
        position: 'bottom-left',
        fullscreen: false,
        sessionStorageKey: 'sqlatte_auth_session',
        sessionTTL: 28800000, // 8 hours in ms
    };

    // ============================================
    // STATE MANAGEMENT
    // ============================================
    let isAuthenticated = false;
    let isModalOpen = false;
    let sessionId = null;
    let userInfo = null;
    let selectedTables = [];
    let currentSchema = '';
    let queryHistory = [];
    let favorites = [];
    let isHistoryPanelOpen = false;
    let isFavoritesPanelOpen = false;
    let configData = null; // Server config (allowed DBs, catalogs, schemas)

    // Results cache
    window.sqlatteAuthResultsCache = {};

    // ============================================
    // CONFIG LOADING
    // ============================================
    async function loadServerConfig() {
        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/config`);
            if (response.ok) {
                configData = await response.json();
                console.log('✅ Server config loaded:', configData);
                return true;
            }
        } catch (error) {
            console.error('❌ Failed to load server config:', error);
        }
        return false;
    }

    // ============================================
    // SESSION MANAGEMENT
    // ============================================
    function saveSession(data) {
        const session = {
            sessionId: data.session_id,
            userInfo: data.user_info,
            timestamp: Date.now()
        };
        localStorage.setItem(AUTH_WIDGET_CONFIG.sessionStorageKey, JSON.stringify(session));
        sessionId = data.session_id;
        userInfo = data.user_info;
        isAuthenticated = true;
    }

    function loadSession() {
        const stored = localStorage.getItem(AUTH_WIDGET_CONFIG.sessionStorageKey);
        if (!stored) return false;

        try {
            const session = JSON.parse(stored);
            const age = Date.now() - session.timestamp;

            if (age > AUTH_WIDGET_CONFIG.sessionTTL) {
                clearSession();
                return false;
            }

            sessionId = session.sessionId;
            userInfo = session.userInfo;
            isAuthenticated = true;
            return true;
        } catch (error) {
            clearSession();
            return false;
        }
    }

    function clearSession() {
        localStorage.removeItem(AUTH_WIDGET_CONFIG.sessionStorageKey);
        sessionId = null;
        userInfo = null;
        isAuthenticated = false;
        selectedTables = [];
        currentSchema = '';
    }

    async function validateSession() {
        if (!sessionId) return false;

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/validate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Session-ID': sessionId
                }
            });
            return response.ok;
        } catch (error) {
            console.error('Session validation error:', error);
            return false;
        }
    }

    // ============================================
    // SQL SYNTAX HIGHLIGHTING
    // ============================================
    function highlightSQL(sql) {
        if (!sql) return '';

        let highlighted = sql
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // SQL Keywords
        const keywords = [
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER',
            'ON', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN', 'IS', 'NULL',
            'ORDER BY', 'GROUP BY', 'HAVING', 'LIMIT', 'OFFSET',
            'AS', 'DISTINCT', 'WITH', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END'
        ];

        const functions = [
            'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'ROUND', 'CONCAT',
            'DATE', 'NOW', 'YEAR', 'MONTH', 'DAY', 'UPPER', 'LOWER'
        ];

        // Highlight comments
        highlighted = highlighted.replace(/(--.*)$/gm, '<span class="sql-comment">$1</span>');
        highlighted = highlighted.replace(/(\/\*[\s\S]*?\*\/)/g, '<span class="sql-comment">$1</span>');

        // Highlight strings
        highlighted = highlighted.replace(/('(?:[^']|'')*')/g, '<span class="sql-string">$1</span>');

        // Highlight numbers
        highlighted = highlighted.replace(/\b(\d+\.?\d*)\b/g, '<span class="sql-number">$1</span>');

        // Highlight functions
        functions.forEach(func => {
            const regex = new RegExp(`\\b(${func})\\b`, 'gi');
            highlighted = highlighted.replace(regex, '<span class="sql-function">$1</span>');
        });

        // Highlight keywords
        keywords.forEach(keyword => {
            const regex = new RegExp(`\\b(${keyword.replace(' ', '\\s+')})\\b`, 'gi');
            highlighted = highlighted.replace(regex, '<span class="sql-keyword">$1</span>');
        });

        return highlighted;
    }

    // ============================================
    // CHART GENERATION
    // ============================================
    function generateChart(columns, data, chartType = 'auto') {
        if (!data || data.length === 0) return null;

        // Auto-detect chart type
        if (chartType === 'auto') {
            const hasNumericColumn = columns.some(col =>
                data.every(row => !isNaN(parseFloat(row[col])))
            );
            const hasDateColumn = columns.some(col =>
                data.some(row => !isNaN(Date.parse(row[col])))
            );

            if (hasDateColumn && hasNumericColumn) {
                chartType = 'line';
            } else if (data.length <= 20 && hasNumericColumn) {
                chartType = 'bar';
            } else {
                return null;
            }
        }

        const chartId = 'chart-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);

        setTimeout(() => {
            const canvas = document.getElementById(chartId);
            if (!canvas) return;

            const ctx = canvas.getContext('2d');
            const labelCol = columns[0];
            const valueCol = columns.find(col =>
                data.every(row => !isNaN(parseFloat(row[col])))
            ) || columns[1];

            new Chart(ctx, {
                type: chartType === 'line' ? 'line' : 'bar',
                data: {
                    labels: data.map(row => row[labelCol]),
                    datasets: [{
                        label: valueCol,
                        data: data.map(row => parseFloat(row[valueCol]) || 0),
                        backgroundColor: chartType === 'bar' ?
                            'rgba(212, 165, 116, 0.6)' : 'rgba(212, 165, 116, 0.2)',
                        borderColor: '#D4A574',
                        borderWidth: 2,
                        fill: chartType === 'line'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });
        }, 100);

        return `
            <div class="sqlatte-chart-container">
                <canvas id="${chartId}"></canvas>
            </div>
        `;
    }

    // ============================================
    // LOGIN FORM CREATION
    // ============================================
    function createLoginModal() {
        const modal = document.createElement('div');
        modal.id = 'sqlatte-auth-login-modal';
        modal.className = 'sqlatte-auth-modal';

        modal.innerHTML = `
            <div class="sqlatte-auth-modal-content">
                <div class="sqlatte-auth-header">
                    <h2>🔐 SQLatte Login</h2>
                    <button class="sqlatte-auth-close" onclick="SQLatteAuthWidget.closeLoginModal()">✕</button>
                </div>

                <div class="sqlatte-auth-body" id="sqlatte-auth-login-body">
                    <div class="sqlatte-auth-loading">Loading configuration...</div>
                </div>
            </div>
        `;

        // Load config and render form
        setTimeout(async () => {
            await loadServerConfig();
            renderLoginForm();
        }, 100);

        return modal;
    }

    function renderLoginForm() {
        const body = document.getElementById('sqlatte-auth-login-body');
        if (!body) return;

        if (!configData) {
            body.innerHTML = '<div class="sqlatte-error">❌ Failed to load configuration</div>';
            return;
        }

        const allowedDBs = configData.allowed_db_types || ['trino'];
        const catalogs = configData.allowed_catalogs || [];
        const schemas = configData.allowed_schemas || [];

        body.innerHTML = `
            <form id="sqlatte-auth-login-form" onsubmit="event.preventDefault(); SQLatteAuthWidget.handleLogin();">

                <!-- Username -->
                <div class="sqlatte-form-group">
                    <label>Username</label>
                    <input type="text" id="sqlatte-username" required
                           placeholder="Enter your username" autocomplete="username" />
                </div>

                <!-- Password -->
                <div class="sqlatte-form-group">
                    <label>Password</label>
                    <input type="password" id="sqlatte-password" required
                           placeholder="Enter your password" autocomplete="current-password" />
                </div>

                <!-- Catalog (only if configured) -->
                ${catalogs.length > 0 ? `
                <div class="sqlatte-form-group">
                    <label>Catalog</label>
                    <select id="sqlatte-catalog" required>
                        <option value="">Select catalog...</option>
                        ${catalogs.map(cat => `<option value="${cat}">${cat}</option>`).join('')}
                    </select>
                </div>
                ` : ''}

                <!-- Schema (only if configured) -->
                ${schemas.length > 0 ? `
                <div class="sqlatte-form-group">
                    <label>Schema</label>
                    <select id="sqlatte-schema" required>
                        <option value="">Select schema...</option>
                        ${schemas.map(sch => `<option value="${sch}">${sch}</option>`).join('')}
                    </select>
                </div>
                ` : ''}

                <div class="sqlatte-form-actions">
                    <button type="submit" class="sqlatte-btn sqlatte-btn-primary">
                        Login
                    </button>
                </div>

                <div id="sqlatte-auth-error" class="sqlatte-error" style="display: none;"></div>
            </form>

            <div class="sqlatte-auth-info">
                <strong>📊 Database:</strong> ${configData.db_provider || 'Trino'}<br>
                ${catalogs.length > 0 ? `<strong>📚 Available Catalogs:</strong> ${catalogs.join(', ')}<br>` : ''}
                ${schemas.length > 0 ? `<strong>📁 Available Schemas:</strong> ${schemas.join(', ')}` : ''}
            </div>
        `;
    }

    // ============================================
    // AUTHENTICATION HANDLERS
    // ============================================
    async function handleLogin() {
        const username = document.getElementById('sqlatte-username')?.value;
        const password = document.getElementById('sqlatte-password')?.value;
        const catalog = document.getElementById('sqlatte-catalog')?.value || null;
        const schema = document.getElementById('sqlatte-schema')?.value || 'default';
        const errorDiv = document.getElementById('sqlatte-auth-error');

        if (!username || !password) {
            showError(errorDiv, 'Please fill in all required fields');
            return;
        }

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username,
                    password,
                    database_type: configData.db_provider || 'trino',
                    host: configData.db_host || 'localhost',
                    port: configData.db_port || 8080,
                    catalog,
                    schema,
                    http_scheme: 'https'
                })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                saveSession(data);
                closeLoginModal();
                openChatModal();
                await loadTablesAuth();
                showToast('✅ Login successful!', 'success');
            } else {
                showError(errorDiv, data.message || 'Login failed');
            }
        } catch (error) {
            console.error('Login error:', error);
            showError(errorDiv, 'Connection error. Please try again.');
        }
    }

    async function logout() {
        try {
            if (sessionId) {
                await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/logout`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId
                    }
                });
            }
        } catch (error) {
            console.error('Logout error:', error);
        }

        clearSession();
        closeChatModal();
        showToast('👋 Logged out', 'info');
    }

    // ============================================
    // CHAT MODAL CREATION
    // ============================================
    function createChatModal() {
        const modal = document.createElement('div');
        modal.id = 'sqlatte-auth-chat-modal';
        modal.className = 'sqlatte-auth-modal';

        modal.innerHTML = `
            <div class="sqlatte-modal-content ${AUTH_WIDGET_CONFIG.fullscreen ? 'sqlatte-modal-fullscreen' : ''}">
                <!-- Header -->
                <div class="sqlatte-auth-header">
                    <div class="sqlatte-modal-title">
                        <span>☕ SQLatte Assistant</span>
                        <span id="sqlatte-auth-user-badge" class="sqlatte-auth-user-badge"></span>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="sqlatte-modal-btn" onclick="SQLatteAuthWidget.logout()" title="Logout">
                            🚪
                        </button>
                        <button class="sqlatte-auth-close" onclick="SQLatteAuthWidget.closeChatModal()">✕</button>
                    </div>
                </div>

                <!-- Table Selection -->
                <div class="sqlatte-table-select-container">
                    <select id="sqlatte-auth-table-select" multiple
                            onchange="SQLatteAuthWidget.handleTableChange()"
                            class="sqlatte-table-select">
                        <option disabled>Loading tables...</option>
                    </select>
                </div>

                <!-- History & Favorites Buttons -->
                <div class="sqlatte-history-buttons">
                    <button class="sqlatte-history-btn" onclick="SQLatteAuthWidget.toggleHistory()">
                        📜 History
                    </button>
                    <button class="sqlatte-favorites-btn" onclick="SQLatteAuthWidget.toggleFavorites()">
                        ⭐ Favorites
                    </button>
                </div>

                <!-- History Panel -->
                <div id="sqlatte-auth-history-panel" class="sqlatte-panel" style="display: none;"></div>

                <!-- Favorites Panel -->
                <div id="sqlatte-auth-favorites-panel" class="sqlatte-panel" style="display: none;"></div>

                <!-- Chat Area -->
                <div id="sqlatte-auth-chat-area" class="sqlatte-chat-area">
                    <div class="sqlatte-empty-state">
                        <div class="sqlatte-empty-icon">☕</div>
                        <div class="sqlatte-empty-title">Welcome to SQLatte!</div>
                        <div class="sqlatte-empty-text">
                            Ask me anything about your database. I can help you write queries, analyze data, and more.
                        </div>
                    </div>
                </div>

                <!-- Input Area -->
                <div class="sqlatte-input-container">
                    <textarea id="sqlatte-auth-input"
                              placeholder="Ask a question... (e.g., 'Show me customers')"
                              rows="2"></textarea>
                    <button id="sqlatte-auth-send-btn" onclick="SQLatteAuthWidget.sendMessage()">
                        Send →
                    </button>
                </div>
            </div>
        `;

        // Enter key handler
        setTimeout(() => {
            const input = document.getElementById('sqlatte-auth-input');
            if (input) {
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                    }
                });
            }
        }, 100);

        return modal;
    }

    // ============================================
    // TABLE MANAGEMENT
    // ============================================
    async function loadTablesAuth() {
        if (!sessionId) return;

        const select = document.getElementById('sqlatte-auth-table-select');
        if (!select) return;

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/tables`, {
                headers: { 'X-Session-ID': sessionId }
            });

            if (!response.ok) throw new Error('Failed to load tables');

            const data = await response.json();
            const tables = data.tables || [];

            select.innerHTML = tables.length > 0
                ? tables.map(t => `<option value="${t}">${t}</option>`).join('')
                : '<option disabled>No tables available</option>';

        } catch (error) {
            console.error('Error loading tables:', error);
            select.innerHTML = '<option disabled>Error loading tables</option>';
        }
    }

    async function handleTableChange() {
        const select = document.getElementById('sqlatte-auth-table-select');
        if (!select || !sessionId) return;

        selectedTables = Array.from(select.selectedOptions).map(opt => opt.value);

        if (selectedTables.length === 0) {
            currentSchema = '';
            return;
        }

        try {
            const endpoint = selectedTables.length === 1
                ? `/auth/schema/${selectedTables[0]}`
                : '/auth/schema/multiple';

            const options = {
                headers: {
                    'X-Session-ID': sessionId,
                    'Content-Type': 'application/json'
                }
            };

            if (selectedTables.length > 1) {
                options.method = 'POST';
                options.body = JSON.stringify({ tables: selectedTables });
            }

            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}${endpoint}`, options);
            const data = await response.json();

            currentSchema = selectedTables.length === 1
                ? data.schema
                : data.combined_schema;

        } catch (error) {
            console.error('Error loading schema:', error);
        }
    }

    // ============================================
    // MESSAGE HANDLING
    // ============================================
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

    async function sendMessage() {
        if (!sessionId) {
            showToast('❌ Please login first', 'error');
            return;
        }

        const input = document.getElementById('sqlatte-auth-input');
        const sendBtn = document.getElementById('sqlatte-auth-send-btn');

        if (!input || !input.value.trim()) return;

        const question = input.value.trim();
        input.value = '';
        input.disabled = true;
        sendBtn.disabled = true;

        addMessage('user', escapeHtml(question));
        addMessage('assistant', '<div class="sqlatte-loading"></div>');

        try {
            const response = await fetch(`${AUTH_WIDGET_CONFIG.apiBase}/auth/query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Session-ID': sessionId
                },
                body: JSON.stringify({
                    question,
                    tables: selectedTables,
                    schema: currentSchema
                })
            });

            const data = await response.json();

            // Remove loading message
            const chatArea = document.getElementById('sqlatte-auth-chat-area');
            const messages = chatArea.querySelectorAll('.sqlatte-message-assistant');
            const lastMsg = messages[messages.length - 1];
            if (lastMsg) lastMsg.remove();

            // Handle chat responses (no SQL/results)
            if (data.response_type === 'chat' || data.intent_info?.intent === 'chat') {
                const chatMessage = data.message || data.explanation || 'I can help you with database queries!';

                // Add assistant message
                addMessage('assistant', chatMessage);

                console.log('✅ Chat response displayed:', data.response_type);
                input.disabled = false;
                sendBtn.disabled = false;
                return; // Don't try to render SQL/results
            }


            if (data.error) {
                addMessage('assistant', `<div class="sqlatte-error">❌ ${escapeHtml(data.error)}</div>`);
            } else {
                const formatted = formatTable(
                    data.columns,
                    data.data,
                    data.query_id,
                    data.sql,
                    data.explanation
                );
                addMessage('assistant', formatted);

                // Add to history
                saveToHistory(question, data);
            }

        } catch (error) {
            console.error('Query error:', error);
            const chatArea = document.getElementById('sqlatte-auth-chat-area');
            const messages = chatArea.querySelectorAll('.sqlatte-message-assistant');
            const lastMsg = messages[messages.length - 1];
            if (lastMsg) lastMsg.remove();
            addMessage('assistant', '<div class="sqlatte-error">❌ Connection error</div>');
        } finally {
            input.disabled = false;
            sendBtn.disabled = false;
            input.focus();
        }
    }

    // ============================================
    // TABLE FORMATTING
    // ============================================


    function handleChartClick(resultId) {
        const cached = window.sqlatteAuthResultsCache[resultId];
        if (!cached) {
            console.error('❌ No cached data for resultId:', resultId);
            alert('Chart data not found. Please run the query again.');
            return;
        }

        const { columns, data } = cached;

        if (!columns || !data || !Array.isArray(data) || data.length === 0) {
            console.error('❌ Invalid cached data:', { columns, data });
            alert('Invalid data for charting. Please run the query again.');
            return;
        }

        console.log('✅ Opening chart config with:', {
            columns: columns.length,
            rows: data.length,
            firstRow: data[0]
        });

        showChartConfigModal(columns, data, resultId);
    }

    function showChartConfigModal(columns, data, resultId) {
        // Detect column types
        const dimensionCols = [];
        const metricCols = [];

        columns.forEach(col => {
            const hasNumeric = data.some(row => typeof row[col] === 'number');
            const hasDate = data.some(row => {
                const val = row[col];
                return typeof val === 'string' && !isNaN(Date.parse(val));
            });

            if (hasNumeric) {
                metricCols.push(col);
            }
            if (!hasNumeric || hasDate) {
                dimensionCols.push(col);
            }
        });

        if (metricCols.length === 0) {
            alert('No numeric columns found for charting');
            return;
        }

        const modal = document.createElement('div');
        modal.className = 'sqlatte-chart-config-modal';
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999999;
        `;

        const content = document.createElement('div');
        content.style.cssText = `
            background: #1a1a1a;
            padding: 24px;
            border-radius: 12px;
            max-width: 500px;
            width: 90%;
            color: #e0e0e0;
        `;

        content.innerHTML = `
            <h3 style="margin: 0 0 20px 0; color: #D4A574;">📊 Chart Configuration</h3>

            <div style="margin-bottom: 20px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 500;">
                    Dimension (X-axis):
                </label>
                <select id="chart-dimension" style="width: 100%; padding: 8px; background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; border-radius: 6px;">
                    <option value="">-- Select dimension --</option>
                    ${dimensionCols.map(col => `<option value="${col}">${col}</option>`).join('')}
                </select>
            </div>

            <div style="margin-bottom: 20px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 500;">
                    Metrics (Y-axis):
                </label>
                <div id="chart-metrics" style="background: #2a2a2a; border: 1px solid #444; border-radius: 6px; padding: 12px; max-height: 200px; overflow-y: auto;">
                    ${metricCols.map(col => `
                        <label style="display: block; padding: 6px 0; cursor: pointer;">
                            <input type="checkbox" value="${col}" style="margin-right: 8px;" />
                            ${col}
                        </label>
                    `).join('')}
                </div>
                <small style="color: #999; display: block; margin-top: 4px;">
                    Select one or more metrics
                </small>
            </div>

            <div style="margin-bottom: 20px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 500;">
                    Chart Type:
                </label>
                <select id="chart-type" style="width: 100%; padding: 8px; background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; border-radius: 6px;">
                    <option value="bar">Bar Chart</option>
                    <option value="line">Line Chart</option>
                    <option value="pie">Pie Chart</option>
                </select>
            </div>

            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                <button id="chart-cancel" style="padding: 10px 20px; background: #333; color: #e0e0e0; border: none; border-radius: 6px; cursor: pointer;">
                    Cancel
                </button>
                <button id="chart-generate" style="padding: 10px 20px; background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%); color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 500;">
                    Generate Chart
                </button>
            </div>
        `;

        modal.appendChild(content);
        document.body.appendChild(modal);

        document.getElementById('chart-cancel').onclick = () => modal.remove();

        document.getElementById('chart-generate').onclick = () => {
            const dimension = document.getElementById('chart-dimension').value;
            const metricCheckboxes = document.querySelectorAll('#chart-metrics input[type="checkbox"]:checked');
            const selectedMetrics = Array.from(metricCheckboxes).map(cb => cb.value);
            const chartType = document.getElementById('chart-type').value;

            if (!dimension) {
                alert('Please select a dimension');
                return;
            }

            if (selectedMetrics.length === 0) {
                alert('Please select at least one metric');
                return;
            }

            modal.remove();
            generateChart(columns, data, resultId, dimension, selectedMetrics, chartType);
        };
    }

    function generateChart(columns, data, resultId, dimension, metrics, chartType) {

    // =====================
    // VALIDATIONS
    // =====================
    if (!data || !Array.isArray(data) || data.length === 0) {
        console.error('❌ Invalid data for chart:', data);
        alert('No data available for charting');
        return;
    }

    if (!columns || !Array.isArray(columns) || columns.length === 0) {
        console.error('❌ Invalid columns for chart:', columns);
        alert('No columns available for charting');
        return;
    }

    if (!dimension || !metrics || metrics.length === 0) {
        console.error('❌ Invalid dimension/metrics:', { dimension, metrics });
        alert('Please select dimension and metrics');
        return;
    }

    // =====================
    // LOAD CHART.JS IF NEEDED
    // =====================
    if (typeof Chart === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
        script.onload = () =>
            generateChart(columns, data, resultId, dimension, metrics, chartType);
        document.head.appendChild(script);
        return;
    }

    // =====================
    // RANDOM COLOR GENERATOR
    // =====================
    function randomColor(alpha = 0.85) {
        const r = Math.floor(Math.random() * 156) + 50;
        const g = Math.floor(Math.random() * 156) + 50;
        const b = Math.floor(Math.random() * 156) + 50;
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    // =====================
    // LABELS
    // =====================
    const labels = data.map(row => {
        const val = row[dimension];
        return val !== null && val !== undefined ? String(val) : 'N/A';
    });

    // =====================
    // DATASETS
    // =====================
    let datasets;

    if (chartType === 'pie') {
        const metric = metrics[0]; // pie için tek metric
        datasets = [{
            label: metric,
            data: data.map(row => Number(row[metric]) || 0),
            backgroundColor: labels.map(() => randomColor(0.9)),
            borderColor: '#1a1a1a',
            borderWidth: 2
        }];
    } else {
        datasets = metrics.map(metric => {
            const color = randomColor();
            return {
                label: metric,
                data: data.map(row => Number(row[metric]) || 0),
                backgroundColor: chartType === 'line' ? color : color,
                borderColor: color,
                borderWidth: 2,
                fill: chartType !== 'line',
                tension: chartType === 'line' ? 0.4 : 0
            };
        });
    }

    // =====================
    // MODAL UI
    // =====================
    const chartModal = document.createElement('div');
    chartModal.style.cssText = `
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.95);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 999999;
        padding: 20px;
    `;

    const chartContainer = document.createElement('div');
    chartContainer.style.cssText = `
        background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
        padding: 24px;
        border-radius: 12px;
        max-width: 1200px;
        width: 100%;
        max-height: 90vh;
        overflow-y: auto;
    `;

    chartContainer.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
            <h3 style="margin:0;color:#e5e5e5;">
                📊 ${dimension} vs ${metrics.join(', ')}
            </h3>
            <button id="close-chart"
                style="background:#333;color:white;border:none;padding:8px 16px;
                border-radius:6px;cursor:pointer;">
                Close
            </button>
        </div>
        <div style="position:relative;height:500px;">
            <canvas id="chart-canvas-${resultId}"></canvas>
        </div>
    `;

    chartModal.appendChild(chartContainer);
    document.body.appendChild(chartModal);

    // =====================
    // CHART INIT
    // =====================
    const ctx = document
        .getElementById(`chart-canvas-${resultId}`)
        .getContext('2d');

    new Chart(ctx, {
        type: chartType === 'pie'
            ? 'pie'
            : chartType === 'line'
                ? 'line'
                : 'bar',
        data: {
            labels,
            datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#e0e0e0' }
                },
                tooltip: chartType === 'pie' ? {
                    callbacks: {
                        label: ctx => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const value = ctx.raw;
                            const pct = total ? ((value / total) * 100).toFixed(1) : 0;
                            return `${ctx.label}: ${value} (${pct}%)`;
                        }
                    }
                } : {}
            },
            scales: chartType !== 'pie' ? {
                x: {
                    ticks: { color: '#e0e0e0' },
                    grid: { color: '#333' }
                },
                y: {
                    beginAtZero: true,
                    ticks: { color: '#e0e0e0' },
                    grid: { color: '#333' }
                }
            } : {}
        }
    });

    // =====================
    // CLOSE HANDLERS
    // =====================
    document.getElementById('close-chart').onclick = () => chartModal.remove();
    chartModal.onclick = e => {
        if (e.target === chartModal) chartModal.remove();
    };
}


    function normalizeRows(columns, data) {
        if (!Array.isArray(data) || data.length === 0) return [];
        // Zaten object ise hiç dokunma
        if (typeof data[0] === 'object' && !Array.isArray(data[0])) {
            return data;
        }
        // Array-of-array → object[]
        return data.map(row => {
            const obj = {};
            columns.forEach((col, i) => {
                obj[col] = row[i];
            });
            return obj;
        });
    }

    function formatTable(columns, data, queryId = null, sql = null, explanation = null) {
        if (!data || data.length === 0) {
            return '<div style="opacity: 0.7; margin-top: 8px;">No results returned.</div>';
        }

        const resultId = 'result-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
        const normalizedData = normalizeRows(columns, data);
        window.sqlatteAuthResultsCache[resultId] = { columns, data: normalizedData };

        let html = '';

        // Explanation
        if (explanation) {
            html += `<div class="sqlatte-explanation"><strong>💡</strong> ${escapeHtml(explanation)}</div>`;
        }

        // SQL Code with Highlighting
        if (sql) {
            const sqlId = 'sql-' + resultId;
            html += `
                <div class="sqlatte-sql-container">
                    <div class="sqlatte-sql-toolbar" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding: 8px 12px; background: rgba(255,255,255,0.05); border-radius: 6px;">
                    <div class="sqlatte-sql-label" style="font-size: 12px; font-weight: 600; color: #888; text-transform: uppercase; letter-spacing: 0.5px;">Generated SQL</div>
                </div>
                    </div>
                    <div class="sqlatte-sql-code">
                        <pre><code id="${sqlId}" data-raw-sql="${escapeHtml(sql)}">${highlightSQL(sql)}</code></pre>
                    </div>
                </div>
            `;
        }

        // Data Table
        html += `
            <div class="sqlatte-table-actions">
                <button onclick="SQLatteAuthWidget.exportToCSV('${resultId}')">📥 CSV</button>
                <button onclick="SQLatteAuthWidget.handleChartClick('${resultId}')">📊 Chart</button>
                ${queryId ? `<button onclick="SQLatteAuthWidget.addToFavorites('${queryId}')">⭐ Save</button>` : ''}
            </div>
            <div class="sqlatte-table-wrapper">
                <table class="sqlatte-table">
                    <thead>
                        <tr>${columns.map(col => `<th>${escapeHtml(col)}</th>`).join('')}</tr>
                    </thead>
                    <tbody>
                        ${normalizedData.slice(0, 100).map(row => `
                            <tr>${columns.map(col => `<td>${escapeHtml(String(row[col] ?? ''))}</td>`).join('')}</tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        if (data.length > 100) {
            html += `<div class="sqlatte-table-footer">Showing first 100 of ${data.length} rows</div>`;
        }

        return html;
    }

    // ============================================
    // HISTORY & FAVORITES
    // ============================================
    function saveToHistory(question, result) {
        queryHistory.unshift({
            id: Date.now(),
            question,
            sql: result.sql,
            timestamp: new Date().toISOString()
        });

        if (queryHistory.length > 50) queryHistory.pop();
        localStorage.setItem('sqlatte_auth_history', JSON.stringify(queryHistory));
    }

    function loadHistory() {
        const stored = localStorage.getItem('sqlatte_auth_history');
        if (stored) {
            try {
                queryHistory = JSON.parse(stored);
            } catch (e) {
                queryHistory = [];
            }
        }
    }

    function toggleHistory() {
        isHistoryPanelOpen = !isHistoryPanelOpen;
        const panel = document.getElementById('sqlatte-auth-history-panel');

        if (isHistoryPanelOpen) {
            renderHistoryPanel();
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    }

    function renderHistoryPanel() {
        const panel = document.getElementById('sqlatte-auth-history-panel');
        if (!panel) return;

        if (queryHistory.length === 0) {
            panel.innerHTML = '<div class="sqlatte-empty-panel">No history yet</div>';
            return;
        }

        panel.innerHTML = `
            <div class="sqlatte-panel-header">
                <h3>📜 Query History</h3>
                <button onclick="SQLatteAuthWidget.clearHistory()">Clear</button>
            </div>
            <div class="sqlatte-panel-list">
                ${queryHistory.map(item => `
                    <div class="sqlatte-history-item" onclick="SQLatteAuthWidget.rerunQuery('${escapeHtml(item.sql)}')">
                        <div class="sqlatte-history-question">${escapeHtml(item.question)}</div>
                        <div class="sqlatte-history-time">${new Date(item.timestamp).toLocaleString()}</div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    function clearHistory() {
        queryHistory = [];
        localStorage.removeItem('sqlatte_auth_history');
        renderHistoryPanel();
    }

    function toggleFavorites() {
        isFavoritesPanelOpen = !isFavoritesPanelOpen;
        const panel = document.getElementById('sqlatte-auth-favorites-panel');

        if (isFavoritesPanelOpen) {
            renderFavoritesPanel();
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    }

    function renderFavoritesPanel() {
        const panel = document.getElementById('sqlatte-auth-favorites-panel');
        if (!panel) return;

        if (favorites.length === 0) {
            panel.innerHTML = '<div class="sqlatte-empty-panel">No favorites yet</div>';
            return;
        }

        panel.innerHTML = `
            <div class="sqlatte-panel-header">
                <h3>⭐ Favorites</h3>
            </div>
            <div class="sqlatte-panel-list">
                ${favorites.map(item => `
                    <div class="sqlatte-history-item" onclick="SQLatteAuthWidget.rerunQuery('${escapeHtml(item.sql)}')">
                        <div class="sqlatte-history-question">${escapeHtml(item.name)}</div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    // ============================================
    // UTILITY FUNCTIONS
    // ============================================
    function copySQLAction(sqlId) {
        const sqlElement = document.getElementById(sqlId);
        if (!sqlElement) return;

        const rawSQL = sqlElement.getAttribute('data-raw-sql');
        if (rawSQL) {
            copyToClipboard(decodeHTMLEntities(rawSQL));
        }
    }

    function copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                showToast('📋 Copied to clipboard!', 'success');
            });
        }
    }

    function exportToCSV(resultId) {
        const cached = window.sqlatteAuthResultsCache[resultId];
        if (!cached) return;

        const { columns, data } = cached;
        let csv = columns.join(',') + '\n';

        data.forEach(row => {
            csv += columns.map(col => {
                const val = row[col] ?? '';
                return `"${String(val).replace(/"/g, '""')}"`;
            }).join(',') + '\n';
        });

        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'sqlatte_export.csv';
        a.click();
        URL.revokeObjectURL(url);

        showToast('📥 CSV downloaded!', 'success');
    }

    /* OLD visualizeData - REMOVED
function visualizeData(resultId) {
        const cached = window.sqlatteAuthResultsCache[resultId];
        if (!cached) return;

        const { columns, data } = cached;
        const chartHTML = generateChart(columns, data);

        if (chartHTML) {
            addMessage('assistant', chartHTML);
        } else {
            showToast('📊 Could not generate chart for this data', 'error');
        }
    }

*/
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function decodeHTMLEntities(text) {
        const textarea = document.createElement('textarea');
        textarea.innerHTML = text;
        return textarea.value;
    }

    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `sqlatte-toast sqlatte-toast-${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => toast.classList.add('sqlatte-toast-show'), 10);
        setTimeout(() => {
            toast.classList.remove('sqlatte-toast-show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    function showError(element, message) {
        if (element) {
            element.textContent = message;
            element.style.display = 'block';
            setTimeout(() => element.style.display = 'none', 5000);
        }
    }

    // ============================================
    // MODAL CONTROLS
    // ============================================
    function openLoginModal() {
        const modal = document.getElementById('sqlatte-auth-login-modal');
        if (modal) modal.classList.add('sqlatte-auth-modal-open');
        const badge = document.querySelector('.sqlatte-badge-btn');
        if (badge) badge.style.display = 'none';
    }

    function closeLoginModal() {
        const modal = document.getElementById('sqlatte-auth-login-modal');
        if (modal) modal.classList.remove('sqlatte-auth-modal-open');
        const badge = document.querySelector('.sqlatte-badge-btn');
        if (badge) badge.style.display = 'flex';
    }

    function openChatModal() {
        const modal = document.getElementById('sqlatte-auth-chat-modal');
        if (modal) {
            const userBadge = document.getElementById('sqlatte-auth-user-badge');
            if (userBadge && userInfo) {
                userBadge.textContent = `👤 ${userInfo.username}`;
            }
            modal.classList.add('sqlatte-auth-modal-open');
            isModalOpen = true;
            const badge = document.querySelector('.sqlatte-badge-btn');
            if (badge) badge.style.display = 'none';
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

    // ============================================
    // WIDGET INITIALIZATION
    // ============================================
    function createWidget() {
        if (document.getElementById('sqlatte-auth-widget')) return;

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

        const loginModal = createLoginModal();
        const chatModal = createChatModal();
        document.body.appendChild(loginModal);
        document.body.appendChild(chatModal);

        injectStyles();
        loadHistory();

        setTimeout(() => widget.classList.add('sqlatte-widget-visible'), 500);

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

        // Load Chart.js for visualizations
        if (!window.Chart) {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
            document.head.appendChild(script);
        }
    }

    // ============================================
    // STYLES
    // ============================================
    function injectStyles() {
        if (document.getElementById('sqlatte-auth-widget-styles')) return;

        const style = document.createElement('style');
        style.id = 'sqlatte-auth-widget-styles';
        style.textContent = `
/* SQLatte Auth Widget - Full Featured */

.sqlatte-widget {
    position: fixed;
    z-index: 999999;
    opacity: 0;
    transform: translateY(20px);
    transition: all 0.3s;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.sqlatte-widget.sqlatte-widget-visible { opacity: 1; transform: translateY(0); }
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

.sqlatte-badge-btn:hover { transform: translateY(-4px) scale(1.05); }

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

/* Modals */
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

.sqlatte-auth-modal.sqlatte-auth-modal-open { opacity: 1; pointer-events: all; }

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

.sqlatte-modal-content { max-width: 650px; height: 650px; }
.sqlatte-modal-fullscreen {
    width: 100vw !important;
    height: 100vh !important;
    max-width: 100vw !important;
    max-height: 100vh !important;
    border-radius: 0 !important;
}

/* Headers */
.sqlatte-auth-header {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    padding: 16px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px 12px 0 0;
}

.sqlatte-auth-header h2 { margin: 0; color: white; font-size: 18px; }
.sqlatte-modal-title { display: flex; align-items: center; gap: 10px; color: white; font-weight: 600; }
.sqlatte-auth-user-badge {
    background: rgba(255, 255, 255, 0.2);
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
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
.sqlatte-modal-btn:hover { background: rgba(255, 255, 255, 0.2); }

/* Forms */
.sqlatte-auth-body {
    padding: 24px;
    overflow-y: auto;
    flex: 1;
}

.sqlatte-form-group {
    margin-bottom: 16px;
}

.sqlatte-form-group label {
    display: block;
    margin-bottom: 6px;
    color: #e0e0e0;
    font-size: 13px;
    font-weight: 600;
}

.sqlatte-form-group input,
.sqlatte-form-group select {
    width: 100%;
    padding: 10px 12px;
    background: #000;
    border: 1px solid #333;
    border-radius: 6px;
    color: white;
    font-size: 14px;
    font-family: inherit;
}

.sqlatte-form-group input:focus,
.sqlatte-form-group select:focus {
    outline: none;
    border-color: #D4A574;
}

.sqlatte-form-actions {
    margin-top: 24px;
}

.sqlatte-btn {
    padding: 10px 20px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}

.sqlatte-btn-primary {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    color: white;
    width: 100%;
}

.sqlatte-btn-primary:hover { transform: translateY(-1px); }

.sqlatte-auth-info {
    margin-top: 20px;
    padding: 12px;
    background: rgba(212, 165, 116, 0.1);
    border-left: 3px solid #D4A574;
    border-radius: 4px;
    font-size: 12px;
    color: #a0a0a0;
    line-height: 1.6;
}

.sqlatte-error {
    color: #f87171;
    font-size: 12px;
    padding: 10px;
    background: rgba(248, 113, 113, 0.1);
    border-left: 3px solid #f87171;
    border-radius: 4px;
    margin-top: 12px;
}

/* Table Selection */
.sqlatte-table-select-container {
    padding: 12px 16px;
    background: #0a0a0a;
    border-bottom: 1px solid #333;
}

.sqlatte-table-select {
    width: 100%;
    padding: 8px;
    background: #000;
    border: 1px solid #333;
    border-radius: 6px;
    color: white;
    font-size: 12px;
    max-height: 120px;
}

/* History & Favorites */
.sqlatte-history-buttons {
    padding: 8px 16px;
    background: #0a0a0a;
    border-bottom: 1px solid #333;
    display: flex;
    gap: 8px;
}

.sqlatte-history-btn,
.sqlatte-favorites-btn {
    padding: 6px 12px;
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 6px;
    color: #e0e0e0;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.2s;
}

.sqlatte-history-btn:hover,
.sqlatte-favorites-btn:hover {
    background: #252525;
    border-color: #D4A574;
}

.sqlatte-panel {
    max-height: 200px;
    overflow-y: auto;
    background: #0a0a0a;
    border-bottom: 1px solid #333;
}

.sqlatte-panel-header {
    padding: 12px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #333;
}

.sqlatte-panel-header h3 {
    margin: 0;
    font-size: 13px;
    color: #D4A574;
}

.sqlatte-panel-header button {
    padding: 4px 10px;
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 4px;
    color: #e0e0e0;
    font-size: 11px;
    cursor: pointer;
}

.sqlatte-history-item {
    padding: 10px 16px;
    border-bottom: 1px solid #1a1a1a;
    cursor: pointer;
    transition: background 0.2s;
}

.sqlatte-history-item:hover { background: #1a1a1a; }

.sqlatte-history-question {
    font-size: 12px;
    color: #e0e0e0;
    margin-bottom: 4px;
}

.sqlatte-history-time {
    font-size: 10px;
    color: #666;
}

/* Chat Area */
.sqlatte-chat-area {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    background: #000;
}

.sqlatte-empty-state {
    text-align: center;
    padding: 40px 20px;
    color: #666;
}

.sqlatte-empty-icon { font-size: 48px; margin-bottom: 16px; }
.sqlatte-empty-title { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.sqlatte-empty-text { font-size: 14px; }

.sqlatte-message {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
}

.sqlatte-message-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #1a1a1a;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    font-size: 16px;
}

.sqlatte-message-content {
    flex: 1;
    background: #1a1a1a;
    padding: 12px;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.6;
    color: #e0e0e0;
}

.sqlatte-message-user .sqlatte-message-content {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
}

/* SQL Code Highlighting */
.sqlatte-sql-container {
    background: #000;
    border-radius: 8px;
    margin: 12px 0;
    border: 1px solid #1a1a1a;
    overflow: hidden;
}

.sqlatte-sql-toolbar {
    background: #1a1a1a;
    padding: 10px 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #333;
}

.sqlatte-sql-label {
    font-size: 12px;
    font-weight: 600;
    color: #D4A574;
}

.sqlatte-sql-actions {
    display: flex;
    gap: 8px;
}

.sqlatte-sql-toolbar button {
    padding: 6px 12px;
    background: #333;
    border: 1px solid #444;
    border-radius: 6px;
    color: #e0e0e0;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.2s;
}

.sqlatte-sql-toolbar button:hover {
    background: #3d3d3d;
    border-color: #D4A574;
}

.sqlatte-sql-code {
    max-height: 350px;
    overflow: auto;
    background: #000;
}

.sqlatte-sql-code pre {
    margin: 0;
    padding: 14px 16px;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.7;
    color: #e0e0e0;
}

.sql-keyword { color: #66d9ef; font-weight: bold; }
.sql-function { color: #fd971f; font-weight: 600; }
.sql-string { color: #a6e22e; }
.sql-number { color: #ae81ff; }
.sql-comment { color: #75715e; font-style: italic; opacity: 0.8; }

/* Tables */
.sqlatte-table-actions {
    margin: 12px 0;
    display: flex;
    gap: 8px;
}

.sqlatte-table-actions button {
    padding: 6px 12px;
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 6px;
    color: #e0e0e0;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.2s;
}

.sqlatte-table-actions button:hover {
    background: #252525;
    border-color: #D4A574;
}

.sqlatte-table-wrapper {
    max-height: 400px;
    overflow: auto;
    border-radius: 8px;
    border: 1px solid #333;
}

.sqlatte-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}

.sqlatte-table th {
    position: sticky;
    top: 0;
    background: #1a1a1a;
    color: #D4A574;
    padding: 10px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #333;
}

.sqlatte-table td {
    padding: 8px 10px;
    border-bottom: 1px solid #1a1a1a;
    color: #e0e0e0;
}

.sqlatte-table tr:hover td { background: #1a1a1a; }

/* Charts */
.sqlatte-chart-container {
    margin: 16px 0;
    padding: 20px;
    background: #1a1a1a;
    border-radius: 8px;
    height: 300px;
}

/* Input */
.sqlatte-input-container {
    padding: 16px;
    background: #0a0a0a;
    border-top: 1px solid #333;
    display: flex;
    gap: 12px;
    align-items: flex-end;
}

.sqlatte-input-container textarea {
    flex: 1;
    padding: 10px 12px;
    background: #000;
    border: 1px solid #333;
    border-radius: 8px;
    color: white;
    font-size: 13px;
    font-family: inherit;
    resize: none;
    min-height: 40px;
    max-height: 120px;
}

.sqlatte-input-container textarea:focus {
    outline: none;
    border-color: #D4A574;
}

.sqlatte-input-container button {
    padding: 10px 20px;
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
}

.sqlatte-input-container button:hover { transform: translateY(-1px); }
.sqlatte-input-container button:disabled { opacity: 0.5; cursor: not-allowed; }

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

.sqlatte-toast.sqlatte-toast-show { opacity: 1; transform: translateX(0); }
.sqlatte-toast.sqlatte-toast-success { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
.sqlatte-toast.sqlatte-toast-info { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }
.sqlatte-toast.sqlatte-toast-error { background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); }

/* Loading */
.sqlatte-loading,
.sqlatte-auth-loading {
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

.sqlatte-explanation {
    color: #a0a0a0;
    font-size: 12px;
    margin: 8px 0;
    padding: 10px;
    background: rgba(212, 165, 116, 0.1);
    border-left: 3px solid #D4A574;
    border-radius: 4px;
}

/* FULLSCREEN FIX */
.sqlatte-modal-content.sqlatte-modal-fullscreen {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    max-width: 100vw !important;
    max-height: 100vh !important;
    border-radius: 0 !important;
    margin: 0 !important;
    transform: none !important;
}

.sqlatte-auth-modal.sqlatte-auth-modal-open .sqlatte-modal-content.sqlatte-modal-fullscreen {
    transform: none !important;
}

/* FULLSCREEN FIX - CRITICAL */
.sqlatte-modal-content.sqlatte-modal-fullscreen,
.sqlatte-auth-modal.sqlatte-auth-modal-open .sqlatte-modal-content {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    max-width: 100vw !important;
    max-height: 100vh !important;
    border-radius: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    transform: none !important;
    z-index: 99999 !important;
}

.sqlatte-auth-modal {
    z-index: 99999 !important;
}

.sqlatte-chart-config-modal,
.sqlatte-chart-display-modal {
    z-index: 999999 !important;
}

        .sqlatte-auth-modal.sqlatte-auth-modal-open ~ .sqlatte-widget .sqlatte-badge-btn {
            display: none !important;
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

    // ============================================
    // PUBLIC API
    // ============================================
    window.SQLatteAuthWidget = {
        // Auth
        handleLogin: handleLogin,
        logout: logout,

        // Modals
        openLoginModal: openLoginModal,
        closeLoginModal: closeLoginModal,
        openChatModal: openChatModal,
        closeChatModal: closeChatModal,

        // Chat
        sendMessage: sendMessage,
        handleTableChange: handleTableChange,

        // History & Favorites
        toggleHistory: toggleHistory,
        toggleFavorites: toggleFavorites,
        clearHistory: clearHistory,
        rerunQuery: (sql) => {
            const input = document.getElementById('sqlatte-auth-input');
            if (input) {
                input.value = sql;
                sendMessage();
            }
        },

        // Utilities
        copySQLAction: copySQLAction,
        executeSQL: (sql) => {
            const input = document.getElementById('sqlatte-auth-input');
            if (input) {
                input.value = sql;
                sendMessage();
            }
        },
        exportToCSV: exportToCSV,
        handleChartClick: handleChartClick,
        addToFavorites: (queryId) => {
            favorites.push({ id: queryId, name: 'Query ' + queryId });
            localStorage.setItem('sqlatte_auth_favorites', JSON.stringify(favorites));
            showToast('⭐ Added to favorites', 'success');
        },

        // Config
        configure: function(options) {
            Object.assign(AUTH_WIDGET_CONFIG, options);
        },
        getConfig: function() {
            return { ...AUTH_WIDGET_CONFIG
        };
        }
    };

(function forceFullscreen() {
    const observer = new MutationObserver((mutations) => {
        // Force fullscreen on ALL modals
        const modals = document.querySelectorAll('.sqlatte-modal-content, .sqlatte-auth-modal .sqlatte-modal-content');
        modals.forEach(modal => {
            if (!modal.hasAttribute('data-fs-forced')) {
                modal.setAttribute('data-fs-forced', 'true');
                modal.classList.add('sqlatte-modal-fullscreen');

                // Nuclear option - inline styles with !important
                modal.style.cssText = `
                    position: fixed !important;
                    top: 0 !important;
                    left: 0 !important;
                    right: 0 !important;
                    bottom: 0 !important;
                    width: 100vw !important;
                    height: 100vh !important;
                    max-width: none !important;
                    max-height: none !important;
                    border-radius: 0 !important;
                    margin: 0 !important;
                    padding: 0 !important;
                    transform: none !important;
                    z-index: 99999 !important;
                `;

                console.log('✅ Fullscreen enforced on modal');
            }
        });
        const chartModals = document.querySelectorAll('.sqlatte-chart-config-modal, .sqlatte-chart-display-modal');
        chartModals.forEach(modal => {
            modal.style.zIndex = '999999';
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class', 'style']
    });

    console.log('✅ Fullscreen observer activated');
})();

})();
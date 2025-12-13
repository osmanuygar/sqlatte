/* SQLatte - Main JavaScript */
/* Handles all frontend logic and API communication */

// API Base URL - automatically detects environment
const API_BASE = window.location.protocol === 'file:' 
    ? 'http://localhost:8000'
    : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.hostname === '')
        ? 'http://localhost:8000'
        : `${window.location.protocol}//${window.location.host}`;

console.log('SQLatte API Base:', API_BASE);

// State
let currentTable = '';
let currentSchema = '';
let selectedTables = [];

/**
 * Load available tables from database
 */
async function loadTables() {
    const select = document.getElementById('tableSelect');
    try {
        const response = await fetch(`${API_BASE}/tables`);
        
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
        
        // Show friendly error in chat
        const chatArea = document.getElementById('chatArea');
        const errorMsg = document.createElement('div');
        errorMsg.className = 'message assistant';
        errorMsg.innerHTML = `
            <div class="message-avatar">☕</div>
            <div class="message-content">
                <div class="error">
                    <strong>⚠️ Connection Error</strong><br>
                    Could not connect to backend.<br><br>
                    <strong>Make sure:</strong><br>
                    1. Server is running: <code>python run.py</code><br>
                    2. Open: <code>http://localhost:8000</code> (NOT 0.0.0.0)<br>
                    3. No firewall blocking connection<br><br>
                    <strong>Current URL:</strong> ${window.location.href}<br>
                    <strong>API URL:</strong> ${API_BASE}
                </div>
            </div>
        `;
        chatArea.innerHTML = '';
        chatArea.appendChild(errorMsg);
    }
}

/**
 * Handle table selection change
 */
document.getElementById('tableSelect')?.addEventListener('change', async (e) => {
    const select = e.target;
    selectedTables = Array.from(select.selectedOptions).map(opt => opt.value);
    
    if (selectedTables.length === 0) {
        currentSchema = '';
        return;
    }
    
    try {
        if (selectedTables.length === 1) {
            // Single table
            const response = await fetch(`${API_BASE}/schema/${selectedTables[0]}`);
            const data = await response.json();
            currentSchema = data.schema;
        } else {
            // Multiple tables
            const response = await fetch(`${API_BASE}/schema/multiple`, {
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
});

/**
 * Add message to chat
 */
function addMessage(role, content) {
    const chatArea = document.getElementById('chatArea');
    const empty = chatArea.querySelector('.empty-state');
    if (empty) empty.remove();
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? '👤' : '☕';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = content;
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentDiv);
    chatArea.appendChild(messageDiv);
    
    // Auto scroll
    chatArea.scrollTop = chatArea.scrollHeight;
}

/**
 * Format table data as HTML
 */
function formatTable(columns, data) {
    if (!data || data.length === 0) {
        return '<div class="text-sm opacity-70 mt-2">No results returned.</div>';
    }
    
    let html = '<table class="results-table"><thead><tr>';
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
    html += `<div class="text-xs opacity-70 mt-2">${data.length} rows returned</div>`;
    
    return html;
}

/**
 * Render HTML safely from backend responses
 * Allows HTML tags but removes dangerous attributes
 */
function renderHTML(html) {
    // Basic sanitization: remove dangerous elements/attributes
    const sanitized = html
        .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
        .replace(/javascript:/gi, '')
        .replace(/on\w+\s*=/gi, ''); // Remove onclick, onload, etc.
    
    return sanitized;
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Send query to backend
 */
async function sendQuery() {
    const input = document.getElementById('queryInput');
    const question = input.value.trim();
    
    if (!question) return;
    
    // Disable input
    const sendBtn = document.getElementById('sendBtn');
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span class="loading"></span>';
    input.disabled = true;

    // Add user message
    addMessage('user', escapeHtml(question));
    input.value = '';

    try {
        const response = await fetch(`${API_BASE}/query`, {
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

        // Build response HTML based on response type
        let responseHTML = '';
        
        if (result.response_type === 'chat') {
            // Chat response - render HTML
            responseHTML = `<div class="chat-message">${renderHTML(result.message)}</div>`;
        } else if (result.response_type === 'sql' || result.sql) {
            // SQL response
            if (result.explanation) {
                responseHTML += `<div class="explanation"><strong>💡 Explanation:</strong><br>${escapeHtml(result.explanation)}</div>`;
            }
            
            responseHTML += `<div class="sql-code">${escapeHtml(result.sql)}</div>`;
            responseHTML += formatTable(result.columns, result.data);
        } else {
            // Fallback - render HTML if it looks like HTML
            const msg = result.message || JSON.stringify(result);
            if (msg.includes('<') && msg.includes('>')) {
                responseHTML = `<div class="chat-message">${renderHTML(msg)}</div>`;
            } else {
                responseHTML = `<div class="chat-message">${escapeHtml(msg)}</div>`;
            }
        }

        addMessage('assistant', responseHTML);

    } catch (error) {
        addMessage('assistant', `<div class="error"><strong>❌ Error:</strong> ${escapeHtml(error.message)}</div>`);
    } finally {
        // Re-enable input
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<span id="btnText">Send</span>';
        input.disabled = false;
        input.focus();
    }
}

/**
 * Handle Enter key to send (Shift+Enter for new line)
 */
document.getElementById('queryInput')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuery();
    }
});

/**
 * Initialize on page load
 */
window.addEventListener('DOMContentLoaded', () => {
    console.log('SQLatte initialized');
    loadTables();
});

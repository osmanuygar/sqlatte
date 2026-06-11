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
            const port = window.location.port || '8000';
            return window.location.protocol + '//' + window.location.hostname + ':' + port;
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
    let allTables = [];
    let currentSchema = '';
    let sessionId = null;
    let queryHistory = [];
    let favorites = [];
    let isHistoryPanelOpen = false;
    let isFavoritesPanelOpen = false;
    let isSchedulesPanelOpen = false;  // NEW
    let schedules = [];  // NEW

    // Results cache
    window.sqlatteResultsCache = {};

    /**
     * ============================================
     * SQL SYNTAX HIGHLIGHTING - NEW!
     * ============================================
     */

    function highlightSQL(sql) {
        if (!sql) return '';

        // Escape HTML first
        let highlighted = sql
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // SQL Keywords
        const keywords = [
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL',
            'ON', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN', 'IS', 'NULL',
            'ORDER BY', 'GROUP BY', 'HAVING', 'LIMIT', 'OFFSET',
            'AS', 'DISTINCT', 'ALL', 'ANY', 'SOME', 'EXISTS',
            'UNION', 'INTERSECT', 'EXCEPT',
            'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER',
            'TABLE', 'INDEX', 'VIEW', 'DATABASE', 'SCHEMA',
            'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
            'WITH', 'RECURSIVE', 'OVER', 'PARTITION BY'
        ];

        // SQL Functions
        const functions = [
            'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
            'DATE', 'NOW', 'CURRENT_DATE', 'CURRENT_TIME', 'CURRENT_TIMESTAMP',
            'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
            'CONCAT', 'SUBSTRING', 'TRIM', 'LTRIM', 'RTRIM',
            'UPPER', 'LOWER', 'LENGTH', 'REPLACE',
            'ROUND', 'FLOOR', 'CEIL', 'ABS', 'SQRT', 'POWER',
            'ROW_NUMBER', 'RANK', 'DENSE_RANK', 'LAG', 'LEAD'
        ];

        // Comments (-- style)
        highlighted = highlighted.replace(/(--.*$)/gm, '<span class="sql-comment">$1</span>');

        // Comments (/* */ style)
        highlighted = highlighted.replace(/(\/\*[\s\S]*?\*\/)/g, '<span class="sql-comment">$1</span>');

        // Strings
        highlighted = highlighted.replace(/('(?:[^']|'')*')/g, '<span class="sql-string">$1</span>');

        // Numbers
        highlighted = highlighted.replace(/\b(\d+\.?\d*)\b/g, '<span class="sql-number">$1</span>');

        // Functions
        functions.forEach(func => {
            const regex = new RegExp(`\\b(${func})\\b`, 'gi');
            highlighted = highlighted.replace(regex, '<span class="sql-function">$1</span>');
        });

        // Keywords
        keywords.forEach(keyword => {
            const regex = new RegExp(`\\b(${keyword.replace(' ', '\\s+')})\\b`, 'gi');
            highlighted = highlighted.replace(regex, '<span class="sql-keyword">$1</span>');
        });

        return highlighted;
    }

    function copySQLAction(sqlId) {
        const sqlElement = document.getElementById(sqlId);
        if (!sqlElement) return;

        const rawSQL = sqlElement.getAttribute('data-raw-sql');
        if (rawSQL) {
            const decoded = decodeHTMLEntities(rawSQL);
            copyToClipboard(decoded);
        }
    }

    function decodeHTMLEntities(text) {
        const textarea = document.createElement('textarea');
        textarea.innerHTML = text;
        return textarea.value;
    }

    function copyToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(() => {
                showToast('📋 Copied to clipboard!', 'success');
            }).catch(err => {
                console.error('Copy failed:', err);
                fallbackCopy(text);
            });
        } else {
            fallbackCopy(text);
        }
    }

    function fallbackCopy(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showToast('📋 Copied to clipboard!', 'success');
        } catch (err) {
            console.error('Fallback copy failed:', err);
            showToast('❌ Copy failed', 'error');
        }
        document.body.removeChild(textarea);
    }

    /**
     * CSV EXPORT FUNCTIONALITY
     */
    function exportToCSV(resultId) {
        const cached = window.sqlatteResultsCache[resultId];
        if (!cached) {
            alert('Results not found. Please run the query again.');
            return;
        }

        const { columns, data } = cached;

        try {
            const csv = generateCSV(columns, data);
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);

            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
            const filename = `sqlatte_export_${timestamp}.csv`;

            link.setAttribute('href', url);
            link.setAttribute('download', filename);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            showToast('📥 CSV exported successfully!', 'success');

        } catch (error) {
            console.error('CSV export error:', error);
            alert('Failed to export CSV: ' + error.message);
        }
    }

    function generateCSV(columns, data) {
        let csv = '';
        csv += columns.map(col => escapeCSVField(col)).join(',') + '\n';
        data.forEach(row => {
            csv += row.map(cell => escapeCSVField(String(cell))).join(',') + '\n';
        });
        return csv;
    }

    function escapeCSVField(field) {
        if (field === null || field === undefined) return '';
        field = String(field);
        if (field.includes(',') || field.includes('\n') || field.includes('"')) {
            return '"' + field.replace(/"/g, '""') + '"';
        }
        return field;
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
     * CHART.JS LOADER & VISUALIZATION
     */
    function loadChartJS(callback) {
        if (window.Chart) {
            callback();
            return;
        }
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
        script.onload = callback;
        script.onerror = () => alert('Failed to load chart library.');
        document.head.appendChild(script);
    }

    // ============================================
    // GELIŞMIŞ CHART — Auth widget seviyesi
    // ============================================

    function showChart(resultId, chartType) {
        const cached = window.sqlatteResultsCache[resultId];
        if (!cached) {
            alert('Results not found. Please run the query again.');
            return;
        }
        const { columns, data } = cached;
        loadChartJS(() => openChartConfigModal(resultId, columns, data));
    }

    function openChartConfigModal(resultId, columns, data) {
        const existing = document.getElementById('sqlatte-chart-config-modal');
        if (existing) existing.remove();

        // Kolon tiplerini tespit et
        const numericCols = [];
        const dimensionCols = [];
        columns.forEach((col, i) => {
            const sample = data[0] ? data[0][i] : null;
            if (sample !== null && !isNaN(parseFloat(sample)) && isFinite(sample)) {
                numericCols.push(col);
            } else {
                dimensionCols.push(col);
            }
        });
        // Fallback: eğer dimension yok, ilk kolonu al
        if (dimensionCols.length === 0 && columns.length > 0) dimensionCols.push(columns[0]);

        const modal = document.createElement('div');
        modal.id = 'sqlatte-chart-config-modal';
        modal.style.cssText = `
            position: fixed; inset: 0; background: rgba(0,0,0,0.85);
            display: flex; align-items: center; justify-content: center;
            z-index: 999999999; padding: 20px;
        `;

        modal.innerHTML = `
            <div style="background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
                        padding: 28px; border-radius: 14px; border: 1px solid #444;
                        max-width: 480px; width: 100%;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px;">
                    <h3 style="margin:0; color:#D4A574; font-size:16px;">📊 Chart Configuration</h3>
                    <button onclick="SQLatteWidget.closeChart()"
                        style="background:#333; color:white; border:none; padding:6px 12px;
                               border-radius:6px; cursor:pointer; font-size:13px;">✕ Close</button>
                </div>

                <div style="margin-bottom:18px;">
                    <label style="display:block; margin-bottom:8px; font-size:13px; font-weight:600; color:#e0e0e0;">
                        📐 Dimension (X-axis / Labels):
                    </label>
                    <select id="chart-cfg-dimension"
                        style="width:100%; padding:9px 12px; background:#0a0a0a; color:#e0e0e0;
                               border:1px solid #444; border-radius:7px; font-size:13px;">
                        ${dimensionCols.map(col => `<option value="${col}">${col}</option>`).join('')}
                        ${numericCols.map(col => `<option value="${col}">${col} (numeric)</option>`).join('')}
                    </select>
                </div>

                <div style="margin-bottom:18px;">
                    <label style="display:block; margin-bottom:8px; font-size:13px; font-weight:600; color:#e0e0e0;">
                        📈 Metrics (Y-axis) — birden fazla seçilebilir:
                    </label>
                    <div style="background:#0a0a0a; border:1px solid #444; border-radius:7px;
                                padding:12px; max-height:180px; overflow-y:auto;">
                        ${numericCols.length > 0
                            ? numericCols.map(col => `
                                <label style="display:flex; align-items:center; gap:8px; padding:6px 0; cursor:pointer; color:#e0e0e0; font-size:13px;">
                                    <input type="checkbox" value="${col}" checked
                                        style="accent-color:#D4A574; width:15px; height:15px;" />
                                    ${col}
                                </label>`).join('')
                            : `<label style="display:flex; align-items:center; gap:8px; padding:6px 0; cursor:pointer; color:#e0e0e0; font-size:13px;">
                                   <input type="checkbox" value="${columns[columns.length - 1]}" checked
                                       style="accent-color:#D4A574; width:15px; height:15px;" />
                                   ${columns[columns.length - 1]}
                               </label>`
                        }
                    </div>
                    <small style="color:#666; font-size:11px; margin-top:4px; display:block;">
                        Pie/Doughnut chart için tek metric seçin
                    </small>
                </div>

                <div style="margin-bottom:24px;">
                    <label style="display:block; margin-bottom:8px; font-size:13px; font-weight:600; color:#e0e0e0;">
                        🎨 Chart Type:
                    </label>
                    <select id="chart-cfg-type"
                        style="width:100%; padding:9px 12px; background:#0a0a0a; color:#e0e0e0;
                               border:1px solid #444; border-radius:7px; font-size:13px;">
                        <option value="bar">📊 Bar Chart</option>
                        <option value="line">📈 Line Chart</option>
                        <option value="pie">🥧 Pie Chart</option>
                        <option value="doughnut">🍩 Doughnut</option>
                    </select>
                </div>

                <button onclick="SQLatteWidget._buildChart('${resultId}')"
                    style="width:100%; padding:12px; background:linear-gradient(135deg,#8B6F47 0%,#A67C52 100%);
                           color:white; border:none; border-radius:8px; font-size:14px; font-weight:700; cursor:pointer;">
                    ✨ Chart Oluştur
                </button>
            </div>
        `;
        const sqlatteModal = document.getElementById('sqlatte-modal');
        if (sqlatteModal) sqlatteModal.classList.add('sqlatte-modal-hidden-for-chart');

        document.body.appendChild(modal);
    }

    function _buildChart(resultId) {
        const cached = window.sqlatteResultsCache[resultId];
        if (!cached) return;

        const dimension = document.getElementById('chart-cfg-dimension').value;
        const chartType = document.getElementById('chart-cfg-type').value;
        const checkedBoxes = document.querySelectorAll('#sqlatte-chart-config-modal input[type=checkbox]:checked');
        const metrics = Array.from(checkedBoxes).map(cb => cb.value);

        if (!dimension) { alert('Dimension seçin.'); return; }
        if (metrics.length === 0) { alert('En az bir metric seçin.'); return; }

        document.getElementById('sqlatte-chart-config-modal').remove();
        renderAdvancedChart(resultId, cached.columns, cached.data, dimension, metrics, chartType);
    }

    function renderAdvancedChart(resultId, columns, data, dimension, metrics, chartType) {
        const existing = document.getElementById('sqlatte-chart-display-modal');
        if (existing) existing.remove();

        const dimIdx = columns.indexOf(dimension);
        const labels = data.map(row => String(row[dimIdx] ?? ''));

        const COLORS = [
            '#D4A574', '#4ade80', '#60a5fa', '#f472b6', '#fb923c',
            '#a78bfa', '#34d399', '#fbbf24', '#f87171', '#38bdf8'
        ];

        const datasets = metrics.map((metric, i) => {
            const metIdx = columns.indexOf(metric);
            const values = data.map(row => parseFloat(row[metIdx]) || 0);
            const color = COLORS[i % COLORS.length];

            if (chartType === 'pie' || chartType === 'doughnut') {
                return {
                    label: metric,
                    data: values,
                    backgroundColor: values.map((_, j) => COLORS[j % COLORS.length]),
                    borderColor: '#1a1a1a',
                    borderWidth: 2
                };
            }
            return {
                label: metric,
                data: values,
                backgroundColor: chartType === 'line' ? color.replace(')', ', 0.2)').replace('rgb', 'rgba') : color,
                borderColor: color,
                borderWidth: 2,
                fill: chartType === 'line',
                tension: 0.4,
                pointBackgroundColor: color,
                pointRadius: 4
            };
        });

        const modal = document.createElement('div');
        modal.id = 'sqlatte-chart-display-modal';
        modal.style.cssText = `
            position: fixed; inset: 0; background: rgba(0,0,0,0.92);
            display: flex; align-items: center; justify-content: center;
            z-index: 999999999; padding: 20px;
        `;

        modal.innerHTML = `
            <div style="background: linear-gradient(135deg,#1a1a1a 0%,#2d2d2d 100%);
                        padding:24px; border-radius:14px; border:1px solid #444;
                        max-width:1100px; width:100%; max-height:90vh; overflow-y:auto;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                    <div>
                        <h3 style="margin:0; color:#D4A574; font-size:16px;">
                            📊 ${dimension} vs ${metrics.join(', ')}
                        </h3>
                        <small style="color:#666; font-size:11px;">${data.length} rows • ${chartType} chart</small>
                    </div>
                    <div style="display:flex; gap:8px;">
                        <button onclick="SQLatteWidget._openConfigAgain('${resultId}')"
                            style="background:#333; color:#D4A574; border:1px solid #D4A574; padding:7px 14px;
                                   border-radius:6px; cursor:pointer; font-size:12px; font-weight:600;">
                            ⚙️ Yeniden Yapılandır
                        </button>
                        <button onclick="SQLatteWidget.closeChart()"
                            style="background:#333; color:white; border:none; padding:7px 14px;
                                   border-radius:6px; cursor:pointer; font-size:12px;">
                            ✕ Kapat
                        </button>
                    </div>
                </div>
                <div style="position:relative; height:480px;">
                    <canvas id="sqlatte-adv-chart-canvas-${resultId}"></canvas>
                </div>
                <div style="margin-top:16px; display:flex; flex-wrap:wrap; gap:8px;">
                    ${metrics.map((m, i) => `
                        <span style="display:inline-flex; align-items:center; gap:5px; padding:4px 10px;
                                     background:#1a1a1a; border:1px solid #333; border-radius:20px; font-size:11px; color:#e0e0e0;">
                            <span style="width:10px;height:10px;border-radius:50%;background:${COLORS[i % COLORS.length]};display:inline-block;"></span>
                            ${m}
                        </span>`).join('')}
                </div>
            </div>
        `;
        const sqlatteModal = document.getElementById('sqlatte-modal');
        if (sqlatteModal) sqlatteModal.classList.add('sqlatte-modal-hidden-for-chart');

        document.body.appendChild(modal);

        const ctx = document.getElementById(`sqlatte-adv-chart-canvas-${resultId}`).getContext('2d');
        new Chart(ctx, {
            type: (chartType === 'pie' || chartType === 'doughnut') ? chartType : (chartType === 'line' ? 'line' : 'bar'),
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: '#e0e0e0', font: { size: 12 } }
                    },
                    tooltip: {
                        backgroundColor: '#1a1a1a',
                        borderColor: '#444',
                        borderWidth: 1,
                        titleColor: '#D4A574',
                        bodyColor: '#e0e0e0',
                        callbacks: chartType === 'pie' || chartType === 'doughnut' ? {
                            label: ctx => {
                                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                const pct = total ? ((ctx.raw / total) * 100).toFixed(1) : 0;
                                return ` ${ctx.label}: ${ctx.raw.toLocaleString()} (${pct}%)`;
                            }
                        } : {}
                    }
                },
                scales: (chartType !== 'pie' && chartType !== 'doughnut') ? {
                    x: {
                        ticks: { color: '#a0a0a0', maxRotation: 45 },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    y: {
                        ticks: {
                            color: '#a0a0a0',
                            callback: v => v >= 1000000 ? (v/1000000).toFixed(1)+'M'
                                         : v >= 1000 ? (v/1000).toFixed(1)+'K' : v
                        },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                } : {}
            }
        });
    }

    function _openConfigAgain(resultId) {
        document.getElementById('sqlatte-chart-display-modal').remove();
        const cached = window.sqlatteResultsCache[resultId];
        if (cached) openChartConfigModal(resultId, cached.columns, cached.data);
    }

    function closeChart() {
        const m1 = document.getElementById('sqlatte-chart-display-modal');
        const m2 = document.getElementById('sqlatte-chart-config-modal');
        const m3 = document.getElementById('sqlatte-chart-modal');
        if (m1) m1.remove();
        if (m2) m2.remove();
        if (m3) m3.remove();
        const sqlatteModal = document.getElementById('sqlatte-modal');
        if (sqlatteModal) sqlatteModal.classList.remove('sqlatte-modal-hidden-for-chart');
    }

    /**
     * SESSION MANAGEMENT
     */
    function getOrCreateSession() {
        const storedSessionId = localStorage.getItem('sqlatte_session_id');
        if (storedSessionId) {
            sessionId = storedSessionId;
        } else {
            sessionId = null;
        }
        return sessionId;
    }

    function saveSession(newSessionId) {
        sessionId = newSessionId;
        localStorage.setItem('sqlatte_session_id', newSessionId);
    }

    function clearSession() {
        sessionId = null;
        localStorage.removeItem('sqlatte_session_id');
    }

    // Acquire a server-credential-backed auto-session for embedded/widget use.
    // Returns the session_id string on success, null if auto-session is disabled
    // (403) or unavailable.
    async function acquireAutoSession() {
        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/auth/auto-session`, {
                method: 'POST',
            });
            if (!response.ok) {
                // 403 = feature disabled; any other error = fall back silently
                return null;
            }
            const data = await response.json();
            if (data.session_id) {
                saveSession(data.session_id);
                console.log('[SQLatte] auto-session acquired');
                return data.session_id;
            }
        } catch (e) {
            console.warn('[SQLatte] auto-session unavailable:', e);
        }
        return null;
    }

    // Returns fetch headers with X-Session-ID when a session is active.
    function getAuthHeaders() {
        return sessionId ? { 'X-Session-ID': sessionId } : {};
    }

    /**
     * QUERY HISTORY & FAVORITES
     */
    async function loadHistory() {
        if (!sessionId) return;

        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/history?session_id=${sessionId}&limit=20`);
            if (response.ok) {
                const data = await response.json();
                queryHistory = data.queries || [];
                renderHistoryPanel();
            }
        } catch (error) {
            console.error('Error loading history:', error);
        }
    }

    async function loadFavorites() {
        if (!sessionId) return;  // Session gerekli

        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/favorites?session_id=${sessionId}&limit=50`);
            if (response.ok) {
                const data = await response.json();
                favorites = data.favorites || [];
                renderFavoritesPanel();
            }
        } catch (error) {
            console.error('Error loading favorites:', error);
        }
    }

    async function addToFavorites(queryId, customName = null) {
        // Find the button that was clicked
        const buttons = document.querySelectorAll(`.sqlatte-fav-btn[onclick*="${queryId}"]`);
        const button = buttons[0];

        if (button) {
            // Save original content
            const originalContent = button.innerHTML;
            const originalDisabled = button.disabled;

            // Set loading state
            button.disabled = true;
            button.innerHTML = '<span class="sqlatte-loading"></span> Saving...';
            button.style.opacity = '0.7';
        }

        try {
            const body = { query_id: queryId };
            if (customName) body.favorite_name = customName;

            const response = await fetch(`${BADGE_CONFIG.apiBase}/favorites?session_id=${sessionId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (response.ok) {
                // Success state
                if (button) {
                    button.innerHTML = '✅ Saved!';
                    button.style.opacity = '1';
                    button.style.background = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';
                    button.style.transform = 'scale(1.05)';
                }

                showToast('⭐ Added to favorites!', 'success');
                loadFavorites();
                loadHistory();

                // Reset button after 2 seconds
                if (button) {
                    setTimeout(() => {
                        button.innerHTML = originalContent;
                        button.disabled = originalDisabled;
                        button.style.opacity = '1';
                        button.style.background = '';
                        button.style.transform = '';
                    }, 2000);
                }
            } else {
                throw new Error('Failed to add favorite');
            }
        } catch (error) {
            console.error('Error adding favorite:', error);
            showToast('❌ Failed to add favorite', 'error');

            // Error state
            if (button) {
                button.innerHTML = '❌ Failed';
                button.style.opacity = '1';
                button.style.background = 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)';

                setTimeout(() => {
                    button.innerHTML = originalContent;
                    button.disabled = originalDisabled;
                    button.style.opacity = '1';
                    button.style.background = '';
                }, 2000);
            }
        }
    }

    async function removeFromFavorites(queryId) {
        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/favorites/${queryId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            // Check if schedules exist
            if (result.error === 'scheduled_queries_exist') {
                const count = result.schedules.length;
                const scheduleNames = result.schedules
                    .map(s => `  • ${s.name} (${s.frequency})`)
                    .join('\n');

                const message = `⚠️ Bu query'e bağlı ${count} aktif schedule var:\n\n${scheduleNames}\n\nFavorite ve tüm schedule'ları silmek istiyor musunuz?`;

                if (confirm(message)) {
                    // Force delete - cascade
                    const forceResponse = await fetch(
                        `${BADGE_CONFIG.apiBase}/favorites/${queryId}?force=true`,
                        { method: 'DELETE' }
                    );

                    const forceResult = await forceResponse.json();

                    if (forceResponse.ok) {
                        showToast(`✅ Favorite ve ${forceResult.schedules_deleted} schedule silindi`, 'success');
                        loadFavorites();
                        loadHistory();
                    } else {
                        throw new Error(forceResult.detail || 'Failed to delete');
                    }
                } else {
                    showToast('❌ İptal edildi', 'info');
                }
                return;
            }

            if (response.ok) {
                showToast('🗑️ Removed from favorites', 'info');
                loadFavorites();
                loadHistory();
            }
        } catch (error) {
            console.error('Error removing favorite:', error);
            showToast('❌ Failed to remove favorite', 'error');
        }
    }

    async function deleteFromHistory(queryId) {
        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/history/${queryId}?session_id=${sessionId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                showToast('🗑️ Deleted from history', 'info');
                loadHistory();
            }
        } catch (error) {
            console.error('Error deleting from history:', error);
        }
    }

    function useQuery(query) {
        const input = document.getElementById('sqlatte-input');
        if (input) {
            input.value = query.question;
            input.focus();
        }

        if (query.tables && query.tables.length > 0) {
            const select = document.getElementById('sqlatte-table-select');
            if (select) {
                Array.from(select.options).forEach(opt => {
                    opt.selected = query.tables.includes(opt.value);
                });
                handleTableChange();
            }
        }

        closeHistoryPanel();
        closeFavoritesPanel();

        showToast('📝 Query loaded - press Enter to run', 'info');
    }

    function renderHistoryPanel() {
        const panel = document.getElementById('sqlatte-history-panel');
        if (!panel) return;

        if (queryHistory.length === 0) {
            panel.innerHTML = `
                <div class="sqlatte-panel-empty">
                    <span>📜</span>
                    <p>No query history yet</p>
                    <small>Your queries will appear here</small>
                </div>
            `;
            return;
        }

        let html = '<div class="sqlatte-panel-list">';

        queryHistory.forEach(query => {
            const timeAgo = getTimeAgo(query.created_at);
            const isFav = query.is_favorite;

            html += `
                <div class="sqlatte-history-item ${isFav ? 'sqlatte-history-item-favorite' : ''}">
                    <div class="sqlatte-history-item-header">
                        <span class="sqlatte-history-question" onclick="SQLatteWidget.useQuery(${JSON.stringify(query).replace(/"/g, '&quot;')})">${escapeHtml(truncate(query.question, 50))}</span>
                        <span class="sqlatte-history-time">${timeAgo}</span>
                    </div>
                    <div class="sqlatte-history-item-meta">
                        <span class="sqlatte-history-rows">${query.row_count} rows</span>
                        <span class="sqlatte-history-tables">${query.tables.join(', ') || 'N/A'}</span>
                    </div>
                    <div class="sqlatte-history-item-actions">
                        <button onclick="SQLatteWidget.useQuery(${JSON.stringify(query).replace(/"/g, '&quot;')})" title="Use this query">▶️</button>
                        ${isFav
                            ? `<button onclick="SQLatteWidget.removeFromFavorites('${query.id}')" title="Remove from favorites">💔</button>`
                            : `<button onclick="SQLatteWidget.addToFavorites('${query.id}')" title="Add to favorites">⭐</button>`
                        }
                        <button onclick="SQLatteWidget.deleteFromHistory('${query.id}')" title="Delete">🗑️</button>
                    </div>
                </div>
            `;
        });

        html += '</div>';
        panel.innerHTML = html;
    }

    function renderFavoritesPanel() {
        const panel = document.getElementById('sqlatte-favorites-panel');
        if (!panel) return;

        if (favorites.length === 0) {
            panel.innerHTML = `
                <div class="sqlatte-panel-empty">
                    <span>⭐</span>
                    <p>No favorites yet</p>
                    <small>Star your frequent queries</small>
                </div>
            `;
            return;
        }

        let html = '<div class="sqlatte-panel-list">';

        favorites.forEach(fav => {
            html += `
                <div class="sqlatte-favorite-item">
                    <div class="sqlatte-favorite-item-header">
                        <span class="sqlatte-favorite-name" onclick="SQLatteWidget.useQuery(${JSON.stringify(fav).replace(/"/g, '&quot;')})">⭐ ${escapeHtml(fav.favorite_name || truncate(fav.question, 40))}</span>
                    </div>
                    <div class="sqlatte-favorite-item-meta">
                        <span class="sqlatte-favorite-tables">${fav.tables.join(', ') || 'N/A'}</span>
                    </div>
                    <div class="sqlatte-favorite-item-actions">
                        <button onclick="SQLatteWidget.useQuery(${JSON.stringify(fav).replace(/"/g, '&quot;')})" title="Use this query">▶️</button>
                        <button onclick="SQLatteWidget.removeFromFavorites('${fav.id}')" title="Remove">💔</button>
                    </div>
                </div>
            `;
        });

        html += '</div>';
        panel.innerHTML = html;
    }

    function toggleHistoryPanel() {
        const panel = document.getElementById('sqlatte-history-panel');
        const btn = document.getElementById('sqlatte-history-btn');

        if (isHistoryPanelOpen) {
            closeHistoryPanel();
        } else {
            closeFavoritesPanel();
            panel.classList.add('sqlatte-panel-open');
            btn.classList.add('sqlatte-toolbar-btn-active');
            isHistoryPanelOpen = true;
            loadHistory();
        }
    }

    function closeHistoryPanel() {
        const panel = document.getElementById('sqlatte-history-panel');
        const btn = document.getElementById('sqlatte-history-btn');
        if (panel) panel.classList.remove('sqlatte-panel-open');
        if (btn) btn.classList.remove('sqlatte-toolbar-btn-active');
        isHistoryPanelOpen = false;
    }

    function toggleFavoritesPanel() {
        const panel = document.getElementById('sqlatte-favorites-panel');
        const btn = document.getElementById('sqlatte-favorites-btn');

        if (isFavoritesPanelOpen) {
            closeFavoritesPanel();
        } else {
            closeHistoryPanel();
            panel.classList.add('sqlatte-panel-open');
            btn.classList.add('sqlatte-toolbar-btn-active');
            isFavoritesPanelOpen = true;
            loadFavorites();
        }
    }

    function closeFavoritesPanel() {
        const panel = document.getElementById('sqlatte-favorites-panel');
        const btn = document.getElementById('sqlatte-favorites-btn');
        if (panel) panel.classList.remove('sqlatte-panel-open');
        if (btn) btn.classList.remove('sqlatte-toolbar-btn-active');
        isFavoritesPanelOpen = false;
    }

    /**
     * ============================================
     * SCHEDULES PANEL FUNCTIONS
     * ============================================
     */

    async function loadSchedules() {
        if (!sessionId) return;  // Session gerekli

        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/api/schedules?session_id=${sessionId}`);

            if (!response.ok) {
                console.error('Failed to load schedules');
                return;
            }

            const data = await response.json();
            schedules = data || [];

            console.log('✅ Loaded schedules:', schedules.length);
            renderSchedulesPanel();

        } catch (error) {
            console.error('❌ Failed to load schedules:', error);
        }
    }

    function toggleSchedulesPanel() {
        const panel = document.getElementById('sqlatte-schedules-panel');
        const btn = document.getElementById('sqlatte-schedules-btn');

        if (isSchedulesPanelOpen) {
            closeSchedulesPanel();
        } else {
            closeHistoryPanel();
            closeFavoritesPanel();
            panel.classList.add('sqlatte-panel-open');
            btn.classList.add('sqlatte-toolbar-btn-active');
            isSchedulesPanelOpen = true;
            loadSchedules();
        }
    }

    function closeSchedulesPanel() {
        const panel = document.getElementById('sqlatte-schedules-panel');
        const btn = document.getElementById('sqlatte-schedules-btn');
        if (panel) panel.classList.remove('sqlatte-panel-open');
        if (btn) btn.classList.remove('sqlatte-toolbar-btn-active');
        isSchedulesPanelOpen = false;
    }

    function renderSchedulesPanel() {
        const panelContent = document.querySelector('#sqlatte-schedules-panel .sqlatte-panel-content');
        if (!panelContent) return;

        if (schedules.length === 0) {
            panelContent.innerHTML = `
                <div class="sqlatte-panel-empty">
                    <span>📅</span>
                    <p>No schedules yet</p>
                    <button onclick="SQLatteWidget.openScheduleModal()" class="sqlatte-btn-primary" style="margin-top: 15px; padding: 10px 20px;">
                        Create Schedule
                    </button>
                </div>
            `;
            return;
        }

        let html = '<div class="sqlatte-schedules-list" style="padding: 15px;">';

        schedules.forEach(schedule => {
            const statusClass = schedule.enabled ? 'success' : 'warning';
            const statusText = schedule.enabled ? 'Active' : 'Paused';
            const toggleIcon = schedule.enabled ? '⏸️' : '▶️';
            const toggleTitle = schedule.enabled ? 'Pause' : 'Resume';

            html += `
                <div class="sqlatte-schedule-card" style="background: #0f0f0f; border: 1px solid #333; border-radius: 8px; padding: 15px; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                        <div>
                            <h5 style="margin: 0 0 5px 0; color: #e0e0e0;">${escapeHtml(schedule.name)}</h5>
                            <span style="display: inline-block; padding: 2px 8px; background: ${statusClass === 'success' ? '#4ade8033' : '#fbbf2433'}; color: ${statusClass === 'success' ? '#4ade80' : '#fbbf24'}; border-radius: 4px; font-size: 10px; font-weight: 600; text-transform: uppercase;">
                                ${statusText}
                            </span>
                        </div>
                        <div style="display: flex; gap: 5px;">
                            <button onclick="SQLatteWidget.runScheduleNow('${schedule.id}')" title="Run Now" style="padding: 5px 8px; background: transparent; border: 1px solid #333; border-radius: 4px; color: #e0e0e0; cursor: pointer; font-size: 12px;">
                                ▶️
                            </button>
                            <button onclick="SQLatteWidget.toggleSchedule('${schedule.id}')" title="${toggleTitle}" style="padding: 5px 8px; background: transparent; border: 1px solid #333; border-radius: 4px; color: #e0e0e0; cursor: pointer; font-size: 12px;">
                                ${toggleIcon}
                            </button>
                            <button onclick="SQLatteWidget.deleteSchedule('${schedule.id}', '${escapeHtml(schedule.name).replace(/'/g, "\\'")}');" title="Delete" style="padding: 5px 8px; background: transparent; border: 1px solid #333; border-radius: 4px; color: #e0e0e0; cursor: pointer; font-size: 12px;">
                                🗑️
                            </button>
                        </div>
                    </div>

                    <div style="font-size: 12px; color: #888; margin-bottom: 10px;">
                        <div><strong style="color: #e0e0e0;">Frequency:</strong> ${schedule.frequency}</div>
                        <div><strong style="color: #e0e0e0;">Recipients:</strong> ${schedule.email_recipients.slice(0, 2).join(', ')}${schedule.email_recipients.length > 2 ? '...' : ''}</div>
                        <div><strong style="color: #e0e0e0;">Format:</strong> ${schedule.format.toUpperCase()}</div>
                    </div>

                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; font-size: 11px;">
                        <div>
                            <small style="color: #666;">Last Run</small>
                            <div style="color: #D4A574;">${schedule.last_run ? new Date(schedule.last_run).toLocaleString('en-US', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : 'Never'}</div>
                        </div>
                        <div>
                            <small style="color: #666;">Next Run</small>
                            <div style="color: #D4A574;">${schedule.next_run ? new Date(schedule.next_run).toLocaleString('en-US', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '-'}</div>
                        </div>
                        <div>
                            <small style="color: #666;">Total</small>
                            <div style="color: #D4A574;">${schedule.run_count || 0}</div>
                        </div>
                    </div>
                </div>
            `;
        });

        html += '</div>';

        // ✅ Add "Create New Schedule" button at the bottom
        html += `
            <div style="padding: 15px; text-align: center;">
                <button onclick="SQLatteWidget.openScheduleModal()" class="sqlatte-btn-primary" style="padding: 10px 20px; background: linear-gradient(135deg, #D4A574 0%, #A67C52 100%); border: none; border-radius: 6px; color: white; font-weight: 600; cursor: pointer;">
                    ➕ Create New Schedule
                </button>
            </div>
        `;

        panelContent.innerHTML = html;
    }

    async function runScheduleNow(scheduleId) {
        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/api/schedules/${scheduleId}/run`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error('Failed to run schedule');

            showToast('✅ Schedule execution started!', 'success');
            setTimeout(() => loadSchedules(), 2000);

        } catch (error) {
            console.error('Failed to run schedule:', error);
            showToast('Failed to run schedule', 'error');
        }
    }

    async function toggleSchedule(scheduleId) {
        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/api/schedules/${scheduleId}/toggle`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error('Failed to toggle schedule');

            showToast('✅ Schedule updated', 'success');
            loadSchedules();

        } catch (error) {
            console.error('Failed to toggle schedule:', error);
            showToast('Failed to update schedule', 'error');
        }
    }

    async function deleteSchedule(scheduleId, scheduleName) {
        if (!confirm(`Delete schedule "${scheduleName}"?`)) return;

        try {
            const response = await fetch(`${BADGE_CONFIG.apiBase}/api/schedules/${scheduleId}`, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error('Failed to delete schedule');

            showToast('✅ Schedule deleted', 'success');
            loadSchedules();

        } catch (error) {
            console.error('Failed to delete schedule:', error);
            showToast('Failed to delete schedule', 'error');
        }
    }

    function openScheduleModal(queryId = null) {
        console.log('📅 Opening schedule modal, queryId:', queryId);
        console.log('📅 Favorites count:', favorites.length);

        const modal = document.createElement('div');
        modal.id = 'sqlatte-schedule-modal';
        modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 999999999;';

        modal.innerHTML = `
            <div style="width: 500px; max-width: 90vw; max-height: 80vh; overflow-y: auto; background: #1a1a1a; border: 1px solid #333; border-radius: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 20px; border-bottom: 1px solid #333;">
                    <h3 style="margin: 0; color: #D4A574; font-size: 18px;">📅 Create Schedule</h3>
                    <button onclick="SQLatteWidget.closeScheduleModal()" style="background: none; border: none; color: #888; font-size: 24px; cursor: pointer;">✕</button>
                </div>

                <div style="padding: 20px;">
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Select Query *</label>
                        <select id="schedule-query-select" style="width: 100%; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0;">
                            <option value="">Choose from favorites...</option>
                        </select>
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Schedule Name *</label>
                        <input type="text" id="schedule-name" placeholder="e.g., Daily Sales Report" style="width: 100%; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0;">
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Frequency *</label>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;">
                            <button class="freq-tab active" data-freq="daily" style="padding: 10px; background: linear-gradient(135deg, #D4A574 0%, #A67C52 100%); border: 1px solid #D4A574; border-radius: 6px; color: white; cursor: pointer; font-weight: 600;">Daily</button>
                            <button class="freq-tab" data-freq="weekly" style="padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0; cursor: pointer;">Weekly</button>
                            <button class="freq-tab" data-freq="monthly" style="padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0; cursor: pointer;">Monthly</button>
                        </div>
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Time</label>
                        <input type="time" id="schedule-time" value="09:00" style="width: 100%; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0;">
                    </div>

                    <div id="weekly-select" style="display: none; margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Day of Week</label>
                        <select id="schedule-weekday" style="width: 100%; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0;">
                            <option value="1">Monday</option>
                            <option value="2">Tuesday</option>
                            <option value="3">Wednesday</option>
                            <option value="4">Thursday</option>
                            <option value="5">Friday</option>
                            <option value="6">Saturday</option>
                            <option value="0">Sunday</option>
                        </select>
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Email Recipients *</label>
                        <input type="text" id="schedule-emails" placeholder="email@company.com, another@company.com" style="width: 100%; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0;">
                        <small style="color: #888; font-size: 11px;">Separate multiple emails with commas</small>
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Email Subject (Optional)</label>
                        <input type="text" id="schedule-email-subject" placeholder="e.g., Daily Sales Report - {{date}}" style="width: 100%; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0;">
                        <small style="color: #888; font-size: 11px;">Leave empty for default subject</small>
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Custom Message (Optional)</label>
                        <textarea id="schedule-email-body" placeholder="Add a custom message to include in the email..." style="width: 100%; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #e0e0e0; min-height: 80px; resize: vertical; font-family: inherit;"></textarea>
                        <small style="color: #888; font-size: 11px;">This message will appear in the email body</small>
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-size: 13px; color: #e0e0e0;">Format</label>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
                            <label style="display: flex; align-items: center; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; cursor: pointer;">
                                <input type="radio" name="format" value="csv" style="margin-right: 8px;">
                                <span>📄 CSV</span>
                            </label>
                            <label style="display: flex; align-items: center; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; cursor: pointer;">
                                <input type="radio" name="format" value="excel" checked style="margin-right: 8px;">
                                <span>📊 Excel</span>
                            </label>
                            <label style="display: flex; align-items: center; padding: 10px; background: #0f0f0f; border: 1px solid #333; border-radius: 6px; cursor: pointer;">
                                <input type="radio" name="format" value="html" style="margin-right: 8px;">
                                <span>🌐 HTML</span>
                            </label>
                        </div>
                    </div>
                </div>

                <div style="display: flex; justify-content: flex-end; gap: 10px; padding: 20px; border-top: 1px solid #333;">
                    <button onclick="SQLatteWidget.closeScheduleModal()" style="padding: 10px 20px; background: transparent; border: 1px solid #333; border-radius: 6px; color: #e0e0e0; cursor: pointer;">Cancel</button>
                    <button onclick="SQLatteWidget.createSchedule()" style="padding: 10px 20px; background: linear-gradient(135deg, #D4A574 0%, #A67C52 100%); border: none; border-radius: 6px; color: white; font-weight: 600; cursor: pointer;">Create</button>
                </div>
            </div>
        `;

        const parent = document.getElementById('sqlatte-modal');
        (parent || document.body).appendChild(modal);
        console.log('📅 Modal added to DOM');

        // Load favorites
        const select = document.getElementById('schedule-query-select');
        console.log('📅 Select element:', select);

        favorites.forEach(fav => {
            const option = document.createElement('option');
            option.value = fav.id;
            option.textContent = fav.question || fav.name || 'Unnamed';
            select.appendChild(option);
        });

        if (queryId) select.value = queryId;

        // Frequency tabs
        document.querySelectorAll('.freq-tab').forEach(tab => {
            tab.addEventListener('click', function() {
                document.querySelectorAll('.freq-tab').forEach(t => {
                    t.style.background = '#0f0f0f';
                    t.style.borderColor = '#333';
                    t.style.color = '#e0e0e0';
                    t.style.fontWeight = 'normal';
                    t.classList.remove('active');
                });
                this.style.background = 'linear-gradient(135deg, #D4A574 0%, #A67C52 100%)';
                this.style.borderColor = '#D4A574';
                this.style.color = 'white';
                this.style.fontWeight = '600';
                this.classList.add('active');

                const freq = this.dataset.freq;
                document.getElementById('weekly-select').style.display = freq === 'weekly' ? 'block' : 'none';
            });
        });
    }

    function closeScheduleModal() {
        const modal = document.getElementById('sqlatte-schedule-modal');
        if (modal) modal.remove();
    }

    async function createSchedule() {
        try {
            const queryId = document.getElementById('schedule-query-select').value;
            const name = document.getElementById('schedule-name').value;
            const time = document.getElementById('schedule-time').value;
            const emails = document.getElementById('schedule-emails').value;
            const emailSubject = document.getElementById('schedule-email-subject')?.value || null;
            const emailBody = document.getElementById('schedule-email-body')?.value || null;
            const format = document.querySelector('input[name="format"]:checked').value;
            const freq = document.querySelector('.freq-tab.active').dataset.freq;

            if (!queryId || !name || !emails) {
                showToast('Please fill all required fields', 'error');
                return;
            }

            const [hour, minute] = time.split(':');
            let cron;

            if (freq === 'daily') {
                cron = `${minute} ${hour} * * *`;
            } else if (freq === 'weekly') {
                const day = document.getElementById('schedule-weekday').value;
                cron = `${minute} ${hour} * * ${day}`;
            } else {
                cron = `${minute} ${hour} 1 * *`;
            }

            const emailList = emails.split(',').map(e => e.trim()).filter(e => e);

            const scheduleData = {
                query_id: queryId,
                name: name,
                frequency: freq,
                cron_expression: cron,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                email_recipients: emailList,
                format: format,
                enabled: true
            };

            // Add optional fields if provided
            if (emailSubject) {
                scheduleData.email_subject = emailSubject;
            }
            if (emailBody) {
                scheduleData.email_body = emailBody;
            }

            const response = await fetch(`${BADGE_CONFIG.apiBase}/api/schedules`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(scheduleData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to create schedule');
            }

            showToast('✅ Schedule created!', 'success');
            closeScheduleModal();
            loadSchedules();

        } catch (error) {
            console.error('Failed to create schedule:', error);
            showToast(`Failed: ${error.message}`, 'error');
        }
    }


    function getTimeAgo(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;
        return date.toLocaleDateString();
    }

    function truncate(str, len) {
        if (!str) return '';
        return str.length > len ? str.substring(0, len) + '...' : str;
    }

    /**
     * CREATE WIDGET
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

        const modal = createModal();
        document.body.appendChild(modal);

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
     * CREATE MODAL
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

            <div class="sqlatte-modal-toolbar-extended">
                <div class="sqlatte-toolbar-buttons">
                    <button id="sqlatte-history-btn" class="sqlatte-toolbar-btn" onclick="SQLatteWidget.toggleHistory()" title="Query History">
                        📜 History
                    </button>
                    <button id="sqlatte-favorites-btn" class="sqlatte-toolbar-btn" onclick="SQLatteWidget.toggleFavorites()" title="Favorites">
                        ⭐ Favorites
                    </button>
                    <button id="sqlatte-schedules-btn" class="sqlatte-toolbar-btn" onclick="SQLatteWidget.toggleSchedules()" title="Scheduled Queries">
                        📅 Schedules
                    </button>
                </div>
                <div class="sqlatte-toolbar-search" style="margin-bottom: 6px;">
                    <input type="text"
                           id="sqlatte-table-search"
                           placeholder="🔍 Search tables..."
                           oninput="SQLatteWidget.filterTables(this.value)"
                           style="width:100%; padding:7px 12px; background:#0a0a0a; border:1px solid #333;
                                  border-radius:6px; color:#e0e0e0; font-size:12px; font-family:inherit; box-sizing:border-box;" />
                </div>
                <div class="sqlatte-toolbar-tables">
                    <label>Tables:</label>
                    <select id="sqlatte-table-select" multiple onchange="SQLatteWidget.handleTableChange()">
                        <option value="">Loading...</option>
                    </select>
                    <small>Ctrl+Click for multiple</small>
                </div>
            </div>

            <div id="sqlatte-history-panel" class="sqlatte-slide-panel">
                <div class="sqlatte-panel-header">
                    <h4>📜 Query History</h4>
                    <button onclick="SQLatteWidget.closeHistoryPanel()">✕</button>
                </div>
                <div class="sqlatte-panel-content">
                    <div class="sqlatte-panel-empty">
                        <span>📜</span>
                        <p>Loading history...</p>
                    </div>
                </div>
            </div>

            <div id="sqlatte-favorites-panel" class="sqlatte-slide-panel">
                <div class="sqlatte-panel-header">
                    <h4>⭐ Favorites</h4>
                    <button onclick="SQLatteWidget.closeFavoritesPanel()">✕</button>
                </div>
                <div class="sqlatte-panel-content">
                    <div class="sqlatte-panel-empty">
                        <span>⭐</span>
                        <p>Loading favorites...</p>
                    </div>
                </div>
            </div>

            <div id="sqlatte-schedules-panel" class="sqlatte-slide-panel">
                <div class="sqlatte-panel-header">
                    <h4>📅 Scheduled Queries</h4>
                    <button onclick="SQLatteWidget.closeSchedulesPanel()">✕</button>
                </div>
                <div class="sqlatte-panel-content">
                    <div class="sqlatte-panel-empty">
                        <span>📅</span>
                        <p>Loading schedules...</p>
                    </div>
                </div>
            </div>

            <div class="sqlatte-modal-body">
                <div class="sqlatte-chat-area" id="sqlatte-chat-area">
                    <div class="sqlatte-empty-state">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                        </svg>
                        <h3>Welcome to SQLatte!</h3>
                        <p>I remember our conversation! Ask me anything.</p>
                        <p class="text-xs">💡 Tip: Use History to replay queries, Favorites to save them</p>
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

            if (sessionId) {
                loadHistory();
                loadFavorites();
            }
        }
    }

    function closeModal() {
        const modal = document.getElementById('sqlatte-modal');
        if (modal) {
            modal.classList.remove('sqlatte-modal-open');
            modal.classList.remove('sqlatte-modal-fullscreen');
            isModalOpen = false;
            closeHistoryPanel();
            closeFavoritesPanel();
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
        queryHistory = [];

        const chatArea = document.getElementById('sqlatte-chat-area');
        if (chatArea) {
            chatArea.innerHTML = `
                <div class="sqlatte-empty-state">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <h3>New Conversation</h3>
                    <p>Your previous chat has been cleared.</p>
                </div>
            `;
        }

        renderHistoryPanel();
    }

    async function loadTables() {
        const select = document.getElementById('sqlatte-table-select');
        if (!select) return;

        // Try to acquire an auto-session if none is active.
        if (!sessionId) await acquireAutoSession();

        const doFetch = () => {
            if (sessionId) {
                return fetch(`${BADGE_CONFIG.apiBase}/auth/tables`, {
                    headers: getAuthHeaders(),
                });
            }
            return fetch(`${BADGE_CONFIG.apiBase}/tables`);
        };

        try {
            let response = await doFetch();

            // Session expired — drop it and retry once with a fresh auto-session.
            if (response.status === 401 && sessionId) {
                clearSession();
                await acquireAutoSession();
                response = await doFetch();
            }

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const data = await response.json();
            allTables = data.tables || [];
            updateTableList(allTables);

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

    function updateTableList(tables) {
        const select = document.getElementById('sqlatte-table-select');
        if (!select) return;
        if (tables.length === 0) {
            select.innerHTML = '<option value="">No tables available</option>';
        } else {
            select.innerHTML = tables.map(t => `<option value="${t}">${t}</option>`).join('');
        }
    }

    function filterTables(searchTerm) {
        const filtered = allTables.filter(table =>
            table.toLowerCase().includes(searchTerm.toLowerCase())
        );
        updateTableList(filtered);
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
            const authHeaders = getAuthHeaders();
            if (selectedTables.length === 1) {
                const schemaPath = sessionId
                    ? `/auth/schema/${selectedTables[0]}`
                    : `/schema/${selectedTables[0]}`;
                let resp = await fetch(`${BADGE_CONFIG.apiBase}${schemaPath}`, {
                    headers: authHeaders,
                });
                if (resp.status === 401 && sessionId) {
                    clearSession();
                    await acquireAutoSession();
                    resp = await fetch(`${BADGE_CONFIG.apiBase}/auth/schema/${selectedTables[0]}`, {
                        headers: getAuthHeaders(),
                    });
                }
                const data = await resp.json();
                currentSchema = data.schema;
            } else {
                const schemaPath = sessionId ? `/auth/schema/multiple` : `/schema/multiple`;
                let resp = await fetch(`${BADGE_CONFIG.apiBase}${schemaPath}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...authHeaders },
                    body: JSON.stringify({ tables: selectedTables })
                });
                if (resp.status === 401 && sessionId) {
                    clearSession();
                    await acquireAutoSession();
                    resp = await fetch(`${BADGE_CONFIG.apiBase}/auth/schema/multiple`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                        body: JSON.stringify({ tables: selectedTables })
                    });
                }
                const data = await resp.json();
                currentSchema = data.combined_schema;
            }
        } catch (error) {
            console.error('Error loading schema:', error);
        }
    }

    /**
     * Convert markdown text to formatted HTML
     * Safely handles chat messages without affecting SQL tables
     */
    function markdownToHtml(text) {
        if (!text) return '';
        if (text.includes('<table') || text.includes('<div class="sqlatte')) {
            return text;
        }

        let html = text;

        // 1. Code blocks (```language\ncode```) - Process FIRST
        html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre class="sqlatte-code-block"><code class="language-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`;
        });

        // 2. Inline code (`code`)
        html = html.replace(/`([^`]+)`/g, '<code class="sqlatte-inline-code">$1</code>');

        // 3. Bold (**text** or __text__)
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

        // 4. Italic (*text* or _text_) - Careful with asterisks
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        html = html.replace(/_([^_]+)_/g, '<em>$1</em>');

        // 5. Links [text](url)
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="sqlatte-link">$1</a>');

        // 6. Headings
        html = html.replace(/^### (.+)$/gm, '<h3 class="sqlatte-h3">$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2 class="sqlatte-h2">$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1 class="sqlatte-h1">$1</h1>');

        // 7. Unordered lists (- item or * item)
        html = html.replace(/^\s*[-*]\s+(.+)$/gm, '<li class="sqlatte-li">$1</li>');
        html = html.replace(/(<li class="sqlatte-li">.*?<\/li>\n?)+/g, '<ul class="sqlatte-ul">$&</ul>');

        // 8. Blockquotes (> text)
        html = html.replace(/^>\s+(.+)$/gm, '<blockquote class="sqlatte-blockquote">$1</blockquote>');

        // 9. Paragraphs - Only if not already formatted
        if (!html.includes('<table') && !html.includes('<pre')) {
            html = html.split('\n\n').map(para => {
                para = para.trim();
                if (!para) return '';
                // Skip if already wrapped in HTML
                if (para.startsWith('<')) return para;
                return `<p class="sqlatte-paragraph">${para.replace(/\n/g, '<br>')}</p>`;
            }).filter(p => p).join('\n');
        }

        return html;
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

    /**
     * FORMAT TABLE WITH SQL HIGHLIGHTING - UPDATED!
     */
    function formatTable(columns, data, queryId = null, sql = null, explanation = null, insights=null) {
        if (!data || data.length === 0) {
            return '<div class="text-sm" style="opacity: 0.7; margin-top: 8px;">No results returned.</div>';
        }

        const resultId = 'result-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
        window.sqlatteResultsCache[resultId] = { columns, data };

        let html = '';

        // Explanation
        if (explanation) {
            const formattedExplanation = markdownToHtml(explanation);
            html += `<div class="sqlatte-explanation"><strong>💡 Explanation:</strong><br>${formattedExplanation}</div>`;
        }

        // SQL Code Block with Highlighting - NEW!
        if (sql) {
            const sqlId = 'sql-' + resultId;
            html += `
                <div class="sqlatte-sql-container">
                    <div class="sqlatte-sql-toolbar">
                        <span class="sqlatte-sql-label">📝 SQL Query</span>
                        <div class="sqlatte-sql-actions">
                            <button onclick="SQLatteWidget.copySQL('${sqlId}')" title="Copy SQL">
                                📋 Copy
                            </button>
                        </div>
                    </div>
                    <div class="sqlatte-sql-code" id="${sqlId}" data-raw-sql="${escapeHtml(sql).replace(/"/g, '&quot;')}">
                        <pre><code>${highlightSQL(sql)}</code></pre>
                    </div>
                </div>
            `;
        }
        if (insights && insights.length > 0) {
        html += '<div class="sqlatte-insights-panel">';
        html += '<div class="sqlatte-insights-header">🧠 Hızlı Görüş</div>';

        insights.forEach(insight => {
            const severityClass = `severity-${insight.severity || 'info'}`;
            const icon = insight.icon || '•';
            const message = escapeHtml(insight.message);

            html += `
                <div class="sqlatte-insight-card ${severityClass}">
                    <div class="sqlatte-insight-icon">${icon}</div>
                    <div class="sqlatte-insight-content">${message}</div>
                </div>
            `;
            });

        html += '</div>';
        }

        // Results


        html += '<div class="sqlatte-results-container">';

        html += `<div class="sqlatte-results-toolbar">`;
        html += `<button class="sqlatte-export-btn" onclick="SQLatteWidget.exportCSV('${resultId}')" title="Export to CSV">📥 CSV</button>`;
        html += `<button class="sqlatte-chart-btn" onclick="SQLatteWidget.showChart('${resultId}')" title="Visualize">📊 Chart</button>`;

        if (queryId) {
            html += `<button class="sqlatte-fav-btn" onclick="SQLatteWidget.addToFavorites('${queryId}')" title="Add to Favorites">⭐ Save</button>`;
        }

        html += `<span class="text-xs" style="opacity: 0.7; margin-left: auto;">${data.length} rows</span>`;
        html += `</div>`;

        html += '<table class="sqlatte-results-table"><thead><tr>';
        columns.forEach(col => {
            html += `<th title="${escapeHtml(col)}">${escapeHtml(col)}</th>`;
        });
        html += '</tr></thead><tbody>';

        data.forEach(row => {
            html += '<tr>';
            row.forEach(cell => {
                const cellValue = escapeHtml(String(cell));
                html += `<td title="${cellValue}">${cellValue}</td>`;
            });
            html += '</tr>';
        });

        html += '</tbody></table></div>';

        return html;
    }

    function renderHTML(html) {
        return html
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/javascript:/gi, '')
            .replace(/on\w+\s*=/gi, '');
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * SEND MESSAGE - UPDATED WITH SQL INFO!
     */
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

        const doQuery = async () => {
            if (sessionId) {
                return fetch(`${BADGE_CONFIG.apiBase}/auth/query`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                    body: JSON.stringify({ question, table_schema: currentSchema })
                });
            }
            return fetch(`${BADGE_CONFIG.apiBase}/query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question, table_schema: currentSchema, session_id: sessionId })
            });
        };

        try {
            let response = await doQuery();

            // Session expired mid-conversation — refresh and retry once.
            if (response.status === 401 && sessionId) {
                clearSession();
                await acquireAutoSession();
                response = await doQuery();
            }

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Query failed');
            }

            const result = await response.json();

            if (result.session_id) {
                saveSession(result.session_id);
            }

            let responseHTML = '';

            if (result.response_type === 'warning') {
                const sqlBlock = result.sql
                    ? `<pre class="sqlatte-warning-sql">${escapeHtml(result.sql)}</pre>`
                    : '';
                responseHTML = `
                    <div class="sqlatte-security-warning">
                        <strong>🔒 Security Warning: Only SELECT queries are allowed</strong><br>
                        <span>${escapeHtml(result.reason || result.message || '')}</span>
                        ${sqlBlock}
                    </div>`;
            } else if (result.response_type === 'chat') {
                const formattedMessage = markdownToHtml(result.message);
                responseHTML = `<div class="sqlatte-chat-message">${formattedMessage}</div>`;
            } else if (result.response_type === 'sql' || result.sql) {
                // NEW: Pass SQL and explanation to formatTable
                responseHTML = formatTable(
                    result.columns,
                    result.data,
                    result.query_id,
                    result.sql,
                    result.explanation,
                    result.insights
                );
            } else {
                const msg = result.message || JSON.stringify(result);
                const formattedMsg = markdownToHtml(msg);
                responseHTML = `<div class="sqlatte-chat-message">${formattedMsg}</div>`;
            }

            addMessage('assistant', responseHTML);

            if (result.query_id) {
                loadHistory();
            }

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
     * INJECT STYLES - WITH SQL HIGHLIGHTING CSS!
     */
    function injectStyles() {
        if (document.getElementById('sqlatte-widget-styles')) return;

        const style = document.createElement('style');
        style.id = 'sqlatte-widget-styles';
        style.textContent = `
/* SQLatte Widget Styles - WITH SQL HIGHLIGHTING */

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

.sqlatte-widget.sqlatte-widget-bottom-right { bottom: 20px; right: 20px; }
.sqlatte-widget.sqlatte-widget-bottom-left { bottom: 20px; left: 20px; }
.sqlatte-widget.sqlatte-widget-top-right { top: 20px; right: 20px; }
.sqlatte-widget.sqlatte-widget-top-left { top: 20px; left: 20px; }

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

/* Modal */
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

.sqlatte-modal:not(.sqlatte-modal-fullscreen) {
    bottom: 80px;
    right: 20px;
    width: 650px;
    max-width: 90vw;
    height: 650px;
    max-height: 85vh;
    border-radius: 16px;
    box-shadow: 0 24px 48px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(212, 165, 116, 0.2);
    transform: scale(0.9) translateY(20px);
}

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
}

.sqlatte-modal.sqlatte-modal-open {
    opacity: 1;
    pointer-events: all;
}

.sqlatte-modal.sqlatte-modal-open:not(.sqlatte-modal-fullscreen) {
    transform: scale(1) translateY(0);
}

.sqlatte-modal-hidden-for-chart {
    visibility: hidden !important;
    pointer-events: none !important;
}

/* Modal Header */
.sqlatte-modal-header {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    padding: 14px 20px;
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
    font-size: 16px;
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

/* Toolbar */
.sqlatte-modal-toolbar-extended {
    padding: 10px 16px;
    background: #242424;
    border-bottom: 1px solid #333;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.sqlatte-toolbar-buttons {
    display: flex;
    gap: 8px;
}

.sqlatte-toolbar-btn {
    padding: 8px 14px;
    background: #333;
    border: 1px solid #444;
    border-radius: 8px;
    color: #e0e0e0;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 6px;
}

.sqlatte-toolbar-btn:hover {
    background: #3d3d3d;
    border-color: #D4A574;
}

.sqlatte-toolbar-btn.sqlatte-toolbar-btn-active {
    background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
    border-color: #D4A574;
    color: white;
}

.sqlatte-toolbar-tables {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.sqlatte-toolbar-tables label {
    font-size: 12px;
    color: #a0a0a0;
    font-weight: 500;
}

.sqlatte-toolbar-tables select {
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

.sqlatte-toolbar-tables select:focus {
    outline: none;
    border-color: #D4A574;
}

.sqlatte-toolbar-tables small {
    font-size: 10px;
    color: #707070;
}

/* ============================================ */
/* MARKDOWN FORMATTING STYLES */
/* ============================================ */

/* Paragraphs */
.sqlatte-paragraph {
    margin: 0 0 12px 0;
    line-height: 1.6;
    color: #e0e0e0;
}

.sqlatte-paragraph:last-child {
    margin-bottom: 0;
}

/* Headings */
.sqlatte-h1 {
    font-size: 20px;
    font-weight: 700;
    color: #D4A574;
    margin: 16px 0 12px 0;
    border-bottom: 2px solid #333;
    padding-bottom: 8px;
}

.sqlatte-h2 {
    font-size: 18px;
    font-weight: 600;
    color: #D4A574;
    margin: 14px 0 10px 0;
}

.sqlatte-h3 {
    font-size: 16px;
    font-weight: 600;
    color: #A67C52;
    margin: 12px 0 8px 0;
}

/* Bold & Italic */
.sqlatte-message-content strong {
    color: #D4A574;
    font-weight: 600;
}

.sqlatte-message-content em {
    color: #A67C52;
    font-style: italic;
}

/* Inline Code */
.sqlatte-inline-code {
    background: #1a1a1a;
    color: #66d9ef;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    border: 1px solid #333;
}

/* Code Blocks */
.sqlatte-code-block {
    background: #0a0a0a;
    border: 1px solid #333;
    border-radius: 6px;
    padding: 12px;
    margin: 12px 0;
    overflow-x: auto;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.5;
}

.sqlatte-code-block code {
    color: #e0e0e0;
}

/* Lists */
.sqlatte-ul {
    margin: 8px 0 12px 20px;
    padding: 0;
    color: #e0e0e0;
    list-style-type: disc;
}

.sqlatte-li {
    margin: 4px 0;
    line-height: 1.5;
}

.sqlatte-ul .sqlatte-li::marker {
    color: #D4A574;
}

/* Links */
.sqlatte-link {
    color: #4a9eff;
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: all 0.2s;
}

.sqlatte-link:hover {
    color: #6bb3ff;
    border-bottom-color: #4a9eff;
}

/* Blockquotes */
.sqlatte-blockquote {
    border-left: 3px solid #D4A574;
    padding-left: 12px;
    margin: 12px 0;
    color: #a0a0a0;
    font-style: italic;
    background: rgba(212, 165, 116, 0.05);
    padding: 8px 12px;
    border-radius: 0 4px 4px 0;
}

/* Chat Message Container - Enhanced */
.sqlatte-chat-message {
    word-wrap: break-word;
    overflow-wrap: break-word;
}

.sqlatte-chat-message p:last-child,
.sqlatte-chat-message .sqlatte-paragraph:last-child {
    margin-bottom: 0;
}

.sqlatte-chat-message code {
    word-break: break-all;
}

/* Message Content Improvements */
.sqlatte-message-content {
    max-width: 85%;
    background: #242424;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid #333;
    font-size: 13px;
    line-height: 1.6;
    color: #e0e0e0;
    word-wrap: break-word;
}

.sqlatte-message-content > *:first-child {
    margin-top: 0;
}

.sqlatte-message-content > *:last-child {
    margin-bottom: 0;
}

/* Slide-out Panels */
.sqlatte-slide-panel {
    position: absolute;
    top: 105px;
    left: 0;
    width: 300px;
    max-width: 80%;
    height: calc(100% - 165px);
    background: #1f1f1f;
    border-right: 1px solid #333;
    transform: translateX(-100%);
    transition: transform 0.3s ease;
    z-index: 9999;
    display: flex;
    flex-direction: column;
    box-shadow: 4px 0 12px rgba(0, 0, 0, 0.3);
}

.sqlatte-slide-panel.sqlatte-panel-open {
    transform: translateX(0);
}

.sqlatte-panel-header {
    padding: 14px 16px;
    background: #2a2a2a;
    border-bottom: 1px solid #333;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.sqlatte-panel-header h4 {
    margin: 0;
    font-size: 14px;
    color: #D4A574;
}

.sqlatte-panel-header button {
    width: 24px;
    height: 24px;
    border-radius: 4px;
    background: transparent;
    border: none;
    color: #a0a0a0;
    cursor: pointer;
    font-size: 14px;
}

.sqlatte-panel-header button:hover {
    background: #333;
    color: white;
}

.sqlatte-panel-content {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
}

.sqlatte-panel-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #707070;
    text-align: center;
}

.sqlatte-panel-empty span {
    font-size: 36px;
    margin-bottom: 12px;
    opacity: 0.5;
}

.sqlatte-panel-empty p {
    margin: 0 0 4px 0;
    font-size: 14px;
}

.sqlatte-panel-empty small {
    font-size: 11px;
}

.sqlatte-panel-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

/* History Item */
.sqlatte-history-item {
    background: #2a2a2a;
    border: 1px solid #333;
    border-radius: 8px;
    padding: 10px 12px;
    transition: all 0.2s;
}

.sqlatte-history-item:hover {
    border-color: #D4A574;
    background: #333;
}

.sqlatte-history-item.sqlatte-history-item-favorite {
    border-color: #f59e0b;
    background: rgba(245, 158, 11, 0.1);
}

.sqlatte-history-item-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 6px;
}

.sqlatte-history-question {
    font-size: 13px;
    color: #e0e0e0;
    cursor: pointer;
    flex: 1;
    word-break: break-word;
}

.sqlatte-history-question:hover {
    color: #D4A574;
}

.sqlatte-history-time {
    font-size: 10px;
    color: #707070;
    white-space: nowrap;
    margin-left: 8px;
}

.sqlatte-history-item-meta {
    display: flex;
    gap: 10px;
    font-size: 10px;
    color: #888;
    margin-bottom: 8px;
}

.sqlatte-history-item-actions {
    display: flex;
    gap: 4px;
}

.sqlatte-history-item-actions button {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: #1a1a1a;
    border: 1px solid #333;
    cursor: pointer;
    font-size: 12px;
    transition: all 0.2s;
}

.sqlatte-history-item-actions button:hover {
    background: #333;
    border-color: #D4A574;
}

/* Favorite Item */
.sqlatte-favorite-item {
    background: linear-gradient(135deg, rgba(245, 158, 11, 0.1) 0%, rgba(217, 119, 6, 0.1) 100%);
    border: 1px solid #f59e0b;
    border-radius: 8px;
    padding: 10px 12px;
    transition: all 0.2s;
}

.sqlatte-favorite-item:hover {
    background: rgba(245, 158, 11, 0.2);
}

.sqlatte-favorite-item-header {
    margin-bottom: 6px;
}

.sqlatte-favorite-name {
    font-size: 13px;
    color: #f59e0b;
    cursor: pointer;
    font-weight: 500;
}

.sqlatte-favorite-name:hover {
    color: #fbbf24;
}

.sqlatte-favorite-item-meta {
    font-size: 10px;
    color: #888;
    margin-bottom: 8px;
}

.sqlatte-favorite-item-actions {
    display: flex;
    gap: 4px;
}

.sqlatte-favorite-item-actions button {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid #f59e0b;
    cursor: pointer;
    font-size: 12px;
    transition: all 0.2s;
}

.sqlatte-favorite-item-actions button:hover {
    background: rgba(245, 158, 11, 0.3);
}

/* Modal Body */
.sqlatte-modal-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

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
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
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

/* ============================================ */
/* SQL SYNTAX HIGHLIGHTING - NEW! */
/* ============================================ */

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
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}

.sqlatte-sql-toolbar button:hover {
    background: #3d3d3d;
    border-color: #D4A574;
    transform: translateY(-1px);
}

.sqlatte-sql-code {
    max-height: 350px;
    overflow-x: auto;
    overflow-y: auto;
    background: #000;
}

.sqlatte-sql-code pre {
    margin: 0;
    padding: 14px 16px;
    font-family: 'Courier New', 'Consolas', 'Monaco', 'Menlo', monospace;
    font-size: 12px;
    line-height: 1.7;
    color: #e0e0e0;
}

.sqlatte-sql-code code {
    font-family: inherit;
    font-size: inherit;
    background: none;
    padding: 0;
}

/* Syntax Token Colors */
.sql-keyword {
    color: #66d9ef;
    font-weight: bold;
}

.sql-function {
    color: #fd971f;
    font-weight: 600;
}

.sql-string {
    color: #a6e22e;
}

.sql-number {
    color: #ae81ff;
}

.sql-comment {
    color: #75715e;
    font-style: italic;
    opacity: 0.8;
}

.sqlatte-sql-code::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

.sqlatte-sql-code::-webkit-scrollbar-track {
    background: #1a1a1a;
}

.sqlatte-sql-code::-webkit-scrollbar-thumb {
    background: #333;
    border-radius: 4px;
}

.sqlatte-sql-code::-webkit-scrollbar-thumb:hover {
    background: #444;
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

.sqlatte-error {
    color: #f87171;
    font-size: 12px;
    margin: 8px 0;
    padding: 10px;
    background: rgba(248, 113, 113, 0.1);
    border-left: 3px solid #f87171;
    border-radius: 4px;
}

.sqlatte-security-warning {
    color: #f59e0b;
    font-size: 12px;
    margin: 8px 0;
    padding: 12px 14px;
    background: rgba(245, 158, 11, 0.1);
    border-left: 3px solid #f59e0b;
    border-radius: 4px;
    line-height: 1.6;
}

.sqlatte-warning-sql {
    margin-top: 8px;
    padding: 8px;
    background: rgba(0, 0, 0, 0.25);
    border-radius: 4px;
    font-size: 11px;
    font-family: monospace;
    white-space: pre-wrap;
    word-break: break-all;
    color: #fbbf24;
}

/* Results */
.sqlatte-results-container {
    margin: 12px 0;
}

.sqlatte-results-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #242424;
    border: 1px solid #333;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
}

.sqlatte-export-btn, .sqlatte-chart-btn, .sqlatte-fav-btn {
    padding: 6px 10px;
    border: none;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.3s ease;
    position: relative;
}

.sqlatte-export-btn {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
}

.sqlatte-chart-btn {
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    color: white;
}

.sqlatte-fav-btn {
    background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
    color: white;
}

.sqlatte-export-btn:hover:not(:disabled),
.sqlatte-chart-btn:hover:not(:disabled),
.sqlatte-fav-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    filter: brightness(1.1);
}

.sqlatte-export-btn:disabled,
.sqlatte-chart-btn:disabled,
.sqlatte-fav-btn:disabled {
    cursor: not-allowed;
    opacity: 0.7;
}

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
    max-height: 350px;
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

.sqlatte-results-table th {
    padding: 10px 14px;
    text-align: left;
    font-weight: 600;
    color: #D4A574;
    background: #242424;
    border-bottom: 2px solid #333;
    white-space: nowrap;
    min-width: 100px;
}

.sqlatte-results-table td {
    padding: 8px 14px;
    border-bottom: 1px solid #333;
    color: #e0e0e0;
    min-width: 100px;
    max-width: 250px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.sqlatte-results-table td:hover {
    background: rgba(212, 165, 116, 0.1);
}
/* ============================================
   INSIGHTS PANEL STYLES
   ============================================ */

.sqlatte-insights-panel {
    margin: 16px 0;
    padding: 16px;
    background: linear-gradient(135deg, rgba(212, 165, 116, 0.1) 0%, rgba(212, 165, 116, 0.05) 100%);
    border-radius: 8px;
    border: 1px solid rgba(212, 165, 116, 0.2);
    animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
    from {
        opacity: 0;
        transform: translateY(-10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.sqlatte-insights-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    font-size: 14px;
    font-weight: 600;
    color: #D4A574;
    letter-spacing: 0.5px;
}

.sqlatte-insight-card {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 10px 14px;
    margin: 8px 0;
    background: rgba(0, 0, 0, 0.3);
    border-radius: 6px;
    border-left: 3px solid #666;
    transition: all 0.2s ease;
    cursor: default;
}

.sqlatte-insight-card:hover {
    background: rgba(0, 0, 0, 0.4);
    transform: translateX(2px);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.sqlatte-insight-card.severity-info {
    border-left-color: #6b7280;
}

.sqlatte-insight-card.severity-success {
    border-left-color: #10b981;
    background: rgba(16, 185, 129, 0.05);
}

.sqlatte-insight-card.severity-warning {
    border-left-color: #f59e0b;
    background: rgba(245, 158, 11, 0.05);
}

.sqlatte-insight-icon {
    font-size: 20px;
    line-height: 1;
    flex-shrink: 0;
    margin-top: 2px;
}

.sqlatte-insight-content {
    flex: 1;
    font-size: 13px;
    color: #e5e5e5;
    line-height: 1.6;
}

/* Mobile responsive */
@media (max-width: 600px) {
    .sqlatte-insights-panel {
        padding: 12px;
        margin: 12px 0;
    }

    .sqlatte-insight-card {
        padding: 8px 12px;
        gap: 10px;
    }

    .sqlatte-insight-icon {
        font-size: 18px;
    }

    .sqlatte-insight-content {
        font-size: 12px;
    }
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
}

.sqlatte-input-area button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(212, 165, 116, 0.3);
}

.sqlatte-input-area button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
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

/* Chart Modal */
.sqlatte-chart-modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 999999999;
    opacity: 0;
    transition: opacity 0.3s;
    backdrop-filter: blur(4px);
}

.sqlatte-chart-modal.sqlatte-chart-modal-open {
    opacity: 1;
}

.sqlatte-chart-modal-content {
    background: #1a1a1a;
    border-radius: 12px;
    border: 1px solid #333;
    width: 90%;
    max-width: 900px;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
}

.sqlatte-chart-header {
    padding: 20px;
    border-bottom: 1px solid #333;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.sqlatte-chart-header h3 {
    margin: 0;
    color: #D4A574;
    font-size: 18px;
}

.sqlatte-chart-controls {
    display: flex;
    gap: 12px;
    align-items: center;
}

.sqlatte-chart-type-select {
    padding: 8px 12px;
    background: #242424;
    border: 1px solid #333;
    border-radius: 6px;
    color: #e0e0e0;
    font-size: 13px;
}

.sqlatte-chart-close {
    width: 32px;
    height: 32px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.1);
    border: none;
    color: white;
    font-size: 18px;
    cursor: pointer;
}

.sqlatte-chart-body {
    padding: 30px;
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
}

.sqlatte-chart-body canvas {
    max-width: 100%;
    max-height: 500px;
}

.sqlatte-chart-footer {
    padding: 15px 20px;
    border-top: 1px solid #333;
    color: #707070;
    font-size: 12px;
    text-align: center;
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

    .sqlatte-slide-panel {
        width: 100%;
        max-width: 100%;
    }

    .sqlatte-toolbar-tables {
        width: 100%;
    }

    .sqlatte-sql-code {
        max-height: 250px;
    }

    .sqlatte-sql-code pre {
        font-size: 11px;
        padding: 12px;
    }
}

.text-xs { font-size: 11px; }
.text-sm { font-size: 12px; }
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
    window.SQLatteWidget = {
        open: openModal,
        close: closeModal,
        minimize: minimizeModal,
        toggle: toggleModal,
        sendMessage: sendMessage,
        handleTableChange: handleTableChange,
        clearChat: clearChat,
        exportCSV: exportToCSV,
        showChart: showChart,
        closeChart: closeChart,
        filterTables: filterTables,
        _buildChart: _buildChart,
        _openConfigAgain: _openConfigAgain,
        getSessionId: function() { return sessionId; },

        // SQL Actions - NEW!
        copySQL: copySQLAction,

        // History & Favorites
        toggleHistory: toggleHistoryPanel,
        toggleFavorites: toggleFavoritesPanel,
        closeHistoryPanel: closeHistoryPanel,
        closeFavoritesPanel: closeFavoritesPanel,
        loadHistory: loadHistory,
        loadFavorites: loadFavorites,
        addToFavorites: addToFavorites,
        removeFromFavorites: removeFromFavorites,
        deleteFromHistory: deleteFromHistory,
        useQuery: useQuery,

        // Schedules
        toggleSchedules: toggleSchedulesPanel,
        closeSchedulesPanel: closeSchedulesPanel,
        loadSchedules: loadSchedules,
        openScheduleModal: openScheduleModal,
        closeScheduleModal: closeScheduleModal,
        createSchedule: createSchedule,
        runScheduleNow: runScheduleNow,
        toggleSchedule: toggleSchedule,
        deleteSchedule: deleteSchedule,

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
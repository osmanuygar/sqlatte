/**
 * SQLatte BigQuery Ops Agent - Frontend Client
 *
 * Handles operation listing, execution, and result rendering
 */

const API_BASE = '';
let currentOperation = null;
let operationsList = [];

// ═══════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    await init();
});

async function init() {
    console.log('🚀 Initializing BigQuery Ops Console...');

    try {
        await loadAgentStatus();
        await loadProjects();
        await loadOperations();
    } catch (error) {
        console.error('Initialization failed:', error);
        showError('Failed to initialize Ops Console', error.message);
    }
}

// ═══════════════════════════════════════════════════
// AGENT STATUS
// ═══════════════════════════════════════════════════

async function loadAgentStatus() {
    try {
        const response = await fetch(`${API_BASE}/ops-agent/health`);
        const data = await response.json();

        const statusHtml = `
            <div class="status-item">
                <small>Project</small>
                <div><strong>${data.project || 'N/A'}</strong></div>
            </div>
            <div class="status-item">
                <small>Region</small>
                <div><strong>${data.region || 'N/A'}</strong></div>
            </div>
            <div class="status-item">
                <small>Status</small>
                <div>
                    <span class="badge ${data.healthy ? 'bg-success' : 'bg-danger'}">
                        ${data.healthy ? '✅ Healthy' : '❌ Error'}
                    </span>
                </div>
            </div>
            ${data.datasets_accessible ? `
            <div class="status-item">
                <small>Datasets</small>
                <div><strong>${data.datasets_accessible}</strong></div>
            </div>
            ` : ''}
            <div class="status-item">
                <small style="color: #c9b9a8;">${data.message}</small>
            </div>
        `;

        document.getElementById('agent-status').innerHTML = statusHtml;

        if (!data.healthy) {
            showError('Agent Health Check Failed', data.message || 'Unknown error');
        }

    } catch (error) {
        document.getElementById('agent-status').innerHTML = `
            <div class="alert alert-danger alert-sm mb-0">
                <small>Failed to connect to ops agent</small>
            </div>
        `;
        console.error('Health check failed:', error);
    }
}

// ═══════════════════════════════════════════════════
// PROJECT MANAGEMENT
// ═══════════════════════════════════════════════════

async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/ops-agent/projects`);
        if (!response.ok) return;

        const data = await response.json();
        const projects = data.projects || [];
        if (projects.length === 0) return;
        renderProjectDropdown(projects);

    } catch (error) {
        console.warn('Could not load projects:', error.message);
    }
}

function renderProjectDropdown(projects) {
    const menu = document.getElementById('project-dropdown-menu');
    const activeLabel = document.getElementById('active-project-label');
    if (!menu || !activeLabel) return;

    const active = projects.find(p => p.active) || projects[0];
    activeLabel.textContent = `${active.project_id}  (${active.region})`;

    menu.innerHTML = projects.map(p => `
        <li>
            <a class="dropdown-item ${p.active ? 'active' : ''}"
               href="#"
               onclick="switchProject('${p.project_id}'); return false;"
               style="
                   color: ${p.active ? 'var(--bg)' : 'var(--text)'};
                   background: ${p.active ? 'var(--caramel)' : 'transparent'};
                   padding: 0.5rem 1rem;
               ">
                <strong>${p.project_id}</strong>
                <small class="d-block" style="opacity: 0.75;">${p.region}</small>
            </a>
        </li>
    `).join('');
}

async function switchProject(projectId) {
    const spinner = document.getElementById('switch-spinner');
    const btn = document.getElementById('project-dropdown-btn');
    if (spinner) spinner.style.display = 'inline-block';
    if (btn) btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/ops-agent/switch-project`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_id: projectId})
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Switch failed');
        }

        const result = await response.json();
        console.log(`✅ Switched to ${result.active_project} (${result.region})`);

        // Reload status and refresh dropdown
        await loadAgentStatus();
        await loadProjects();

        // Clear any open result
        document.getElementById('results-container').innerHTML = '';
        document.getElementById('welcome-card').style.display = 'block';
        document.getElementById('operation-card').style.display = 'none';
        document.querySelectorAll('.operation-item').forEach(i => i.classList.remove('active'));

    } catch (error) {
        showError('Project Switch Failed', error.message);
    } finally {
        if (spinner) spinner.style.display = 'none';
        if (btn) btn.disabled = false;
    }
}

// ═══════════════════════════════════════════════════
// OPERATIONS LOADING
// ═══════════════════════════════════════════════════

async function loadOperations() {
    try {
        const response = await fetch(`${API_BASE}/ops-agent/operations`);
        const data = await response.json();

        if (!data.operations || data.operations.length === 0) {
            document.getElementById('operations-list').innerHTML = `
                <div class="p-4 text-center text-muted">
                    <p>No operations available</p>
                    <small>${data.message || 'Ops agent not configured'}</small>
                </div>
            `;
            return;
        }

        operationsList = data.operations;

        // Group by category
        const grouped = {};
        operationsList.forEach(op => {
            if (!grouped[op.category]) {
                grouped[op.category] = [];
            }
            grouped[op.category].push(op);
        });

        // Render grouped operations
        let html = '';
        const categoryOrder = ['cost', 'security', 'performance', 'governance'];

        categoryOrder.forEach(category => {
            if (!grouped[category]) return;

            html += `
                <div class="list-group-item category-header">
                    <strong>${getCategoryIcon(category)} ${category.toUpperCase()}</strong>
                </div>
            `;

            grouped[category].forEach(op => {
                html += `
                    <a href="#"
                       class="list-group-item list-group-item-action operation-item"
                       onclick="selectOperation('${op.name}'); return false;"
                       data-operation="${op.name}">
                        <div class="d-flex justify-content-between align-items-start">
                            <div style="flex: 1;">
                                <div style="font-size: 0.9rem; font-weight: 500; color: #f5f5f5;">
                                    ${formatOperationName(op.name)}
                                </div>
                                <small style="color: #b0b0b0;">${op.description}</small>
                            </div>
                            <small style="color: #888;">~${op.estimated_duration_sec}s</small>
                        </div>
                    </a>
                `;
            });
        });

        document.getElementById('operations-list').innerHTML = html;
        console.log(`✅ Loaded ${operationsList.length} operations`);

    } catch (error) {
        document.getElementById('operations-list').innerHTML = `
            <div class="p-4 text-center text-danger">
                <p>Failed to load operations</p>
                <small>${error.message}</small>
            </div>
        `;
        console.error('Failed to load operations:', error);
    }
}

function getCategoryIcon(category) {
    const icons = {
        'cost': '💰',
        'security': '🔒',
        'performance': '⚡',
        'governance': '📋',
        'diagnostics': '🔍'
    };
    return icons[category] || '🔧';
}

function formatOperationName(name) {
    // Convert get_expensive_queries → Get Expensive Queries
    return name
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

// ═══════════════════════════════════════════════════
// OPERATION SELECTION
// ═══════════════════════════════════════════════════

async function selectOperation(operationName) {
    const operation = operationsList.find(op => op.name === operationName);
    if (!operation) {
        console.error('Operation not found:', operationName);
        return;
    }

    currentOperation = operation;

    // Update active state in sidebar
    document.querySelectorAll('.operation-item').forEach(item => {
        item.classList.remove('active');
    });
    document.querySelector(`[data-operation="${operationName}"]`)?.classList.add('active');

    // Hide welcome, show operation card
    document.getElementById('welcome-card').style.display = 'none';
    document.getElementById('operation-card').style.display = 'block';

    // Update operation header
    document.getElementById('op-category').textContent = operation.category;
    document.getElementById('op-name').textContent = operation.description;

    // Render parameters form if needed
    if (operation.params && operation.params.length > 0) {
        renderParamsForm(operation.params);
        document.getElementById('params-container').style.display = 'block';
    } else {
        document.getElementById('params-container').style.display = 'none';
    }

    // Clear previous results
    document.getElementById('results-container').innerHTML = '';
    document.getElementById('execution-time').textContent = '';

    console.log('Selected operation:', operationName);
}

function renderParamsForm(params) {
    let html = '<div class="row g-3">';

    params.forEach(param => {
        const required = param.required ? 'required' : '';
        const defaultVal = param.default !== undefined ? param.default : '';

        html += `
            <div class="col-md-6">
                <label for="param-${param.name}" class="form-label">
                    ${formatOperationName(param.name)}
                    ${param.required ? '<span class="text-danger">*</span>' : ''}
                </label>
                <input
                    type="${param.type === 'int' ? 'number' : 'text'}"
                    class="form-control"
                    id="param-${param.name}"
                    value="${defaultVal}"
                    ${required}
                    placeholder="${param.type}">
                <small class="text-muted">${param.type}${param.default !== undefined ? ` (default: ${param.default})` : ''}</small>
            </div>
        `;
    });

    html += '</div>';
    document.getElementById('params-form').innerHTML = html;
}

function cancelOperation() {
    currentOperation = null;
    document.getElementById('operation-card').style.display = 'none';
    document.getElementById('welcome-card').style.display = 'block';
    document.getElementById('results-container').innerHTML = '';

    // Clear active state
    document.querySelectorAll('.operation-item').forEach(item => {
        item.classList.remove('active');
    });
}

// ═══════════════════════════════════════════════════
// OPERATION EXECUTION
// ═══════════════════════════════════════════════════

async function executeOperation() {
    if (!currentOperation) {
        console.error('No operation selected');
        return;
    }

    // Collect parameters
    const params = {};
    if (currentOperation.params && currentOperation.params.length > 0) {
        for (const paramDef of currentOperation.params) {
            const input = document.getElementById(`param-${paramDef.name}`);
            if (input) {
                let value = input.value;

                // Type conversion
                if (paramDef.type === 'int') {
                    value = parseInt(value);
                    if (isNaN(value)) {
                        alert(`Invalid value for ${paramDef.name}: must be a number`);
                        return;
                    }
                }

                params[paramDef.name] = value;
            } else if (paramDef.required) {
                alert(`Required parameter missing: ${paramDef.name}`);
                return;
            }
        }
    }

    // Disable button and show loading
    const executeBtn = document.getElementById('execute-btn');
    executeBtn.disabled = true;
    executeBtn.innerHTML = '⏳ Running...';

    // Show spinner in results
    document.getElementById('results-container').innerHTML = `
        <div class="text-center p-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-3" style="color: #c9b9a8;">Executing ${currentOperation.name}...</p>
        </div>
    `;

    const startTime = Date.now();

    try {
        const response = await fetch(`${API_BASE}/ops-agent/execute`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                operation: currentOperation.name,
                params: params
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        const duration = ((Date.now() - startTime) / 1000).toFixed(2);

        document.getElementById('execution-time').textContent = `✅ Completed in ${duration}s`;

        renderResults(result);

    } catch (error) {
        const duration = ((Date.now() - startTime) / 1000).toFixed(2);
        document.getElementById('execution-time').textContent = `❌ Failed after ${duration}s`;

        showError('Operation Failed', error.message);
    } finally {
        executeBtn.disabled = false;
        executeBtn.innerHTML = '▶️ Run Operation';
    }
}

// ═══════════════════════════════════════════════════
// RESULTS RENDERING
// ═══════════════════════════════════════════════════

function renderResults(result) {
    if (!result.success) {
        showError('Operation Failed', result.error || 'Unknown error');
        return;
    }

    let html = '';

    // Summary Card
    if (result.summary) {
        html += `
            <div class="result-card">
                <div class="result-card-header" style="border-left: 3px solid var(--caramel);">
                    <span style="color: var(--caramel);">📊 Summary</span>
                </div>
                <div class="card-body">
                    <p class="lead mb-0">${escapeHtml(result.summary)}</p>
                </div>
            </div>
        `;
    }

    // Data Table
    if (result.data && result.data.length > 0) {
        html += `
            <div class="result-card">
                <div class="result-card-header">
                    📋 Results <span class="badge bg-secondary">${result.row_count} rows</span>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        ${renderDataTable(result.data)}
                    </div>
                </div>
            </div>
        `;
    } else if (result.data && result.data.length === 0) {
        html += `
            <div class="result-card">
                <div class="card-body text-center">
                    <p style="color: #c9b9a8;">No data returned</p>
                </div>
            </div>
        `;
    }

    // Visualization
    if (result.visualization) {
        html += `
            <div class="result-card">
                <div class="result-card-header">
                    📈 Visualization
                </div>
                <div class="card-body">
                    <canvas id="result-chart"></canvas>
                </div>
            </div>
        `;
    }

    // Recommendations
    if (result.recommendations && result.recommendations.length > 0) {
        html += `
            <div class="result-card">
                <div class="result-card-header bg-warning">
                    💡 Recommendations
                </div>
                <div class="card-body">
                    <ul class="mb-0">
                        ${result.recommendations.map(r => `<li>${escapeHtml(r)}</li>`).join('')}
                    </ul>
                </div>
            </div>
        `;
    }

    document.getElementById('results-container').innerHTML = html;

    // Render chart if present
    if (result.visualization) {
        setTimeout(() => {
            try {
                const ctx = document.getElementById('result-chart');
                new Chart(ctx, result.visualization);
            } catch (error) {
                console.error('Failed to render chart:', error);
            }
        }, 100);
    }
}

function renderDataTable(data) {
    if (!data || data.length === 0) {
        return '<p class="text-muted">No data</p>';
    }

    const columns = Object.keys(data[0]);

    let html = '<table class="table table-hover table-sm">';

    // Header
    html += '<thead class="table-light"><tr>';
    columns.forEach(col => {
        html += `<th>${escapeHtml(formatOperationName(col))}</th>`;
    });
    html += '</tr></thead>';

    // Body
    html += '<tbody>';
    data.forEach(row => {
        html += '<tr>';
        columns.forEach(col => {
            let value = row[col];

            // Format numbers
            if (typeof value === 'number') {
                if (Number.isInteger(value)) {
                    value = value.toLocaleString('tr-TR');
                } else {
                    value = value.toLocaleString('tr-TR', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    });
                }
            }

            // Format nulls
            if (value === null || value === undefined) {
                value = '<span class="text-muted">null</span>';
            } else {
                value = escapeHtml(String(value));
            }

            html += `<td>${value}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table>';

    return html;
}

// ═══════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════

function showError(title, message) {
    const html = `
        <div class="result-card">
            <div class="result-card-header bg-danger text-white">
                ❌ ${escapeHtml(title)}
            </div>
            <div class="card-body">
                <p class="mb-0">${escapeHtml(message)}</p>
            </div>
        </div>
    `;
    document.getElementById('results-container').innerHTML = html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// No auto-refresh - health is loaded once on page load
// User can refresh page if needed

console.log('✅ SQLatte BigQuery Ops loaded');
"""
SQLatte Demo Routes
Demo pages for standard and auth widgets
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def demo_auth_page():
    """Auth widget demo page"""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SQLatte Auth Demo ☕</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .demo-container {
            max-width: 800px;
            text-align: center;
        }

        .logo {
            width: 120px;
            height: 120px;
            margin: 0 auto 30px;
            background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 64px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }

        h1 {
            font-size: 48px;
            margin-bottom: 15px;
            background: linear-gradient(135deg, #D4A574 0%, #A67C52 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .subtitle {
            font-size: 20px;
            color: #a0a0a0;
            margin-bottom: 40px;
        }

        .info-box {
            background: rgba(212, 165, 116, 0.1);
            border: 1px solid rgba(212, 165, 116, 0.3);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            text-align: left;
        }

        .info-box h3 {
            color: #D4A574;
            margin-bottom: 12px;
            font-size: 18px;
        }

        .info-box ul {
            list-style: none;
            padding: 0;
        }

        .info-box li {
            padding: 8px 0;
            font-size: 14px;
            color: #c0c0c0;
        }

        .info-box li:before {
            content: "✓ ";
            color: #10b981;
            font-weight: bold;
            margin-right: 8px;
        }

        .hint {
            margin-top: 30px;
            font-size: 16px;
            color: #D4A574;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }

        .badge-pointer {
            position: fixed;
            bottom: 90px;
            right: 90px;
            font-size: 48px;
            animation: point 1.5s infinite;
            pointer-events: none;
            z-index: 999998;
        }

        @keyframes point {
            0%, 100% { transform: translate(0, 0); }
            50% { transform: translate(10px, 10px); }
        }

        .status {
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(16, 185, 129, 0.2);
            border: 1px solid #10b981;
            padding: 12px 20px;
            border-radius: 8px;
            color: #10b981;
            font-size: 13px;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }

        .links {
            margin-top: 30px;
            padding: 20px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            border: 1px solid #333;
        }

        .links a {
            color: #D4A574;
            text-decoration: none;
            margin: 0 15px;
            font-size: 14px;
        }

        .links a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="status">🔐 Auth Plugin Active</div>

    <div class="demo-container">
        <div class="logo">☕</div>

        <h1>SQLatte Auth Demo</h1>
        <p class="subtitle">Login-Based Database Widget</p>

        <div class="info-box">
            <h3>🔐 How to Test</h3>
            <ul>
                <li>Click the ☕ badge in bottom-right corner</li>
                <li>Login modal will appear</li>
                <li>Enter your database credentials</li>
                <li>Select tables and start querying!</li>
            </ul>
        </div>

        <div class="info-box">
            <h3>🗄️ Supported Databases</h3>
            <ul>
                <li><strong>Trino:</strong> host, port, user, password, catalog, schema, http_scheme</li>
                <li><strong>PostgreSQL:</strong> host, port, database, user, password, schema</li>
                <li><strong>MySQL:</strong> host, port, database, user, password</li>
            </ul>
        </div>

        <div class="info-box">
            <h3>✨ Features</h3>
            <ul>
                <li>Per-user database connections (isolated sessions)</li>
                <li>Conversation memory & query history</li>
                <li>SQL syntax highlighting</li>
                <li>Chart visualization & CSV export</li>
                <li>Favorites & recent queries</li>
            </ul>
        </div>

        <p class="hint">👇 Click the badge below 👇</p>
        <div class="badge-pointer">👉</div>

        <div class="links">
            <a href="/">← Back to Home</a>
            <a href="/admin">Admin Panel</a>
            <a href="/health">Health Check</a>
        </div>
    </div>

    <!-- SQLatte Auth Widget -->
    <script src="/static/js/sqlatte-badge-auth.js"></script>

    <script>
        window.addEventListener('load', () => {
            console.log('🎯 SQLatte Auth Demo Page Loaded');

            // Check if widget loaded successfully
            setTimeout(() => {
                if (window.SQLatteAuthWidget) {
                    console.log('✅ Auth Widget API available');
                    console.log('📦 Methods:', Object.keys(window.SQLatteAuthWidget));
                } else {
                    console.error('❌ Auth widget failed to load!');
                    console.error('Check: frontend/static/js/sqlatte-badge-auth.js');

                    // Show error to user
                    const status = document.querySelector('.status');
                    status.style.background = 'rgba(239, 68, 68, 0.2)';
                    status.style.borderColor = '#ef4444';
                    status.style.color = '#ef4444';
                    status.textContent = '❌ Widget Load Failed';
                }
            }, 1000);
        });

        // Log any JS errors
        window.addEventListener('error', (e) => {
            console.error('Page error:', e.message);
        });
    </script>
</body>
</html>"""

    return HTMLResponse(content=html_content)


@router.get("/compare", response_class=HTMLResponse)
async def demo_compare_page():
    """Side-by-side comparison of standard vs auth widgets"""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SQLatte Widget Comparison</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 40px 20px;
        }

        .header {
            text-align: center;
            margin-bottom: 40px;
        }

        .header h1 {
            font-size: 48px;
            background: linear-gradient(135deg, #D4A574 0%, #A67C52 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 15px;
        }

        .comparison-grid {
            max-width: 1200px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
        }

        .widget-card {
            background: #242424;
            border-radius: 12px;
            padding: 30px;
            border: 1px solid #333;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        .widget-card h2 {
            color: #D4A574;
            margin-bottom: 20px;
            font-size: 24px;
        }

        .widget-card ul {
            list-style: none;
            padding: 0;
        }

        .widget-card li {
            padding: 10px 0;
            border-bottom: 1px solid #333;
            font-size: 14px;
            color: #c0c0c0;
        }

        .widget-card li:last-child {
            border-bottom: none;
        }

        .badge-demo {
            margin-top: 20px;
            padding: 20px;
            background: rgba(212, 165, 116, 0.1);
            border: 1px solid rgba(212, 165, 116, 0.3);
            border-radius: 8px;
            text-align: center;
        }

        .badge-demo p {
            font-size: 13px;
            color: #a0a0a0;
        }

        .links {
            text-align: center;
            margin-top: 40px;
        }

        .links a {
            color: #D4A574;
            text-decoration: none;
            margin: 0 15px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>SQLatte Widget Comparison ☕</h1>
        <p>Standard vs Auth-based widgets</p>
    </div>

    <div class="comparison-grid">
        <!-- Standard Widget -->
        <div class="widget-card">
            <h2>📦 Standard Widget</h2>
            <ul>
                <li><strong>Authentication:</strong> None (backend config)</li>
                <li><strong>Database:</strong> Shared connection</li>
                <li><strong>Use Case:</strong> Internal apps, single tenant</li>
                <li><strong>Configuration:</strong> config.yaml</li>
                <li><strong>Setup:</strong> 1 minute</li>
                <li><strong>Security:</strong> Backend credentials</li>
            </ul>
            <div class="badge-demo">
                <p>Badge position: <strong>Bottom-Right</strong></p>
                <p>Loads from: <code>/static/js/sqlatte-badge.js</code></p>
            </div>
        </div>

        <!-- Auth Widget -->
        <div class="widget-card">
            <h2>🔐 Auth Widget</h2>
            <ul>
                <li><strong>Authentication:</strong> Login required</li>
                <li><strong>Database:</strong> Per-user connection</li>
                <li><strong>Use Case:</strong> Multi-tenant SaaS</li>
                <li><strong>Configuration:</strong> User provides credentials</li>
                <li><strong>Setup:</strong> 5 minutes (plugin)</li>
                <li><strong>Security:</strong> Session-based isolation</li>
            </ul>
            <div class="badge-demo">
                <p>Badge position: <strong>Bottom-Left</strong></p>
                <p>Loads from: <code>/static/js/sqlatte-badge-auth.js</code></p>
            </div>
        </div>
    </div>

    <div class="links">
        <a href="/">← Home</a>
        <a href="/demo">Auth Demo</a>
        <a href="/admin">Admin Panel</a>
    </div>

    <!-- Load BOTH widgets for comparison -->
    <script src="/static/js/sqlatte-badge.js"></script>
    <script src="/static/js/sqlatte-badge-auth.js"></script>

    <script>
        console.log('📊 Comparison page loaded');
        console.log('Standard widget:', window.SQLatteWidget ? '✅' : '❌');
        console.log('Auth widget:', window.SQLatteAuthWidget ? '✅' : '❌');
    </script>
</body>
</html>"""

    return HTMLResponse(content=html_content)


@router.get("/test", response_class=HTMLResponse)
async def demo_test_page():
    """Minimal test page for debugging"""
    html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>SQLatte Auth Widget Test</title>
    <style>
        body {
            font-family: monospace;
            background: #1a1a1a;
            color: #e0e0e0;
            padding: 40px;
        }
        .log {
            background: #000;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #333;
            margin-top: 20px;
        }
        .log pre {
            margin: 0;
            font-size: 12px;
            line-height: 1.6;
        }
        .success { color: #10b981; }
        .error { color: #ef4444; }
        .info { color: #3b82f6; }
    </style>
</head>
<body>
    <h1>🧪 SQLatte Auth Widget Test</h1>
    <p>Minimal test page for debugging</p>

    <div class="log" id="log">
        <pre>Initializing...</pre>
    </div>

    <script>
        const logEl = document.getElementById('log').querySelector('pre');

        function log(msg, type = 'info') {
            const timestamp = new Date().toLocaleTimeString();
            const className = type;
            logEl.innerHTML += `\n<span class="${className}">[${timestamp}] ${msg}</span>`;
        }

        log('Loading auth widget...', 'info');

        const script = document.createElement('script');
        script.src = '/static/js/sqlatte-badge-auth.js';

        script.onerror = () => {
            log('❌ Failed to load sqlatte-badge-auth.js', 'error');
            log('Check: frontend/static/js/sqlatte-badge-auth.js', 'error');
        };

        script.onload = () => {
            log('✅ Script loaded successfully', 'success');

            setTimeout(() => {
                if (window.SQLatteAuthWidget) {
                    log('✅ SQLatteAuthWidget API available', 'success');
                    log('Methods: ' + Object.keys(window.SQLatteAuthWidget).join(', '), 'info');
                } else {
                    log('❌ SQLatteAuthWidget not found in window', 'error');
                }
            }, 500);
        };

        document.head.appendChild(script);
    </script>
</body>
</html>"""

    return HTMLResponse(content=html_content)
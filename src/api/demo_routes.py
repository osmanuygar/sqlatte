"""
SQLatte Demo Routes
Demo pages for standard and auth widgets
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

# Get frontend directory
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def demo_auth_page():
    """
    Auth widget demo page
    Serves frontend/demo.html if exists, otherwise embedded HTML
    """
    demo_file = FRONTEND_DIR / "demo.html"

    # If demo.html exists, serve it
    if demo_file.exists():
        logger.info(f"✅ Serving demo.html from: {demo_file}")
        return FileResponse(demo_file)

    # Otherwise serve embedded HTML (backward compatibility)
    logger.warning("⚠️ demo.html not found, serving embedded HTML")
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
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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
            background: white;
            padding: 48px;
            border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            color: #333;
        }

        h1 {
            font-size: 48px;
            margin-bottom: 15px;
            background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .subtitle {
            font-size: 20px;
            color: #666;
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
            color: #8B6F47;
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
            color: #666;
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
            color: #8B6F47;
            font-weight: 600;
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
        }


        /* CRITICAL: Hide badge when modal is open */
        .sqlatte-auth-modal.sqlatte-auth-modal-open ~ .sqlatte-widget .sqlatte-badge-btn {
            display: none !important;
        }



</style>
</head>
<body>
    <div class="status">🔐 Auth Plugin Active</div>

    <div class="demo-container">
        <h1>☕ SQLatte Auth Demo</h1>
        <p class="subtitle">Login-Based Database Widget</p>

        <div class="info-box">
            <h3>🔐 How to Test</h3>
            <ul>
                <li>Click the ☕ badge in bottom-right corner</li>
                <li>Login modal will appear fullscreen</li>
                <li>Enter your database credentials</li>
                <li>Select tables and start querying!</li>
            </ul>
        </div>

        <div class="info-box">
            <h3>✨ Features</h3>
            <ul>
                <li>Fullscreen modal interface</li>
                <li>Chart visualization with metric selector</li>
                <li>SQL syntax highlighting</li>
                <li>Query history & favorites</li>
                <li>CSV export</li>
                <li>Session management</li>
            </ul>
        </div>

        <p class="hint">👉 Look for the ☕ badge in the bottom-right corner!</p>
    </div>

    <!-- Load Auth Widget -->
    <script src="/static/js/sqlatte-badge-auth.js"></script>

    <script>
        window.addEventListener('load', () => {
            if (window.SQLatteAuthWidget) {
                window.SQLatteAuthWidget.configure({
                    position: 'bottom-right',
                    fullscreen: true,
                    apiBase: window.location.origin
                });
                console.log('✅ SQLatte Auth Widget configured');



            } else {
                console.error('❌ SQLatte Auth Widget not loaded');
            }
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@router.get("/fullscreen", response_class=HTMLResponse)
async def demo_fullscreen_page():
    """
    Fullscreen demo page with nuclear fullscreen enforcement
    """
    demo_file = FRONTEND_DIR / "demo-fullscreen.html"

    # Try to serve demo-fullscreen.html
    if demo_file.exists():
        logger.info(f"✅ Serving demo-fullscreen.html from: {demo_file}")
        return FileResponse(demo_file)

    # Fallback to main demo
    logger.warning("⚠️ demo-fullscreen.html not found, using main demo")
    return await demo_auth_page()


@router.get("/standard", response_class=HTMLResponse)
async def demo_standard_page():
    """
    Standard (non-auth) widget demo page
    """
    demo_file = FRONTEND_DIR / "demo-standard.html"

    if demo_file.exists():
        logger.info(f"✅ Serving demo-standard.html from: {demo_file}")
        return FileResponse(demo_file)

    # Fallback to auth demo
    logger.warning("⚠️ demo-standard.html not found, using auth demo")
    return await demo_auth_page()


@router.get("/comparison", response_class=HTMLResponse)
async def demo_comparison_page():
    """
    Side-by-side comparison of auth vs standard widgets
    """
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
            padding: 40px;
        }

        .header {
            text-align: center;
            margin-bottom: 40px;
        }

        h1 {
            font-size: 48px;
            background: linear-gradient(135deg, #8B6F47 0%, #A67C52 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .comparison-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
            max-width: 1400px;
            margin: 0 auto;
        }

        .widget-card {
            background: rgba(212, 165, 116, 0.1);
            border: 1px solid rgba(212, 165, 116, 0.3);
            border-radius: 12px;
            padding: 30px;
        }

        .widget-card h2 {
            color: #D4A574;
            margin-bottom: 20px;
        }

        .widget-card ul {
            list-style: none;
            padding: 0;
        }

        .widget-card li {
            padding: 8px 0;
            font-size: 14px;
        }

        .widget-card li strong {
            color: #D4A574;
        }

        .badge-demo {
            margin-top: 20px;
            padding: 15px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
        }

        .links {
            text-align: center;
            margin-top: 40px;
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
    <div class="header">
        <h1>☕ SQLatte Widget Comparison</h1>
        <p style="color: #a0a0a0; margin-top: 10px;">Choose the right widget for your use case</p>
    </div>

    <div class="comparison-grid">
        <!-- Standard Widget -->
        <div class="widget-card">
            <h2>📊 Standard Widget</h2>
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
        <a href="/demo/standard">Standard Demo</a>
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
</html>
    """
    return HTMLResponse(content=html_content)


@router.get("/health")
async def demo_health():
    """
    Health check for demo routes and files
    """
    demo_html = FRONTEND_DIR / "demo.html"
    widget_js = FRONTEND_DIR / "static" / "js" / "sqlatte-badge-auth.js"

    return {
        "status": "healthy" if demo_html.exists() and widget_js.exists() else "degraded",
        "files": {
            "demo_html": {
                "path": str(demo_html),
                "exists": demo_html.exists(),
                "size": demo_html.stat().st_size if demo_html.exists() else 0
            },
            "widget_js": {
                "path": str(widget_js),
                "exists": widget_js.exists(),
                "size": widget_js.stat().st_size if widget_js.exists() else 0
            }
        },
        "frontend_dir": str(FRONTEND_DIR),
        "endpoints": [
            "/demo",
            "/demo/fullscreen",
            "/demo/standard",
            "/demo/comparison",
            "/demo/health"
        ]
    }


logger.info("✅ Demo routes registered")
#!/bin/bash
# SQLatte Startup Script
# Makes it super easy to start SQLatte

echo "============================================================"
echo "☕ SQLatte - Starting..."
echo "============================================================"
echo ""

# Check if in correct directory
if [ ! -f "run.py" ]; then
    echo "❌ Error: run.py not found!"
    echo ""
    echo "Make sure you're in the sqlatte directory:"
    echo "  cd sqlatte/"
    echo ""
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found!"
    echo ""
    echo "Creating .env from template..."
    cp .env.example .env
    echo "✅ Created .env"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env and add your API keys:"
    echo "  nano .env"
    echo ""
    echo "Press Enter after editing .env..."
    read
fi

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
fi

# Activate venv
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install/upgrade packages
echo "📦 Installing dependencies..."
pip install -q -r requirements.txt --upgrade

echo ""
echo "🧪 Running validation tests..."
echo ""

# Test imports
python validate_imports.py
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Validation failed! Fix errors above."
    exit 1
fi

echo ""
echo "🔑 Testing API key..."
echo ""

# Test API key
python test_api_key.py
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ API key test failed!"
    echo ""
    echo "Fix your .env file:"
    echo "  nano .env"
    echo ""
    echo "Then run this script again."
    exit 1
fi

echo ""
echo "============================================================"
echo "✅ All checks passed! Starting SQLatte..."
echo "============================================================"
echo ""
echo "🌐 Opening browser in 3 seconds..."
echo ""

# Start server in background
python run.py &
SERVER_PID=$!

# Wait a bit
sleep 3

# Try to open browser
if command -v xdg-open > /dev/null; then
    xdg-open http://localhost:8000
elif command -v open > /dev/null; then
    open http://localhost:8000
else
    echo "📱 Open manually: http://localhost:8000"
fi

echo ""
echo "============================================================"
echo "✅ SQLatte is running!"
echo "============================================================"
echo ""
echo "🌐 URL: http://localhost:8000"
echo "🛑 Stop: Press Ctrl+C"
echo ""
echo "============================================================"

# Wait for user to stop
wait $SERVER_PID

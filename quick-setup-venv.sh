#!/bin/bash
# Quick venv setup for Raspberry Pi (fast alternative to setup-pi.sh)
# Use this if you already have system packages installed
# Assumes python3-picamera2, libjpeg-dev, etc. are already installed

set -e

echo "⚡ Quick venv setup (assumes system packages already installed)..."
echo ""

# Remove old venv
if [ -d venv ]; then
    echo "🗑️  Removing old venv..."
    rm -rf venv
fi

# Create venv with system packages
echo "🔧 Creating Python virtual environment with system packages..."
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Install pip tools
echo "📦 Upgrading pip, setuptools, wheel..."
pip install --upgrade pip setuptools wheel

# Install Python dependencies (pre-built wheels only, no compilation)
echo "📚 Installing Python dependencies..."
pip install --only-binary :all: -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Next steps:"
echo ""
echo "1. Create a .env file with your configuration:"
echo "   cp .env.example .env"
echo "   nano .env  # Edit with your AUTH_API_URL and SECRET_KEY"
echo ""
echo "2. Start the Python backend:"
echo "   source venv/bin/activate"
echo "   python3 app.py"
echo ""
echo "   The MJPEG stream will be available at:"
echo "   http://<pi-ip>:5000/stream"
echo ""

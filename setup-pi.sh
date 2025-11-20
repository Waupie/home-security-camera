#!/bin/bash
# Setup script for Raspberry Pi camera streaming app
# Run this once to install all dependencies

set -e

echo "🚀 Setting up Pi Camera Streaming App..."
echo ""

# Update system packages
echo "📦 Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Python and dependencies
echo "🐍 Installing Python and build tools..."
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    python3-venv \
    build-essential \
    git

# Install system packages for Picamera2 and image libraries
echo "📷 Installing camera and image libraries..."
sudo apt-get install -y \
    python3-picamera2 \
    python3-libcamera \
    libjpeg-dev \
    zlib1g-dev \
    libatlas-base-dev \
    libjasper-dev \
    libharfbuzz0b \
    libwebp6 \
    libtiff6 \
    libjasper1 \
    libopenjp2-7 || echo "⚠️  Some optional packages not found, continuing..."

# Install Node.js (for the frontend, optional)
echo "📱 Installing Node.js..."
sudo apt-get install -y nodejs npm

# Create virtual environment (optional but recommended)
echo "🔧 Creating Python virtual environment..."
cd "$(dirname "$0")"
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "📚 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

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
echo "3. In another terminal, start the Node.js frontend:"
echo "   cd node-app"
echo "   npm install  # (first time only)"
echo "   npm start"
echo ""
echo "4. Open your browser to http://localhost:9000"
echo ""

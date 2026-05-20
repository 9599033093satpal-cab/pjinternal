#!/bin/bash
# OCR Agent Web App - Quick Start Script

echo "=================================="
echo "🚀 OCR Agent Web App"
echo "=================================="
echo ""

# Check if virtual environment exists
if [ ! -d "ocr_env" ]; then
    echo "⚠️  Virtual environment not found!"
    echo "Run ./install.sh first to install dependencies."
    exit 1
fi

# Activate virtual environment
source ocr_env/bin/activate

# Create necessary directories
mkdir -p uploads outputs

# Check if Flask is installed
python -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "📦 Installing web dependencies..."
    pip install -r requirements_webapp.txt
fi

echo ""
echo "✅ Starting OCR Agent Web Application..."
echo ""
echo "🌐 Open in browser: http://localhost:5000"
echo ""
echo "Features:"
echo "  • Drag & drop PDF upload"
echo "  • Real-time progress tracking"
echo "  • Multiple OCR engines"
echo "  • Beautiful UI"
echo ""
echo "Press Ctrl+C to stop"
echo "=================================="
echo ""

# Start the Flask app
python app.py

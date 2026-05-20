#!/bin/bash
# Enterprise OCR Agent - Installation Script
# Automates system and Python dependency installation

set -e  # Exit on error

echo "=================================="
echo "OCR Agent Installation Script"
echo "=================================="
echo ""

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    echo "Error: Unsupported OS. This script supports Linux and macOS only."
    echo "For Windows, please follow manual installation in README.md"
    exit 1
fi

echo "Detected OS: $OS"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Python
echo "Checking Python installation..."
if ! command_exists python3; then
    echo "Error: Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "✓ Python $PYTHON_VERSION found"
echo ""

# Install system dependencies
echo "Installing system dependencies..."
if [ "$OS" == "linux" ]; then
    echo "This will run: sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-eng"
    read -p "Continue? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo apt-get update
        sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-eng
        
        # Optional: Install Hindi language data
        read -p "Install Hindi OCR support? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            sudo apt-get install -y tesseract-ocr-hin
            echo "✓ Hindi language data installed"
        fi
    fi
elif [ "$OS" == "macos" ]; then
    if ! command_exists brew; then
        echo "Error: Homebrew is not installed. Please install it from https://brew.sh"
        exit 1
    fi
    
    echo "This will run: brew install poppler tesseract tesseract-lang"
    read -p "Continue? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        brew install poppler tesseract tesseract-lang
    fi
fi

# Verify installations
echo ""
echo "Verifying system dependencies..."

if command_exists tesseract; then
    TESSERACT_VERSION=$(tesseract --version | head -1)
    echo "✓ $TESSERACT_VERSION"
else
    echo "✗ Tesseract not found"
    exit 1
fi

if command_exists pdftoppm; then
    echo "✓ Poppler-utils installed"
else
    echo "✗ Poppler-utils not found"
    exit 1
fi

echo ""

# Create virtual environment
echo "Creating Python virtual environment..."
if [ -d "ocr_env" ]; then
    echo "Virtual environment already exists. Skipping creation."
else
    python3 -m venv ocr_env
    echo "✓ Virtual environment created: ocr_env"
fi

echo ""

# Activate virtual environment and install dependencies
echo "Installing Python dependencies..."
source ocr_env/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✓ Python dependencies installed"

# Check for GPU support
echo ""
echo "Checking for GPU support..."
if command_exists nvidia-smi; then
    echo "✓ NVIDIA GPU detected"
    read -p "Install GPU-accelerated PyTorch for faster OCR? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
        echo "✓ GPU support installed"
    fi
else
    echo "No NVIDIA GPU detected. Using CPU mode (still fast with parallel processing)."
fi

# Test installation
echo ""
echo "Testing installation..."
python3 -c "import pytesseract; import pdf2image; import pypdf; print('✓ All core libraries imported successfully')"

echo ""
echo "=================================="
echo "Installation Complete! 🎉"
echo "=================================="
echo ""
echo "To activate the environment:"
echo "  source ocr_env/bin/activate"
echo ""
echo "To run the OCR agent:"
echo "  python ocr_agent.py your_document.pdf"
echo ""
echo "For more options:"
echo "  python ocr_agent.py --help"
echo ""
echo "Check README.md for detailed usage examples."
echo "=================================="

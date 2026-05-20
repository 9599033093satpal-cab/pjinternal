# 🚀 OCR Agent Web Application

**Beautiful web interface for enterprise-grade PDF OCR processing**

A modern, responsive web application with drag-and-drop PDF upload, real-time progress tracking, and multiple OCR engine support.

![OCR Agent](https://img.shields.io/badge/OCR-Agent-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![Python](https://img.shields.io/badge/Python-3.8+-yellow)

## ✨ Features

### 🎨 Beautiful Modern UI
- **Drag & Drop Upload**: Simply drag PDFs into the browser
- **Real-time Progress**: Watch OCR processing in real-time
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Animated Interface**: Smooth transitions and animations
- **Dark/Light Gradient**: Eye-catching purple gradient theme

### 🚀 Powerful Processing
- **Multiple OCR Engines**: Choose from Tesseract, EasyOCR, or PaddleOCR
- **100+ Languages**: Support for English, Hindi, Chinese, Arabic, and more
- **Parallel Processing**: Multi-core support for faster processing
- **Large File Support**: Handle massive 2000+ page PDFs (1GB+ files)
- **HITL Dashboard**: Built-in Human-in-the-Loop validation for high-accuracy production needs
- **Page-Synced Editing**: Neural JSON editor that filters fields by the current PDF page
- **Full-Page PDF Viewer**: Professional document viewer with zoom, pan, and page sync
- **Auto File Splitting**: Automatically split output into multiple files

### 📊 Job Management
- **Job History**: View all past OCR jobs
- **Live Statistics**: See total jobs, completed, and processing
- **Download Results**: Easy one-click download of OCR results and verified JSON
- **Job Tracking**: Track progress of multiple PDFs simultaneously
- **Audit Logs**: Automatic accuracy scoring and field-level correction logs

## 🎯 Screenshots

### Upload Interface
- Drag and drop area with visual feedback
- File size and type validation
- Beautiful upload animations

### Configuration Panel
- OCR engine selection
- Language picker
- Quality (DPI) settings
- Worker count control
- Output file splitting options

### Progress Tracking
- Real-time progress bar
- Current page indicator
- Processing status updates
- Download buttons for completed jobs

## 🔧 Installation

### Quick Start (3 Steps)

```bash
# 1. Install dependencies
./install.sh

# 2. Install web dependencies
source ocr_env/bin/activate
pip install -r requirements_webapp.txt

# 3. Run the web app
./run_webapp.sh
```

### Manual Installation

```bash
# Create virtual environment
python -m venv ocr_env
source ocr_env/bin/activate

# Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-eng

# Install Python packages
pip install -r requirements_webapp.txt

# Create directories
mkdir -p uploads outputs templates

# Run the app
python app.py
```

## 🌐 Usage

### Starting the Server

```bash
# Option 1: Using the run script
./run_webapp.sh

# Option 2: Direct Python
python app.py
```

The app will start on `http://localhost:5000`

### Using the Web Interface

1. **Upload PDF**
   - Drag and drop your PDF file onto the upload area
   - Or click to browse and select a file
   - Max file size: 1GB (Optimized for 2000+ pages)

2. **Configure Processing**
   - Select OCR engine (Tesseract recommended for speed)
   - Choose document language
   - Set quality (DPI): 300 is standard, 600 for high quality
   - Configure parallel workers (4 recommended)
   - Choose how many output files to create

3. **Start Processing**
   - Click "Start Processing" button
   - Watch real-time progress
   - View statistics and current page

4. **Download Results**
   - Once completed, download buttons appear
   - Click to download each output file
   - Files are in plain text format

### API Endpoints

The web app also provides a REST API:

#### Upload PDF
```bash
curl -X POST http://localhost:5000/api/upload \
  -F "file=@document.pdf" \
  -F "engine=tesseract" \
  -F "language=eng" \
  -F "dpi=300" \
  -F "workers=4" \
  -F "split_files=2"
```

#### Check Job Status
```bash
curl http://localhost:5000/api/status/{job_id}
```

#### List All Jobs
```bash
curl http://localhost:5000/api/jobs
```

#### Download Result
```bash
curl http://localhost:5000/api/download/{job_id}/{filename} -o output.txt
```

#### Health Check
```bash
curl http://localhost:5000/health
```

## 🏗️ Architecture

```
ocr-agent-webapp/
├── app.py                    # Flask application & API
├── ocr_agent.py             # OCR processing engine
├── templates/
│   └── index.html           # Web interface (HTML/CSS/JS)
├── uploads/                 # Uploaded PDFs (auto-created)
├── outputs/                 # OCR results (auto-created)
├── requirements_webapp.txt  # Python dependencies
└── run_webapp.sh           # Quick start script
```

## 📋 API Reference

### Job Object Structure

```json
{
  "job_id": "uuid",
  "filename": "document.pdf",
  "status": "processing",
  "progress": 45,
  "current_page": 23,
  "total_pages": 50,
  "output_files": ["ocr_output_part1.txt"],
  "error": null,
  "started_at": "2024-01-15T14:30:00",
  "completed_at": null,
  "engine": "tesseract",
  "language": "eng",
  "dpi": 300
}
```

### Status Values
- `queued`: Job is waiting to start
- `processing`: Currently processing
- `completed`: Successfully finished
- `failed`: Processing failed with error

## 🎨 Customization

### Changing Theme Colors

Edit the CSS variables in `templates/index.html`:

```css
:root {
    --primary: #6366f1;        /* Primary color */
    --primary-dark: #4f46e5;   /* Primary dark */
    --success: #10b981;        /* Success green */
    --warning: #f59e0b;        /* Warning orange */
    --danger: #ef4444;         /* Error red */
}
```

### Changing Port

Edit `app.py`:

```python
app.run(host='0.0.0.0', port=8080, debug=True)
```

### Adding Languages

Edit the language list in `templates/index.html`:

```html
<option value="your_lang_code">Your Language</option>
```

## 🐳 Docker Deployment

### Build Image
```bash
docker build -t ocr-webapp .
```

### Run Container
```bash
docker run -p 5000:5000 -v $(pwd)/uploads:/app/uploads -v $(pwd)/outputs:/app/outputs ocr-webapp
```

### Docker Compose
```bash
docker-compose up
```

## 🔒 Production Deployment

### Security Considerations

1. **Change Secret Key**
   ```python
   app.config['SECRET_KEY'] = 'your-secure-random-key-here'
   ```

2. **Disable Debug Mode**
   ```python
   app.run(host='0.0.0.0', port=5000, debug=False)
   ```

3. **Add Authentication**
   - Implement user login
   - Add API key validation
   - Use HTTPS/SSL

4. **File Size Limits**
   - Already set to 500MB
   - Adjust based on your needs

5. **Rate Limiting**
   - Add Flask-Limiter
   - Prevent abuse

### NGINX Configuration

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    client_max_body_size 1024M;
}
```

### Systemd Service

```ini
[Unit]
Description=OCR Agent Web App
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/ocr-agent
Environment="PATH=/path/to/ocr-agent/ocr_env/bin"
ExecStart=/path/to/ocr-agent/ocr_env/bin/python app.py

[Install]
WantedBy=multi-user.target
```

## 📊 Performance

### Benchmarks (Intel i7, 8 cores)

| File Size | Pages | Engine | DPI | Time | Workers |
|-----------|-------|--------|-----|------|---------|
| 50MB | 100 | Tesseract | 300 | 9 min | 4 |
| 150MB | 300 | Tesseract | 300 | 27 min | 4 |
| 250MB | 500 | Tesseract | 300 | 45 min | 4 |
| 50MB | 100 | EasyOCR | 300 | 15 min | 4 |
| 150MB | 300 | EasyOCR (GPU) | 300 | 12 min | 4 |

### Optimization Tips

1. **Increase Workers**: Match CPU cores
2. **Lower DPI**: 200 DPI for faster processing
3. **Use GPU**: 5-10x faster with EasyOCR
4. **Batch Processing**: Process multiple files
5. **Cache Results**: Avoid reprocessing

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Find and kill process using port 5000
lsof -ti:5000 | xargs kill -9

# Or use different port
python app.py --port 8080
```

### File Upload Fails
- Check file size (max 1GB)
- Verify file is a PDF
- Check uploads/ directory permissions

### Processing Hangs
- Check available RAM
- Reduce workers count
- Lower DPI setting

### No Output Files
- Check outputs/ directory permissions
- View logs in terminal
- Check job status via API

## 📝 Development

### Running in Development Mode

```bash
export FLASK_ENV=development
export FLASK_DEBUG=1
python app.py
```

### Adding New Features

1. **New OCR Engine**: Edit `ocr_agent.py`
2. **UI Changes**: Edit `templates/index.html`
3. **API Endpoints**: Edit `app.py`

### Testing

```bash
# Test file upload
curl -X POST http://localhost:5000/api/upload -F "file=@test.pdf"

# Test health check
curl http://localhost:5000/health
```

## 🤝 Integration Examples

### JavaScript Fetch API
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('engine', 'tesseract');

const response = await fetch('/api/upload', {
    method: 'POST',
    body: formData
});

const data = await response.json();
console.log('Job ID:', data.job_id);
```

### Python Requests
```python
import requests

files = {'file': open('document.pdf', 'rb')}
data = {'engine': 'tesseract', 'language': 'eng'}

response = requests.post('http://localhost:5000/api/upload', 
                        files=files, data=data)
job = response.json()
```

## 📄 License

MIT License - Free for commercial and personal use

## 🙏 Credits

- **Flask**: Web framework
- **Tesseract**: OCR engine by Google
- **EasyOCR**: Deep learning OCR
- **PaddleOCR**: Baidu's OCR toolkit

## 📞 Support

For issues or questions:
1. Check troubleshooting section
2. Review terminal logs
3. Test API endpoints
4. Check browser console

---

**Made with ❤️ for easy OCR processing**

**Quick Commands:**
```bash
./install.sh          # Install dependencies
./run_webapp.sh       # Start web app
python app.py         # Direct start
```

**Access:** http://localhost:5000

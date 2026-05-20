"""
Direct test: Run the full OCR pipeline manually for a given PDF 
to confirm route_page extracts text correctly in the threading context.
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ocr_router import route_page

# Find the most recent upload
uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
pdf_files = [f for f in os.listdir(uploads_dir) if f.endswith('.pdf')]
if not pdf_files:
    print("No PDF files found in uploads/")
    exit(1)

# Sort by modified time, most recent first
pdf_files.sort(key=lambda f: os.path.getmtime(os.path.join(uploads_dir, f)), reverse=True)
pdf_path = os.path.join(uploads_dir, pdf_files[0])
print(f"Testing with: {pdf_path}")

# Test page 0
result = route_page(pdf_path=pdf_path, page_index=0, dpi=200, language='eng')
print(f"\nEngine: {result['engine']}")
print(f"Is Blank: {result['is_blank']}")
print(f"Confidence: {result['confidence']}")
print(f"Quality: {result['quality_score']}")
print(f"Text Length: {len(result['text'])} chars")
print(f"\nText Preview:\n{result['text'][:500]}")

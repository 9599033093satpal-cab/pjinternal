import sys
import os
sys.path.append(os.getcwd())

from ocr_router import route_page
import json

pdf_path = 'uploads/e18d6274-a2e7-4c9f-803d-9410453d0c1a_Parul_Vats_1.pdf'
if not os.path.exists(pdf_path):
    # Try another ID
    print(f"File not found at {pdf_path}")
    exit(1)

result = route_page(pdf_path=pdf_path, page_index=0, dpi=200)
print(json.dumps(result, indent=2))

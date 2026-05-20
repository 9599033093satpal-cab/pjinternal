import pypdfium2 as pdfium
import os

pdf_path = 'uploads/19f3816f-1d91-4641-8873-bc6af57a1b49_Parul_Vats_1.pdf'
if not os.path.exists(pdf_path):
    # Try another ID if that one failed
    print(f"File not found at {pdf_path}")
    exit(1)

doc = pdfium.PdfDocument(pdf_path)
page = doc[0]
bitmap = page.render(scale=2)
pil_image = bitmap.to_pil()
pil_image.save('scratch/test_page.jpg')
print("Saved scratch/test_page.jpg")
doc.close()

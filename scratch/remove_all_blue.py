import os
import re

templates_dir = r"c:\Users\dell\Downloads\OCR\ocr-agent-complete\templates"
css_file = r"c:\Users\dell\Downloads\OCR\ocr-agent-complete\static\css\index.css"

replacements = [
    (r"#3b82f6", "#e8a020"),
    (r"#3B82F6", "#e8a020"),
    (r"#60a5fa", "#f5c842"),
    (r"#60A5FA", "#f5c842"),
    (r"59,\s*130,\s*246", "232,160,32"),
    (r"#93c5fd", "#f5c842"),
    (r"#818cf8", "#e8a020")
]

def apply_replacements(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    for old, new in replacements:
        content = re.sub(old, new, content, flags=re.IGNORECASE)
        
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Updated {filepath}")

# Process CSS
apply_replacements(css_file)

# Process HTMLs
for filename in os.listdir(templates_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(templates_dir, filename)
        apply_replacements(filepath)

print("Done removing blue colors.")

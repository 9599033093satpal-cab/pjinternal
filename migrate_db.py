
import sqlite3
import os

db_path = 'instance/aether_ocr.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check existing columns
    cursor.execute("PRAGMA table_info(ocr_jobs)")
    columns = [column[1] for column in cursor.fetchall()]
    
    # Add missing columns for Enterprise logic
    missing_columns = {
        'document_id': 'TEXT',
        'template_id': 'INTEGER',
        'accuracy_score': 'FLOAT',
        'is_locked': 'INTEGER DEFAULT 0',
        'audit_summary': 'TEXT DEFAULT "{}"'
    }
    
    for col, col_type in missing_columns.items():
        if col not in columns:
            print(f"Adding column {col} to ocr_jobs...")
            cursor.execute(f"ALTER TABLE ocr_jobs ADD COLUMN {col} {col_type}")
    
    conn.commit()
    conn.close()
    print("Database migration completed successfully!")
else:
    print("Database file not found. It will be created by Flask with the correct schema.")

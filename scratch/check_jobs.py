import sqlite3
import os

db_path = 'instance/aether_ocr.db'
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("--- Recent Jobs (All Statuses) ---")
try:
    cursor.execute("SELECT job_id, filename, status, error, started_at FROM ocr_jobs ORDER BY started_at DESC LIMIT 10")
    rows = cursor.fetchall()
    for row in rows:
        print(f"ID: {row[0]} | File: {row[1]} | Status: {row[2]} | Start: {row[4]}")
        if row[3]:
            print(f"  Error: {row[3]}")
except Exception as e:
    print(f"Error querying ocr_jobs: {e}")

conn.close()

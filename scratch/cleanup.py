import os
import sqlite3
import shutil

WORKSPACE = r"c:\Users\dell\Downloads\OCR\ocr-agent-complete"
db_path = os.path.join(WORKSPACE, "instance", "aether_ocr.db")

print("Cleaning up test job test_job_12345...")

# Delete database row
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ocr_jobs WHERE job_id = 'test_job_12345';")
    conn.commit()
    conn.close()
    print("Database record deleted.")
except Exception as e:
    print("Failed to delete database record:", e)

# Delete outputs directory
output_dir = os.path.join(WORKSPACE, "outputs", "test_job_12345")
if os.path.exists(output_dir):
    shutil.rmtree(output_dir)
    print("Outputs directory deleted.")
else:
    print("Outputs directory not found.")

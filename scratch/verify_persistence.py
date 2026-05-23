import os
import sys
import json
import sqlite3
from pathlib import Path

# Inject virtual env site-packages
WORKSPACE = r"c:\Users\dell\Downloads\OCR\ocr-agent-complete"
venv_site = os.path.join(WORKSPACE, "venv12", "Lib", "site-packages")
if os.path.exists(venv_site):
    sys.path.insert(0, venv_site)

# Set up paths
db_path = os.path.join(WORKSPACE, "instance", "aether_ocr.db")

print("Checking SQLite database at:", db_path)
if not os.path.exists(db_path):
    print("Database file does not exist!")
    sys.exit(1)

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get list of tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables in database:", [t[0] for t in tables])

# Check for jobs
cursor.execute("SELECT job_id, filename, status, accuracy_score FROM ocr_jobs LIMIT 10;")
jobs = cursor.fetchall()
print("\nRecent jobs in DB:")
for job in jobs:
    print(f"Job ID: {job[0]}, Filename: {job[1]}, Status: {job[2]}, Accuracy: {job[3]}")

if not jobs:
    print("No jobs found in DB. Creating a dummy job for testing...")
    # Let's insert a dummy job
    dummy_job_id = "test_job_12345"
    dummy_filename = "dummy_agreement.pdf"
    cursor.execute(
        "INSERT INTO ocr_jobs (job_id, filename, status, started_at) VALUES (?, ?, ?, datetime('now'));",
        (dummy_job_id, dummy_filename, "processing")
    )
    conn.commit()
    print(f"Dummy job inserted with ID: {dummy_job_id}")
    jobs = [(dummy_job_id, dummy_filename, "processing", None)]

test_job_id = jobs[0][0]
test_filename = jobs[0][1]
pdf_stem = Path(test_filename).stem

# Create dummy output directory and dummy output files
output_dir = os.path.join(WORKSPACE, "outputs", test_job_id)
os.makedirs(output_dir, exist_ok=True)

# Write dummy semantic.json
dummy_semantic = {
    "document_bundle": {
        "primary_type": "leave_license_agreement",
        "page_range": [1, 3]
    },
    "pages": [
        {
            "page_number": 1,
            "extracted_fields": {
                "licensor": "John Doe Original",
                "licensee": "Jane Smith Original",
                "rent": "10000"
            }
        }
    ],
    "master_case": {
        "parties": {
            "licensor": "John Doe Original",
            "licensee": "Jane Smith Original"
        },
        "financials": {
            "rent": "10000"
        }
    }
}

semantic_path = os.path.join(output_dir, f"{pdf_stem}_semantic.json")
master_path = os.path.join(output_dir, "master_case.json")

with open(semantic_path, 'w', encoding='utf-8') as f:
    json.dump(dummy_semantic, f, indent=2)
with open(master_path, 'w', encoding='utf-8') as f:
    json.dump(dummy_semantic, f, indent=2)

print(f"\nWritten dummy semantic files to {output_dir}")

# Close DB connection for now
conn.close()

# We will run tests against the Flask local server using requests
import requests
server_url = "http://localhost:5000"

print(f"\nSending GET request to {server_url}/api/semantic_data/{test_job_id}")
try:
    r = requests.get(f"{server_url}/api/semantic_data/{test_job_id}")
    print("GET Status Code:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print("GET Data matches original semantic file:", data["master_case"]["parties"]["licensor"] == "John Doe Original")
except Exception as e:
    print("GET Request failed:", e)

# Let's POST updated data
updated_data = json.loads(json.dumps(dummy_semantic))
updated_data["master_case"]["parties"]["licensor"] = "John Doe Verified"
updated_data["pages"][0]["extracted_fields"]["licensor"] = "John Doe Verified"

print(f"\nSending POST request to {server_url}/api/semantic_data/{test_job_id}")
try:
    r = requests.post(
        f"{server_url}/api/semantic_data/{test_job_id}",
        json=updated_data
    )
    print("POST Status Code:", r.status_code)
    if r.status_code == 200:
        res = r.json()
        print("POST Response:", res)
except Exception as e:
    print("POST Request failed:", e)

# Now verify on disk that master_case.json and verified files are updated
verified_path = os.path.join(output_dir, f"{pdf_stem}_verified.json")
print("\nVerifying disk files:")
print("verified_verified.json exists:", os.path.exists(verified_path))
if os.path.exists(verified_path):
    with open(verified_path, 'r', encoding='utf-8') as f:
        v_data = json.load(f)
        print("Verified data licensor value:", v_data["master_case"]["parties"]["licensor"])

print("master_case.json exists:", os.path.exists(master_path))
if os.path.exists(master_path):
    with open(master_path, 'r', encoding='utf-8') as f:
        m_data = json.load(f)
        print("Master case data licensor value on disk:", m_data["master_case"]["parties"]["licensor"])

# Verify GET request returns verified data
print(f"\nSending second GET request to verify persistence")
try:
    r = requests.get(f"{server_url}/api/semantic_data/{test_job_id}")
    print("GET Status Code:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print("GET Data returned verified licensor:", data["master_case"]["parties"]["licensor"])
except Exception as e:
    print("Second GET Request failed:", e)

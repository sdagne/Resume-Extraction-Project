# Testing Guide: Resume Extraction Enterprise Pipeline

This guide provides step-by-step instructions to verify the Enterprise Tiers (Security, OCR, Enhancement, and Persistence).

## Pre-requisites
1.  **Docker**: Ensure Docker is running.
2.  **Environment**: Verify `.env` has `DOCEX_RESUME_ENHANCE=1` and `DOCEX_RESUME_LAYOUT=1`.

---

## Step 1: Start the System
Run the following command to rebuild and start the containers:
```bash
docker-compose up --build -d
```
Check logs to ensure clean startup:
```bash
docker logs resume_extractor_app --tail 20
```

---

## Step 2: Test Tier 1 - Security & Pre-processing
We want to verify the system blocks dangerous or invalid files.

1.  **Invalid Magic-Bytes**: Create a text file, rename it to `fake.pdf`, and upload it.
    *   **Expected Result**: `400 Bad Request` with error "Invalid file type (magic-byte mismatch)".
2.  **Suspicious Content**: Upload a PDF that contains JavaScript or a `/Launch` command.
    *   **Expected Result**: `security_report` in JSON will show `suspicious: true`.

---

## Step 3: Test Tier 3 - NLP Enhancement
Verify the spaCy/Rule-based enhancement is working.

1.  **Skill Splitting**: Upload a resume where skills are a single string like `"Python, FastAPI, Docker"`.
    *   **Expected Result**: The `skills` object in the response should have these as separate items in a list.
2.  **Date Normalization**: Upload a resume with dates like `"Jan 2022"`.
    *   **Expected Result**: Look for `2022-01-01` in the `normalized_date` fields.

---

## Step 4: Test Tier 2 - Intelligent OCR (Scanned PDF)
1.  **Scanned Test**: Take a screenshot of a resume and save it as a PDF.
2.  **Upload**: Send it to `/api/v1/extract/resume`.
    *   **Expected Result**: The `source_type` in the response should be `SCANNED_PDF`. Ensure text is still extracted via PaddleOCR.

---

## Step 5: Test Tier 4 - Hybrid Persistence (Database)
1.  **Extraction**: Complete a successful extraction via the API.
2.  **Check DB**: Connect to your SQL Server and run:
    ```sql
    -- Check Legacy Track
    SELECT TOP 5 * FROM IAPL_CRM_RESUME_PROFILE ORDER BY DateCreated DESC;
    
    -- Check Normalized Track
    SELECT TOP 5 * FROM Candidates_text_to_ocr ORDER BY inserted_date DESC;
    ```
    *   **Expected Result**: Records should exist in BOTH tables.

---

## Useful Tool: Python Test Script
Create a file named `test_api.py` and run it:

```python
import requests

url = "http://localhost:8000/api/v1/extract/resume"
file_path = "path/to/your/test_resume.pdf"

with open(file_path, "rb") as f:
    response = requests.post(url, files={"file": f})

print(f"Status: {response.status_code}")
print(response.json())
```

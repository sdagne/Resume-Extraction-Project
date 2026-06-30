# tests/integration/test_upload_endpoint.py

import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


class TestUploadEndpoint:

    def test_upload_valid_pdf(self, client, mock_file_handler):
        """Test successful PDF upload."""
        with patch("app.api.routes.upload.file_handler", mock_file_handler):
            pdf_content = b"%PDF-1.4 fake pdf content for testing"
            response    = client.post(
                "/api/v1/upload/",
                files={"file": ("test_resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
            )

        assert response.status_code == 201
        data = response.json()
        assert "resume_id"         in data
        assert "status"            in data
        assert data["status"]      in ("pending", "completed")
        assert "original_filename" in data

    def test_upload_rejects_non_pdf(self, client):
        """Test that non-PDF files are rejected."""
        response = client.post(
            "/api/v1/upload/",
            files={"file": ("resume.txt", io.BytesIO(b"text content"), "text/plain")},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False

    def test_upload_rejects_oversized_file(self, client, mock_file_handler):
        """Test that files exceeding size limit are rejected."""
        with patch("app.api.routes.upload.file_handler", mock_file_handler):
            # Create fake content larger than max size
            large_content = b"x" * (11 * 1024 * 1024)  # 11MB
            response      = client.post(
                "/api/v1/upload/",
                files={"file": ("large.pdf", io.BytesIO(large_content), "application/pdf")},
            )

        assert response.status_code == 400

    def test_get_resume_status(self, client, mock_file_handler):
        """Test getting status of uploaded resume."""
        with patch("app.api.routes.upload.file_handler", mock_file_handler):
            pdf_content = b"%PDF-1.4 fake pdf content"
            upload_resp = client.post(
                "/api/v1/upload/",
                files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            )

        assert upload_resp.status_code == 201
        resume_id = upload_resp.json()["resume_id"]

        status_resp = client.get(f"/api/v1/upload/{resume_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["resume_id"] == resume_id

    def test_get_status_not_found(self, client):
        """Test 404 for non-existent resume."""
        response = client.get(
            "/api/v1/upload/00000000-0000-0000-0000-000000000000/status"
        )
        assert response.status_code == 404

    def test_list_resumes_empty(self, client):
        """Test listing resumes when none exist."""
        response = client.get("/api/v1/upload/")
        assert response.status_code == 200
        data = response.json()
        assert "items"    in data
        assert "total"    in data
        assert "page"     in data
        assert isinstance(data["items"], list)

    def test_list_resumes_pagination(self, client, mock_file_handler):
        """Test pagination of resume list."""
        response = client.get("/api/v1/upload/?page=1&page_size=5")
        assert response.status_code == 200
        data = response.json()
        assert data["page"]      == 1
        assert data["page_size"] == 5

    def test_batch_upload(self, client, mock_file_handler):
        """Test batch upload of multiple files."""
        with patch("app.api.routes.upload.file_handler", mock_file_handler):
            files = [
                ("files", (f"resume_{i}.pdf",
                           io.BytesIO(b"%PDF-1.4 content"),
                           "application/pdf"))
                for i in range(3)
            ]
            response = client.post("/api/v1/upload/batch", files=files)

        assert response.status_code == 201
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_delete_resume(self, client, mock_file_handler):
        """Test deleting a resume."""
        with patch("app.api.routes.upload.file_handler", mock_file_handler):
            pdf_content = b"%PDF-1.4 fake pdf content"
            upload_resp = client.post(
                "/api/v1/upload/",
                files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            )

        resume_id = upload_resp.json()["resume_id"]

        with patch("app.api.routes.upload.file_handler", mock_file_handler):
            del_resp = client.delete(f"/api/v1/upload/{resume_id}")

        assert del_resp.status_code == 204

    def test_get_stats(self, client):
        """Test statistics endpoint."""
        response = client.get("/api/v1/upload/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_uploaded"  in data
        assert "total_completed" in data
        assert "total_failed"    in data

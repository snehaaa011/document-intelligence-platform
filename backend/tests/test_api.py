"""
tests/test_api.py

Covers case study section 37 items 13-16: health endpoint, document
processing API, GET document, list documents. Uses TestClient with an
in-memory SQLite database (see conftest.py) and the default rule_based
extraction provider so no network access or API key is required.
"""
import io

from PIL import Image, ImageDraw


def _make_test_invoice_image() -> bytes:
    img = Image.new("RGB", (600, 400), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "TAX INVOICE", fill="black")
    draw.text((20, 60), "Invoice No. TEST/001", fill="black")
    draw.text((20, 100), "Dated 01-Jan-26", fill="black")
    draw.text((20, 300), "Total Amount Chargeable 100.00", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_health_endpoint(api_client):
    resp = api_client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert body["app_name"]


def test_process_document_invoice(api_client):
    file_bytes = _make_test_invoice_image()
    resp = api_client.post(
        "/api/v1/documents/process",
        files={"file": ("test_invoice.jpg", file_bytes, "image/jpeg")},
        data={"document_type": "invoice"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_name"] == "test_invoice.jpg"
    assert body["document_type"] == "invoice"
    assert body["processing_status"] in ("PASS", "FAILED")
    assert "processing_metadata" in body


def test_process_document_rejects_unsupported_type(api_client):
    resp = api_client.post(
        "/api/v1/documents/process",
        files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
        data={"document_type": "invoice"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processing_status"] == "FAILED"
    assert body["error"]["code"] == "FILE_VALIDATION_FAILED"


def test_get_document_after_processing(api_client):
    file_bytes = _make_test_invoice_image()
    api_client.post(
        "/api/v1/documents/process",
        files={"file": ("lookup_test.jpg", file_bytes, "image/jpeg")},
        data={"document_type": "invoice"},
    )
    resp = api_client.get("/api/v1/documents/lookup_test.jpg")
    assert resp.status_code == 200
    assert resp.json()["document_name"] == "lookup_test.jpg"


def test_get_document_not_found(api_client):
    resp = api_client.get("/api/v1/documents/does_not_exist.jpg")
    assert resp.status_code == 404


def test_list_documents(api_client):
    file_bytes = _make_test_invoice_image()
    api_client.post(
        "/api/v1/documents/process",
        files={"file": ("list_test.jpg", file_bytes, "image/jpeg")},
        data={"document_type": "invoice"},
    )
    resp = api_client.get("/api/v1/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(d["document_name"] == "list_test.jpg" for d in body["documents"])


def test_get_latest_result_when_processed_twice(api_client):
    file_bytes = _make_test_invoice_image()
    for _ in range(2):
        api_client.post(
            "/api/v1/documents/process",
            files={"file": ("repeat.jpg", file_bytes, "image/jpeg")},
            data={"document_type": "invoice"},
        )
    resp = api_client.get("/api/v1/documents/repeat.jpg")
    assert resp.status_code == 200

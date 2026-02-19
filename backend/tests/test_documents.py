"""
Tests for admin document management:
  - Unit tests for Document CRUD (no API, direct DB)
  - Unit tests for PDF chunking (no API, direct chunker)
  - Unit tests for Qdrant service (mocked Qdrant client)
  - API integration tests via FastAPI TestClient (mocked Qdrant + agent)
  - Auth / role enforcement tests
"""

import os
import sys
import json
import uuid
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Resolve project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
CHUNKING_DIR = PROJECT_ROOT / "chunking"
SOURCES_DIR = PROJECT_ROOT / "sources"

# Add chunking dir to path so pdf_chunker can be imported
if str(CHUNKING_DIR) not in sys.path:
    sys.path.insert(0, str(CHUNKING_DIR))

# ---------------------------------------------------------------------------
# Mock heavy agentic_chatbot imports BEFORE importing backend modules.
# backend.main imports agentic_chatbot.agent which loads torch, etc.
# ---------------------------------------------------------------------------
_mock_agent_module = MagicMock()
_mock_agent_module.invoke_memory_agent = MagicMock(return_value={"output": "mocked"})
sys.modules.setdefault("agentic_chatbot", MagicMock())
sys.modules["agentic_chatbot.agent"] = _mock_agent_module
sys.modules.setdefault("agentic_chatbot.tools", MagicMock())

# Use a test-only SQLite database
os.environ["DATABASE_URL"] = "sqlite:///test_messages.db"
os.environ["QDRANT_URL"] = "http://localhost:6333"

# Now safe to import backend modules
from backend import models, crud, schemas, auth  # noqa: E402
from backend.main import app  # noqa: E402

# Pre-import pdf_chunker so it can be used in qdrant tests (avoids module-level issues)
from pdf_chunker import PDFSectionChunker, Payload  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_DB_PATH = PROJECT_ROOT / "test_messages.db"


@pytest.fixture(autouse=True)
def fresh_db():
    """Create a fresh database for every test, tearing down afterwards."""
    TEST_DB_PATH.unlink(missing_ok=True)
    # Reset engines so they pick up the fresh file
    models.DATABASE_URL = "sqlite:///test_messages.db"
    models.ENGINE = models.get_engine()
    crud.ENGINE = models.ENGINE
    models.init_db()
    yield
    TEST_DB_PATH.unlink(missing_ok=True)


@pytest.fixture
def admin_user():
    """Create and return an admin user."""
    user = crud.get_or_create_user({
        "email": "admin@iitd.ac.in",
        "name": "Admin User",
        "picture": None,
    })
    from sqlmodel import Session
    with Session(models.ENGINE) as sess:
        db_user = sess.get(models.User, user.id)
        db_user.role = "admin"
        sess.add(db_user)
        sess.commit()
        sess.refresh(db_user)
        return db_user


@pytest.fixture
def regular_user():
    """Create and return a regular (non-admin) user."""
    return crud.get_or_create_user({
        "email": "student@iitd.ac.in",
        "name": "Regular Student",
        "picture": None,
    })


@pytest.fixture
def admin_token(admin_user):
    return auth.create_access_token({"sub": str(admin_user.id)})


@pytest.fixture
def user_token(regular_user):
    return auth.create_access_token({"sub": str(regular_user.id)})


@pytest.fixture
def sample_pdf_path():
    """Return a path to a small real PDF from sources/ (or generate one)."""
    pdf = SOURCES_DIR / "ocs_timeline.pdf"
    if pdf.exists():
        return str(pdf)
    # Fallback: create a tiny PDF with PyMuPDF
    import fitz
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Test document content for chunking.\n" * 20)
    doc.save(tmp.name)
    doc.close()
    tmp.close()
    return tmp.name


@pytest.fixture
def tmp_uploads_dir(tmp_path):
    """Override UPLOADS_DIR to a temp directory so tests don't pollute the project."""
    import backend.main as main_mod
    original = main_mod.UPLOADS_DIR
    main_mod.UPLOADS_DIR = tmp_path
    yield tmp_path
    main_mod.UPLOADS_DIR = original


def _make_pdf_bytes():
    """Create a minimal valid PDF in memory using PyMuPDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Unit test document content.\n" * 10)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ===========================================================================
#  1. UNIT TESTS — Document CRUD (direct DB, no API)
# ===========================================================================

class TestDocumentCRUD:

    def test_create_document(self, admin_user):
        doc = crud.create_document(
            filename="abc123_test.pdf",
            original_name="test.pdf",
            description="A test document",
            file_size=1024,
            chunk_count=10,
            uploaded_by=int(admin_user.id),
        )
        assert doc.id is not None
        assert doc.original_name == "test.pdf"
        assert doc.description == "A test document"
        assert doc.file_size == 1024
        assert doc.chunk_count == 10
        assert doc.uploaded_by == admin_user.id

    def test_list_documents_empty(self):
        assert crud.list_documents() == []

    def test_list_documents_ordering(self, admin_user):
        crud.create_document("f1.pdf", "file1.pdf", "desc1", 100, 5, int(admin_user.id))
        crud.create_document("f2.pdf", "file2.pdf", "desc2", 200, 8, int(admin_user.id))
        docs = crud.list_documents()
        assert len(docs) == 2
        # Newest first
        assert docs[0].original_name == "file2.pdf"

    def test_get_document(self, admin_user):
        doc = crud.create_document("f.pdf", "f.pdf", "d", 50, 2, int(admin_user.id))
        fetched = crud.get_document(int(doc.id))
        assert fetched is not None
        assert fetched.id == doc.id

    def test_get_document_not_found(self):
        assert crud.get_document(9999) is None

    def test_delete_document(self, admin_user):
        doc = crud.create_document("f.pdf", "f.pdf", "d", 50, 2, int(admin_user.id))
        crud.delete_document(int(doc.id))
        assert crud.get_document(int(doc.id)) is None

    def test_delete_nonexistent_is_noop(self):
        crud.delete_document(9999)  # should not raise


# ===========================================================================
#  2. UNIT TESTS — PDF Chunking (direct, no API)
# ===========================================================================

class TestPDFChunking:

    def test_chunk_real_pdf(self, sample_pdf_path):
        chunker = PDFSectionChunker()
        payloads = chunker.process_pdf(sample_pdf_path)
        assert len(payloads) > 0

        first = payloads[0]
        assert hasattr(first, "content")
        assert hasattr(first, "metadata")
        assert isinstance(first.content, str)
        assert len(first.content) > 0

    def test_chunk_metadata_keys(self, sample_pdf_path):
        chunker = PDFSectionChunker()
        payloads = chunker.process_pdf(sample_pdf_path)
        for p in payloads[:5]:
            assert "type" in p.metadata
            assert p.metadata["type"] in ("text", "table_row")

    def test_chunk_size_limit(self, sample_pdf_path):
        chunker = PDFSectionChunker(chunk_size=300, chunk_overlap=50)
        payloads = chunker.process_pdf(sample_pdf_path)
        text_chunks = [p for p in payloads if p.metadata.get("type") == "text"]
        for p in text_chunks:
            assert len(p.content) <= 600, f"Chunk too large ({len(p.content)} chars)"

    def test_invalid_pdf_raises(self):
        chunker = PDFSectionChunker()
        with pytest.raises(Exception):
            chunker.process_pdf("/nonexistent/path.pdf")


# ===========================================================================
#  3. UNIT TESTS — Qdrant Service (mocked client)
# ===========================================================================

class TestQdrantService:

    @pytest.fixture(autouse=True)
    def mock_qdrant(self):
        from backend import qdrant_service

        self.mock_client = MagicMock()
        self.mock_model = MagicMock()
        self.mock_model.encode.return_value = MagicMock(
            tolist=MagicMock(return_value=[0.1] * 384)
        )
        mock_coll = MagicMock()
        mock_coll.name = "documents"
        self.mock_client.get_collections.return_value = MagicMock(collections=[mock_coll])

        qdrant_service._client = self.mock_client
        qdrant_service._model = self.mock_model
        yield
        qdrant_service._client = None
        qdrant_service._model = None

    def test_ensure_collection_already_exists(self):
        from backend import qdrant_service
        qdrant_service.ensure_collection()
        self.mock_client.create_collection.assert_not_called()

    def test_ensure_collection_creates_when_missing(self):
        from backend import qdrant_service
        self.mock_client.get_collections.return_value = MagicMock(collections=[])
        qdrant_service.ensure_collection()
        self.mock_client.create_collection.assert_called_once()

    def test_upsert_chunks(self):
        from backend import qdrant_service

        payloads = [
            Payload(content="Hello world", metadata={"page": 1}),
            Payload(content="Second chunk", metadata={"page": 2}),
        ]
        count = qdrant_service.upsert_chunks(
            file_id=42, file_name="test.pdf", description="Test doc",
            upload_date="2026-02-19T10:00:00", payloads=payloads,
        )

        assert count == 2
        assert self.mock_model.encode.call_count == 2
        self.mock_client.upsert.assert_called_once()

        points = self.mock_client.upsert.call_args.kwargs.get("points")
        assert len(points) == 2
        assert points[0].payload["metadata"]["file_id"] == 42
        assert points[0].payload["metadata"]["page"] == 1

    def test_upsert_batching(self):
        from backend import qdrant_service

        payloads = [Payload(content=f"chunk {i}", metadata={}) for i in range(250)]
        qdrant_service.upsert_chunks(
            file_id=1, file_name="big.pdf", description="",
            upload_date="2026-01-01", payloads=payloads, batch_size=100,
        )
        assert self.mock_client.upsert.call_count == 3  # 100+100+50

    def test_delete_by_file_id(self):
        from backend import qdrant_service
        qdrant_service.delete_by_file_id(42)
        self.mock_client.delete.assert_called_once()
        assert self.mock_client.delete.call_args.kwargs["collection_name"] == "documents"


# ===========================================================================
#  4. API INTEGRATION TESTS — via FastAPI TestClient
# ===========================================================================

class TestAdminDocumentAPI:

    @pytest.fixture(autouse=True)
    def mock_qdrant_for_api(self):
        with patch("backend.qdrant_service.upsert_chunks", return_value=5) as m_up, \
             patch("backend.qdrant_service.delete_by_file_id") as m_del, \
             patch("backend.qdrant_service.ensure_collection"):
            self.mock_upsert = m_up
            self.mock_delete = m_del
            yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        return TestClient(app)

    # ---- Upload ----

    def test_upload_document_as_admin(self, client, admin_token, tmp_uploads_dir):
        pdf_bytes = _make_pdf_bytes()
        resp = client.post(
            "/admin/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
            files={"file": ("test_upload.pdf", pdf_bytes, "application/pdf")},
            data={"description": "Test upload description"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["document"]["original_name"] == "test_upload.pdf"
        assert body["document"]["description"] == "Test upload description"
        assert body["document"]["chunk_count"] > 0
        assert "Successfully uploaded" in body["message"]

    def test_upload_non_pdf_rejected(self, client, admin_token, tmp_uploads_dir):
        resp = client.post(
            "/admin/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
            files={"file": ("notes.txt", b"plain text", "text/plain")},
            data={"description": "Not a PDF"},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"]

    def test_upload_requires_admin(self, client, user_token, tmp_uploads_dir):
        pdf_bytes = _make_pdf_bytes()
        resp = client.post(
            "/admin/documents",
            headers={"Authorization": f"Bearer {user_token}"},
            files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
            data={"description": "Should fail"},
        )
        assert resp.status_code == 403

    def test_upload_requires_auth(self, client, tmp_uploads_dir):
        resp = client.post(
            "/admin/documents",
            files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")},
        )
        # FastAPI HTTPBearer returns 403 when credentials are missing
        assert resp.status_code in (401, 403)

    # ---- List ----

    def test_list_documents_empty(self, client, admin_token):
        resp = client.get(
            "/admin/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_documents_after_upload(self, client, admin_token, tmp_uploads_dir):
        pdf_bytes = _make_pdf_bytes()
        client.post(
            "/admin/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
            files={"file": ("doc1.pdf", pdf_bytes, "application/pdf")},
            data={"description": "First"},
        )
        client.post(
            "/admin/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
            files={"file": ("doc2.pdf", pdf_bytes, "application/pdf")},
            data={"description": "Second"},
        )
        resp = client.get(
            "/admin/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_requires_admin(self, client, user_token):
        resp = client.get(
            "/admin/documents",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    # ---- Get single ----

    def test_get_document(self, client, admin_token, admin_user):
        doc = crud.create_document("f.pdf", "myfile.pdf", "desc", 100, 3, int(admin_user.id))
        resp = client.get(
            f"/admin/documents/{doc.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["original_name"] == "myfile.pdf"

    def test_get_document_not_found(self, client, admin_token):
        resp = client.get(
            "/admin/documents/9999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    # ---- Delete ----

    def test_delete_document(self, client, admin_token, admin_user, tmp_uploads_dir):
        fake_file = tmp_uploads_dir / "stored.pdf"
        fake_file.write_bytes(b"fake pdf content")
        doc = crud.create_document("stored.pdf", "original.pdf", "desc", 100, 3, int(admin_user.id))

        resp = client.delete(
            f"/admin/documents/{doc.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204
        assert crud.get_document(int(doc.id)) is None
        assert not fake_file.exists()
        self.mock_delete.assert_called_once_with(int(doc.id))

    def test_delete_not_found(self, client, admin_token):
        resp = client.delete(
            "/admin/documents/9999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_delete_requires_admin(self, client, user_token, admin_user):
        doc = crud.create_document("f.pdf", "f.pdf", "d", 50, 2, int(admin_user.id))
        resp = client.delete(
            f"/admin/documents/{doc.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


# ===========================================================================
#  5. AUTH & ROLE TESTS
# ===========================================================================

class TestAuthRoles:

    def test_new_user_defaults_to_user_role(self, regular_user):
        assert regular_user.role == "user"

    def test_admin_user_has_admin_role(self, admin_user):
        assert admin_user.role == "admin"

    def test_get_current_admin_rejects_regular_user(self, user_token):
        from fastapi import HTTPException as FastHTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=user_token)
        user = auth.get_current_user(creds)
        with pytest.raises(FastHTTPException) as exc:
            auth.get_current_admin(user)
        assert exc.value.status_code == 403

    def test_get_current_admin_allows_admin(self, admin_token):
        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=admin_token)
        user = auth.get_current_user(creds)
        result = auth.get_current_admin(user)
        assert result.role == "admin"

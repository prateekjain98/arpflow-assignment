"""Test suite for the UNFI RA Classification Pipeline.

Scenarios:
  1. Happy Path — 1 Valid RA + Noise
  2. Multiple RAs — Must Error
  3. Corrupted RA — Missing Headers
  4. All Noise — No RA Found
  5. Three RA Variants — Independent Processing
  6. RA + Noise Permutations — Order Independence
"""

import io
import pathlib
import random
import pytest
from fastapi.testclient import TestClient
from src.main import app
import fitz  # pymupdf

client = TestClient(app)


def _load_file(path: pathlib.Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


_FILES_DIR = pathlib.Path(__file__).parent.parent / "files"
RA_MAIN = _FILES_DIR / "remittance advice" / "256199_01222025_WESTACH.pdf"
RA_SMALL = _FILES_DIR / "remittance advice" / "256199_01222025_WESTACH (1).pdf"
RA_VARIANT = _FILES_DIR / "remittance advice" / "256199_01222025_WESTACH (2).pdf"
NOISE1 = _FILES_DIR / "noise" / "financial_document_1.pdf"
NOISE2 = _FILES_DIR / "noise" / "file-sample_150kB.pdf"
NOISE3 = _FILES_DIR / "noise" / "Sample-Accounting-Income-Statement-PDF-File.pdf"
NOISE4 = _FILES_DIR / "noise" / "financial_document_2.pdf"
NOISE5 = _FILES_DIR / "noise" / "financial_document_3.pdf"
NOISE6 = _FILES_DIR / "noise" / "Sample-Financial-Statements-1.pdf"


class TestHappyPath:
    """Test 1: 1 Valid RA + noise → HTTP 200, 30 classifications."""

    def test_happy_path(self):
        ra = _load_file(RA_MAIN)
        noise = _load_file(NOISE1)
        resp = client.post(
            "/classify",
            files=[
                ("files", ("WESTACH.pdf", io.BytesIO(ra), "application/pdf")),
                ("files", ("noise.pdf", io.BytesIO(noise), "application/pdf")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VALID_RA"
        assert data["ra_document"] == "WESTACH.pdf"
        assert data["total_line_items"] == 30
        assert data["summary"]["total_items"] == 30
        assert data["summary"]["categories"]["Fairshare"] == 30
        # Noise document should be ignored (not in response)
        assert all(item["category"] == "Fairshare" for item in data["classifications"])


class TestMultipleRas:
    """Test 2: Two valid RAs → HTTP 400 with specific message."""

    def test_multiple_ras_error(self):
        ra1 = _load_file(RA_MAIN)
        ra2 = _load_file(RA_SMALL)
        resp = client.post(
            "/classify",
            files=[
                ("files", ("WESTACH.pdf", io.BytesIO(ra1), "application/pdf")),
                ("files", ("WESTACH (1).pdf", io.BytesIO(ra2), "application/pdf")),
            ],
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "Multiple valid RA documents found (2)" in detail
        assert "Expected exactly 1 per email batch" in detail


class TestCorruptedRa:
    """Test 3: PDF with company name + prefixes but missing structural headers."""

    def test_corrupted_ra(self):
        # Build a minimal PDF that looks like an RA but lacks ADVICE DATE
        doc = fitz.open()
        page = doc.new_page()
        text = (
            "United Natural Foods West, Inc.\n"
            "INVOICE DATE INVOICE NUMBER DESCRIPTION GROSS AMOUNT DISCOUNT AMOUNT NET AMOUNT\n"
            "09/13/2025 WFMAUG2558031ISEWBB -$4,642.04 $0.00 -$4,642.04\n"
        )
        page.insert_text((72, 72), text)
        pdf_bytes = doc.write()
        doc.close()

        resp = client.post(
            "/classify",
            files=[
                ("files", ("corrupted.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ],
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "CORRUPTED_RA" in detail


class TestAllNoise:
    """Test 4: Batch with only noise documents → HTTP 400."""

    def test_all_noise(self):
        n1 = _load_file(NOISE1)
        n2 = _load_file(NOISE2)
        resp = client.post(
            "/classify",
            files=[
                ("files", ("lorem.pdf", io.BytesIO(n1), "application/pdf")),
                ("files", ("accounting.pdf", io.BytesIO(n2), "application/pdf")),
            ],
        )
        assert resp.status_code == 400
        assert "No valid RA document found in batch" in resp.json()["detail"]


class TestAllVariants:
    """Test 5: Three RA variants processed independently → all HTTP 200."""

    @pytest.mark.parametrize(
        "path,expected_count",
        [
            (RA_MAIN, 30),
            (RA_SMALL, 2),
            (RA_VARIANT, 10),
        ],
    )
    def test_variant(self, path: str, expected_count: int):
        content = _load_file(path)
        resp = client.post(
            "/classify",
            files=[
                ("files", ("ra.pdf", io.BytesIO(content), "application/pdf")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VALID_RA"
        assert data["total_line_items"] == expected_count


class TestRaWithNoisePermutations:
    """Test 6: 1 RA + noise files in random order → always finds the RA correctly."""

    @pytest.mark.parametrize(
        "ra_path,expected_count,ra_name",
        [
            (RA_MAIN, 30, "WESTACH.pdf"),
            (RA_SMALL, 2, "WESTACH_SMALL.pdf"),
            (RA_VARIANT, 10, "WESTACH_VARIANT.pdf"),
        ],
    )
    def test_ra_first_then_noise(self, ra_path, expected_count, ra_name):
        """RA appears first in the file list."""
        ra = _load_file(ra_path)
        noise = _load_file(NOISE1)
        resp = client.post(
            "/classify",
            files=[
                ("files", (ra_name, io.BytesIO(ra), "application/pdf")),
                ("files", ("noise.pdf", io.BytesIO(noise), "application/pdf")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ra_document"] == ra_name
        assert data["total_line_items"] == expected_count

    @pytest.mark.parametrize(
        "ra_path,expected_count,ra_name",
        [
            (RA_MAIN, 30, "WESTACH.pdf"),
            (RA_SMALL, 2, "WESTACH_SMALL.pdf"),
            (RA_VARIANT, 10, "WESTACH_VARIANT.pdf"),
        ],
    )
    def test_noise_first_then_ra(self, ra_path, expected_count, ra_name):
        """Noise appears first, RA appears last."""
        ra = _load_file(ra_path)
        noise = _load_file(NOISE1)
        resp = client.post(
            "/classify",
            files=[
                ("files", ("noise.pdf", io.BytesIO(noise), "application/pdf")),
                ("files", (ra_name, io.BytesIO(ra), "application/pdf")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ra_document"] == ra_name
        assert data["total_line_items"] == expected_count

    @pytest.mark.parametrize(
        "ra_path,expected_count,ra_name",
        [
            (RA_MAIN, 30, "WESTACH.pdf"),
            (RA_SMALL, 2, "WESTACH_SMALL.pdf"),
            (RA_VARIANT, 10, "WESTACH_VARIANT.pdf"),
        ],
    )
    def test_ra_in_middle_of_multiple_noise(self, ra_path, expected_count, ra_name):
        """RA is sandwiched between multiple noise documents."""
        ra = _load_file(ra_path)
        n1 = _load_file(NOISE1)
        n2 = _load_file(NOISE2)
        n3 = _load_file(NOISE3)
        resp = client.post(
            "/classify",
            files=[
                ("files", ("noise1.pdf", io.BytesIO(n1), "application/pdf")),
                ("files", ("noise2.pdf", io.BytesIO(n2), "application/pdf")),
                ("files", (ra_name, io.BytesIO(ra), "application/pdf")),
                ("files", ("noise3.pdf", io.BytesIO(n3), "application/pdf")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ra_document"] == ra_name
        assert data["total_line_items"] == expected_count

    @pytest.mark.parametrize(
        "ra_path,expected_count,ra_name",
        [
            (RA_MAIN, 30, "WESTACH.pdf"),
            (RA_SMALL, 2, "WESTACH_SMALL.pdf"),
            (RA_VARIANT, 10, "WESTACH_VARIANT.pdf"),
        ],
    )
    def test_random_permutation_with_5_noise_files(self, ra_path, expected_count, ra_name):
        """1 RA + 5 noise files in a random order (seeded for reproducibility)."""
        ra = _load_file(ra_path)
        noise_files = [
            ("noise1.pdf", _load_file(NOISE1)),
            ("noise2.pdf", _load_file(NOISE2)),
            ("noise3.pdf", _load_file(NOISE3)),
            ("noise4.pdf", _load_file(NOISE4)),
            ("noise5.pdf", _load_file(NOISE5)),
        ]

        file_list = [("ra.pdf", ra)] + noise_files
        # Seed RNG so the shuffle is deterministic across test runs
        rng = random.Random(42)
        rng.shuffle(file_list)

        resp = client.post(
            "/classify",
            files=[
                ("files", (name, io.BytesIO(content), "application/pdf"))
                for name, content in file_list
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ra_document"] == "ra.pdf"
        assert data["total_line_items"] == expected_count
        assert data["status"] == "VALID_RA"

    def test_all_noise_files_with_main_ra(self):
        """Main RA with all 6 noise files, random order."""
        ra = _load_file(RA_MAIN)
        noise_files = [
            ("noise1.pdf", _load_file(NOISE1)),
            ("noise2.pdf", _load_file(NOISE2)),
            ("noise3.pdf", _load_file(NOISE3)),
            ("noise4.pdf", _load_file(NOISE4)),
            ("noise5.pdf", _load_file(NOISE5)),
            ("noise6.pdf", _load_file(NOISE6)),
        ]

        file_list = [("main_ra.pdf", ra)] + noise_files
        rng = random.Random(123)
        rng.shuffle(file_list)

        resp = client.post(
            "/classify",
            files=[
                ("files", (name, io.BytesIO(content), "application/pdf"))
                for name, content in file_list
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ra_document"] == "main_ra.pdf"
        assert data["total_line_items"] == 30
        assert data["status"] == "VALID_RA"
        assert data["summary"]["categories"]["Fairshare"] == 30

"""Barcode normalisation, matching and retry-ladder tests (PRD FR-2)."""

from __future__ import annotations

import numpy as np
import pytest

from pdf_batch_separator.core import barcode as bc


class TestNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("EAGC-EDMS-00001", "EAGC-EDMS-00001"),
            ("  EAGC-EDMS-00001  ", "EAGC-EDMS-00001"),
            ("eagc-edms-00001", "EAGC-EDMS-00001"),
            ("EAGC EDMS 00001", "EAGCEDMS00001"),
            ("*PATCHT*", "PATCHT"),
            ("\x00PATCHT\x00", "PATCHT"),
            ("\ufeffPATCHT", "PATCHT"),
            ("patch\tt\n", "PATCHT"),
            (b"EAGC-EDMS-00001", "EAGC-EDMS-00001"),
            (None, ""),
            ("", ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert bc.normalize_barcode_value(raw) == expected

    def test_unmatched_asterisks_are_kept(self):
        # Only a *matching* outer pair is stripped.
        assert bc.normalize_barcode_value("*PATCHT") == "*PATCHT"
        assert bc.normalize_barcode_value("PATCHT*") == "PATCHT*"

    def test_lone_asterisk_is_preserved(self):
        assert bc.normalize_barcode_value("*") == "*"


class TestMatching:
    @pytest.mark.parametrize(
        "decoded,expected",
        [
            ("EAGC-EDMS-00001", "EAGC-EDMS-00001"),
            ("eagc-edms-00001", "EAGC-EDMS-00001"),
            (" EAGC-EDMS-00001 ", "EAGC-EDMS-00001"),
            ("*EAGC-EDMS-00001*", "EAGC-EDMS-00001"),
            ("PATCHT", "  patcht "),
        ],
    )
    def test_matches(self, decoded, expected):
        assert bc.barcode_value_matches(decoded, expected)

    @pytest.mark.parametrize(
        "decoded,expected",
        [
            ("EAGC-EDMS-00002", "EAGC-EDMS-00001"),
            ("EAGC-EDMS-000012", "EAGC-EDMS-00001"),
            ("PATCH", "PATCHT"),
            ("", "PATCHT"),
            (None, "PATCHT"),
            ("PATCHT", ""),
            ("PATCHT", None),
        ],
    )
    def test_does_not_match(self, decoded, expected):
        assert not bc.barcode_value_matches(decoded, expected)

    def test_matching_is_exact_not_substring(self):
        assert not bc.barcode_value_matches("PREFIX-EAGC-EDMS-00001", "EAGC-EDMS-00001")


class TestValidation:
    @pytest.mark.parametrize("value", ["EAGC-EDMS-00001", "PATCHT", "A", "Doc Sep 12"])
    def test_valid(self, value):
        ok, message = bc.validate_separator_value(value)
        assert ok, message

    @pytest.mark.parametrize(
        "value",
        ["", "   ", "x" * 129, "bad\x01value", "emoji \U0001f600"],
    )
    def test_invalid(self, value):
        ok, message = bc.validate_separator_value(value)
        assert not ok
        assert message

    def test_max_length_boundary(self):
        assert bc.validate_separator_value("A" * 128)[0]
        assert not bc.validate_separator_value("A" * 129)[0]


class TestRetryLadder:
    """The ladder must stop as soon as the expected marker is decoded."""

    def _blank(self) -> np.ndarray:
        return np.full((400, 400), 255, dtype=np.uint8)

    def test_stops_early_on_first_attempt(self, monkeypatch):
        calls: list[int] = []

        class FakeResult:
            text = "EAGC-EDMS-00001"
            format = "Code128"

        def fake_read(image):
            calls.append(1)
            return [FakeResult()]

        monkeypatch.setattr(bc, "_read", fake_read)
        outcome = bc.decode_page_barcodes(self._blank(), "EAGC-EDMS-00001")

        assert outcome.matched
        assert len(calls) == 1, "must not retry once the marker is found"
        assert [a.name for a in outcome.attempts] == ["as_rendered"]

    def test_walks_full_ladder_when_never_found(self, monkeypatch):
        monkeypatch.setattr(bc, "_read", lambda image: [])
        outcome = bc.decode_page_barcodes(self._blank(), "EAGC-EDMS-00001")

        assert not outcome.matched
        assert [a.name for a in outcome.attempts] == [
            "as_rendered",
            "gray_autocontrast",
            "otsu",
            "upscale_1.5x",
        ]

    def test_stops_at_the_rung_that_succeeds(self, monkeypatch):
        state = {"n": 0}

        class FakeResult:
            text = "PATCHT"
            format = "Code128"

        def fake_read(image):
            state["n"] += 1
            return [FakeResult()] if state["n"] == 3 else []

        monkeypatch.setattr(bc, "_read", fake_read)
        outcome = bc.decode_page_barcodes(self._blank(), "PATCHT")

        assert outcome.matched
        assert state["n"] == 3
        assert len(outcome.attempts) == 3

    def test_no_retries_without_expected_value(self, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(bc, "_read", lambda image: calls.append(1) or [])
        outcome = bc.decode_page_barcodes(self._blank(), None)

        assert not outcome.matched
        assert len(calls) == 1, "with no marker to hunt for, one pass is enough"

    def test_retries_disabled_flag(self, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(bc, "_read", lambda image: calls.append(1) or [])
        bc.decode_page_barcodes(self._blank(), "PATCHT", enable_retries=False)
        assert len(calls) == 1

    def test_all_values_retained_for_diagnostics(self, monkeypatch):
        class R:
            def __init__(self, text):
                self.text = text
                self.format = "Code128"

        state = {"n": 0}

        def fake_read(image):
            state["n"] += 1
            return [R(f"OTHER-{state['n']}")]

        monkeypatch.setattr(bc, "_read", fake_read)
        outcome = bc.decode_page_barcodes(self._blank(), "MISSING")

        values = {v for v, _ in outcome.barcodes}
        assert values == {"OTHER-1", "OTHER-2", "OTHER-3", "OTHER-4"}
        assert not outcome.matched

    def test_decode_failure_is_contained(self, monkeypatch):
        """A throwing decoder must not propagate out of the ladder."""

        def boom(image, **kwargs):
            raise RuntimeError("zxing exploded")

        monkeypatch.setattr(bc.zxingcpp, "read_barcodes", boom)
        outcome = bc.decode_page_barcodes(self._blank(), "PATCHT")
        assert not outcome.matched
        assert outcome.barcodes == ()


class TestImageHelpers:
    def test_otsu_separates_bimodal_image(self):
        image = np.concatenate(
            [np.full((50, 100), 20, np.uint8), np.full((50, 100), 230, np.uint8)]
        )
        # The threshold may sit on the lower mode; any value that puts the
        # two modes on opposite sides of `gray > t` is a correct split.
        assert 20 <= bc.otsu_threshold(image) < 230

    def test_otsu_on_uniform_image_is_stable(self):
        assert bc.otsu_threshold(np.full((10, 10), 255, np.uint8)) in range(0, 256)

    def test_upscale_respects_dimension_cap(self):
        assert bc._upscale(np.zeros((8000, 10), np.uint8), 1.5, max_dim=9000) is None
        upscaled = bc._upscale(np.zeros((100, 200), np.uint8), 1.5)
        assert upscaled is not None and upscaled.shape == (150, 300)

    def test_grayscale_from_rgb(self):
        rgb = np.zeros((4, 4, 3), np.uint8)
        rgb[:, :, 1] = 255
        gray = bc._to_grayscale(rgb)
        assert gray.ndim == 2 and gray[0, 0] == pytest.approx(149, abs=2)


class TestUpscaleRungPolicy:
    """The 1.5x upscale rung is skipped only where it cannot help.

    Measured over a 39-variant corpus at the 300 DPI analysis resolution, the
    upscale rung never decoded a symbol the other rungs missed, while costing
    roughly half a second per page.  It is therefore skipped for renders whose
    short edge is already large, and kept for genuinely small ones.
    """

    def test_rung_runs_on_small_renders(self, monkeypatch):
        calls: list[str] = []

        def fake_read(image):
            calls.append(f"{image.shape}")
            return []

        monkeypatch.setattr(bc, "_read", fake_read)
        small = np.full((600, 800), 255, dtype=np.uint8)
        outcome = bc.decode_page_barcodes(small, "PATCHT")

        assert "upscale_1.5x" in [a.name for a in outcome.attempts]

    def test_rung_skipped_on_large_renders(self, monkeypatch):
        monkeypatch.setattr(bc, "_read", lambda image: [])
        large = np.full((3508, 2480), 255, dtype=np.uint8)
        outcome = bc.decode_page_barcodes(large, "PATCHT")

        names = [a.name for a in outcome.attempts]
        assert "upscale_1.5x_skipped_high_res" in names
        assert "upscale_1.5x" not in names

    def test_cheaper_otsu_runs_before_upscale(self, monkeypatch):
        monkeypatch.setattr(bc, "_read", lambda image: [])
        small = np.full((600, 800), 255, dtype=np.uint8)
        names = [a.name for a in bc.decode_page_barcodes(small, "PATCHT").attempts]

        assert names.index("otsu") < names.index("upscale_1.5x")


class TestRealBarcodeDecoding:
    """Test actual zxingcpp reading on generated barcode arrays without mocks."""

    def _generate_barcode_image(self, value: str = "EAGC-EDMS-00001") -> np.ndarray:
        barcode = bc.zxingcpp.create_barcode(value, bc.zxingcpp.BarcodeFormat.Code128)
        try:
            img = bc.zxingcpp.write_barcode_to_image(
                barcode, size_hint=4, with_hrt=False, with_quiet_zones=True
            )
        except TypeError:
            img = bc.zxingcpp.write_barcode_to_image(
                barcode, scale=4, add_hrt=False, add_quiet_zones=True
            )
        return np.array(img, copy=True)

    def test_read_real_barcode(self):
        arr = self._generate_barcode_image("EAGC-EDMS-00001")
        results = bc._read(arr)
        assert len(results) >= 1
        assert results[0].text == "EAGC-EDMS-00001"

    def test_read_inverted_real_barcode(self):
        arr = self._generate_barcode_image("PATCHT")
        inv = 255 - arr
        results = bc._read(inv)
        assert len(results) >= 1
        assert results[0].text == "PATCHT"

    def test_format_names_are_stable_across_zxing_versions(self):
        assert bc._format_name("BarcodeFormat.Code128") == "Code128"
        assert bc._format_name("Code 128") == "Code128"
        assert bc._format_name("QR Code") == "QRCode"

    def test_decode_page_barcodes_with_real_barcode(self):
        arr = self._generate_barcode_image("EAGC-EDMS-00001")
        outcome = bc.decode_page_barcodes(arr, "EAGC-EDMS-00001")
        assert outcome.matched
        assert ("EAGC-EDMS-00001", "Code128") in outcome.barcodes


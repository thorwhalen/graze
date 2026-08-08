"""Tests for :mod:`graze.content_kind`.

The load-bearing cases are the ones a share link actually produces: an HTML sign-in page
served with ``HTTP 200``, and a folder link that resolves to a ZIP.
"""

import pytest

from graze.content_kind import (
    SNIFF_BYTES,
    ContentKindMismatch,
    assert_content_kind,
    kind_checked,
    sniff_content_family,
)

# A real Google Drive sign-in interstitial's opening bytes — this is what a *private*
# Drive share link answers with, at HTTP 200, instead of the media.
GOOGLE_SIGNIN_HEAD = (
    b'<!doctype html><html lang="en-US" dir="ltr"><head>'
    b'<base href="https://accounts.google.com/v3/signin/">'
)

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF"
ZIP = b"PK\x03\x04\x14\x00\x00\x00\x08\x00"
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00"
WAV = b"RIFF\x24\x08\x00\x00WAVEfmt "
WEBM = b"\x1a\x45\xdf\xa3\x9fB\x86\x81\x01"


class TestSniff:
    @pytest.mark.parametrize(
        "head,expected",
        [
            (PNG, "image"),
            (JPEG, "image"),
            (ZIP, "archive"),
            (MP4, "video"),
            (M4A, "audio"),
            (WAV, "audio"),
            (WEBM, "video"),
            (GOOGLE_SIGNIN_HEAD, "html"),
            (b'{"key": 1}', "json"),
            (b"[1, 2]", "json"),
            (b"\x1f\x8b\x08\x00", "archive"),
            (b"OggS\x00\x02", "audio"),
        ],
    )
    def test_recognised(self, head, expected):
        assert sniff_content_family(head) == expected

    @pytest.mark.parametrize("head", [b"", b"\x00\x01\x02\x03", b"plain text"])
    def test_unknown_is_none_not_bad(self, head):
        assert sniff_content_family(head) is None

    def test_bom_and_whitespace_do_not_hide_html(self):
        assert sniff_content_family(b"\xef\xbb\xbf  \n<!DOCTYPE html>") == "html"


class TestAssert:
    def test_html_is_refused_for_every_kind(self):
        for kind in ("image", "video", "audio", "json"):
            with pytest.raises(ContentKindMismatch, match="HTML page"):
                assert_content_kind(GOOGLE_SIGNIN_HEAD, expect_kind=kind)

    def test_html_message_names_the_likely_cause(self):
        """A private share link is the usual cause; the message must say so."""
        with pytest.raises(ContentKindMismatch) as exc:
            assert_content_kind(GOOGLE_SIGNIN_HEAD, expect_kind="audio")
        assert "anyone-with-the-link" in str(exc.value)

    def test_archive_is_refused_and_named(self):
        with pytest.raises(ContentKindMismatch, match="archive"):
            assert_content_kind(ZIP, expect_kind="video")

    def test_url_appears_in_the_message_when_given(self):
        with pytest.raises(ContentKindMismatch, match="notthemedia"):
            assert_content_kind(ZIP, expect_kind="video", url="https://x/notthemedia")

    @pytest.mark.parametrize(
        "head,kind", [(MP4, "audio"), (M4A, "video"), (WEBM, "audio")]
    )
    def test_audio_video_ambiguity_passes_both_ways(self, head, kind):
        """A container's magic bytes cannot separate audio-only from audio+video."""
        assert_content_kind(head, expect_kind=kind)  # must not raise

    @pytest.mark.parametrize("head,kind", [(PNG, "audio"), (JPEG, "video"), (WAV, "image")])
    def test_unambiguous_disagreement_is_refused(self, head, kind):
        with pytest.raises(ContentKindMismatch):
            assert_content_kind(head, expect_kind=kind)

    def test_unknown_passes(self):
        assert_content_kind(b"\x00\x01\x02\x03", expect_kind="video")  # must not raise

    @pytest.mark.parametrize("head,kind", [(PNG, "image"), (M4A, "audio"), (MP4, "video")])
    def test_agreement_passes(self, head, kind):
        assert_content_kind(head, expect_kind=kind)


class TestKindChecked:
    def test_bytes_are_preserved_exactly(self):
        chunks = [PNG, b"middle", b"tail"]
        assert b"".join(kind_checked(chunks, expect_kind="image")) == b"".join(chunks)

    def test_refuses_before_yielding_anything(self):
        """The whole point: a bad stream must not leak a single byte to the consumer.

        A guard that checked after draining would let an incremental writer commit a
        partial HTML file to disk before the verdict arrived.
        """
        written = []

        def source():
            for chunk in (GOOGLE_SIGNIN_HEAD, b"more html"):
                written.append(chunk)
                yield chunk

        stream = kind_checked(source(), expect_kind="video")
        with pytest.raises(ContentKindMismatch):
            next(stream)

    def test_head_is_buffered_across_small_chunks(self):
        """A signature split across chunks must still be recognised."""
        chunks = [PNG[:2], PNG[2:], b"rest"]
        assert b"".join(kind_checked(chunks, expect_kind="image")) == PNG + b"rest"
        with pytest.raises(ContentKindMismatch):
            list(kind_checked([PNG[:2], PNG[2:]], expect_kind="audio"))

    def test_empty_stream_is_unknown_and_passes(self):
        assert list(kind_checked([], expect_kind="video")) == []

    def test_a_long_stream_is_not_fully_buffered(self):
        """Only the head is buffered; the tail streams lazily.

        The first chunk alone exceeds SNIFF_BYTES, so buffering stops immediately and
        nothing beyond it is pulled. (A stream whose *total* is under SNIFF_BYTES is
        legitimately drained into the head buffer — the cost of a fixed sniff window.)
        """
        pulled = []

        def source():
            yield PNG + b"\x00" * SNIFF_BYTES
            for i in range(5):
                pulled.append(i)
                yield b"x" * 8

        stream = kind_checked(source(), expect_kind="image")
        next(stream)  # the buffered head
        assert pulled == [], "the tail must not have been consumed yet"

    def test_buffer_bound_is_sniff_bytes_plus_one_chunk(self):
        """Pin the honest memory bound, so the docstring cannot quietly become false.

        The length is checked *after* appending, so a producer handing over one enormous
        chunk has it held whole. Unavoidable (the bytes are already in memory), harmless
        for chunked readers, but it must not be described as bounded by SNIFF_BYTES alone.
        """
        big = PNG + b"\x00" * (4 * SNIFF_BYTES)
        first = next(kind_checked([big, b"tail"], expect_kind="image"))
        assert len(first) == len(big) > SNIFF_BYTES


class TestAdversarialFindings:
    """Regression tests for four blocking findings from the pre-merge review.

    Every one of these passed review only because the test file was originally placed
    outside pytest's ``testpaths``, so none of it ran in CI. That is the finding behind the
    findings: a green check on an uncollected suite says nothing.
    """

    def test_svg_with_an_xml_declaration_is_an_image_not_html(self):
        """`<?xml` used to be an HTML prefix, so a declared SVG was refused as a web page.

        Worse, it was self-inconsistent: the same image WITHOUT the declaration passed.
        """
        declared = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>'
        bare = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
        assert sniff_content_family(declared) == "image"
        assert sniff_content_family(bare) == "image"
        assert_content_kind(declared, expect_kind="image")  # must not raise

    def test_utf16_html_does_not_pass_as_media(self):
        """A UTF-16LE BOM is `\\xff\\xfe`, which trips the MP3 frame-sync test.

        Because audio and video are mutually permissive, that made a UTF-16 sign-in page
        pass `assert_content_kind` as media — defeating the module's entire purpose.
        """
        page = b"\xff\xfe" + "<html><body>Sign in</body></html>".encode("utf-16-le")
        assert sniff_content_family(page) == "html"
        for kind in ("audio", "video", "image"):
            with pytest.raises(ContentKindMismatch):
                assert_content_kind(page, expect_kind=kind)

    @pytest.mark.parametrize("bom,codec", [(b"\xfe\xff", "utf-16-be"), (b"\xff\xfe", "utf-16-le")])
    def test_utf16_json_is_json_either_endianness(self, bom, codec):
        assert sniff_content_family(bom + '{"a": 1}'.encode(codec)) == "json"

    def test_a_real_mp3_frame_still_sniffs_as_audio(self):
        """The tightened sync check must not cost a true positive.

        MPEG-1 Layer III, 128 kbps, 44.1 kHz: \\xff\\xfb\\x90\\x00.
        """
        assert sniff_content_family(b"\xff\xfb\x90\x00") == "audio"

    def test_unrecognised_ftyp_brand_is_unknown_not_video(self):
        """An open-ended registry must not be guessed at.

        Guessing 'video' hard-refuses genuine images, because images are deliberately
        outside the audio/video ambiguity exemption.
        """
        assert sniff_content_family(b"\x00\x00\x00\x18ftypzzzz\x00\x00\x00\x00") is None
        assert_content_kind(
            b"\x00\x00\x00\x18ftypzzzz\x00\x00\x00\x00", expect_kind="image"
        )  # permissive

    def test_canon_cr3_photo_is_an_image(self):
        assert sniff_content_family(b"\x00\x00\x00\x18ftypcrx \x00\x00\x00\x01") == "image"

    def test_bm_prose_is_not_an_image(self):
        """'BM' alone matched ordinary text; a BMP also has a plausible size field."""
        assert sniff_content_family(b"BMW service manual, page 1") is None
        real_bmp = (
            b"BM"
            + (1024).to_bytes(4, "little")  # file size
            + b"\x00" * 4  # reserved
            + (54).to_bytes(4, "little")  # pixel-data offset
        )
        assert sniff_content_family(real_bmp) == "image"

    @pytest.mark.parametrize(
        "page",
        [
            b'<meta http-equiv="refresh" content="0;url=https://accounts.google.com/signin">',
            b'<script>window.location="https://accounts.google.com"</script>',
            b"<title>Sign in - Google Accounts</title>",
            b"<!DOCTYPE\nhtml>\n<html>",
            b"<!-- a comment first --><html><body>Sign in</body></html>",
        ],
    )
    def test_interstitials_that_do_not_open_with_html_are_still_html(self, page):
        """A sign-in page does not reliably start with `<html>`."""
        assert sniff_content_family(page) == "html"
        with pytest.raises(ContentKindMismatch):
            assert_content_kind(page, expect_kind="video")


def test_content_kind_doctests():
    """CI's testpaths is ["tests"], so --doctest-modules never reaches graze/.

    Run the module's doctests explicitly so its examples are actually gated — mirroring
    tests/test_share_links.py::test_share_links_doctests.
    """
    import doctest

    import graze.content_kind

    results = doctest.testmod(
        graze.content_kind,
        optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE,
    )
    assert results.failed == 0, f"{results.failed} doctest failure(s)"

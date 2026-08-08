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
        legitimately drained into the head buffer — that is the cost of a fixed sniff
        window, and it is bounded by SNIFF_BYTES.)
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

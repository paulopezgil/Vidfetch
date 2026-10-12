"""Tests for request validation."""
import pytest
from pydantic import ValidationError

from backend.models.schemas import DownloadRequest, InfoRequest


def test_valid_url():
    req = InfoRequest(url="https://youtube.com/watch?v=abc")
    assert req.url == "https://youtube.com/watch?v=abc"


@pytest.mark.parametrize("bad", ["", "   ", "not-a-url", "ftp://example.com/x", "javascript:alert(1)"])
def test_invalid_url_rejected(bad):
    with pytest.raises(ValidationError):
        InfoRequest(url=bad)


def test_download_request_defaults():
    req = DownloadRequest(url="https://example.com/v")
    assert req.operation_type == "video"
    assert req.format == "best"
    assert req.embed_subs is False


def test_download_request_bad_format():
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://example.com/v", format="8k")


def test_download_request_bad_operation():
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://example.com/v", operation_type="album")

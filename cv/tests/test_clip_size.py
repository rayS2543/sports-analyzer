"""The clip download stops at its size cap and does not publish a partial file.

A window that analyses a half-written video would measure the wrong frames.
"""

import pytest

from var_cv import analyze


class _Stream:
    def __init__(self, data, step):
        self.data, self.step, self.i = data, step, 0

    def read(self, _n):
        chunk = self.data[self.i:self.i + self.step]
        self.i += self.step
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_a_clip_at_the_size_cap_is_kept_and_one_byte_over_is_not_published(monkeypatch, tmp_path):
    body = {"data": b"12345678"}
    monkeypatch.setattr(analyze, "MAX_DOWNLOAD_BYTES", 8)
    monkeypatch.setattr(analyze.urllib.request, "urlopen", lambda *_a, **_k: _Stream(body["data"], 4))
    url = f"https://{analyze.ALLOWED_HOST}/espn/clip.mp4"
    dest = tmp_path / "video.mp4"
    analyze.download(url, dest)
    assert dest.read_bytes() == b"12345678"
    assert not (tmp_path / "video.mp4.part").exists()

    dest.unlink()
    body["data"] = b"123456789"
    with pytest.raises(analyze.UserError, match="larger than 500 MB"):
        analyze.download(url, dest)
    assert not dest.exists()

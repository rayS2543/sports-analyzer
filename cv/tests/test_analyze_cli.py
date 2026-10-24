"""The analysis CLI's source rules: ESPN's CDN for downloads, or a file the user uploaded."""
import json

from var_cv import analyze


def _run(tmp_path, *extra):
    out = tmp_path / "out"
    code = analyze.main(["--clip-id", "900000001", "--start", "0", "--end", "2", "--out", str(out), *extra])
    return code, json.loads((out / "error.json").read_text())["error"]


def test_a_url_outside_espns_cdn_is_still_refused(tmp_path):
    code, error = _run(tmp_path, "--source-url", "https://example.com/clip.mp4", "--video", str(tmp_path / "v.mp4"))
    assert code == 1 and "only https MP4s from espnmedia-cdn.akamaized.net" in error


def test_an_uploaded_video_needs_no_url_but_must_exist(tmp_path):
    code, error = _run(tmp_path, "--local", "--video", str(tmp_path / "missing.mp4"))
    assert code == 1 and error == "the uploaded video is missing"


def test_a_missing_video_without_local_still_needs_an_espn_url(tmp_path):
    code, error = _run(tmp_path, "--video", str(tmp_path / "missing.mp4"))
    assert code == 1 and "refusing source URL" in error

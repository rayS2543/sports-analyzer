"""Who may supply a clip, and which window and pitch size the pipeline will accept.

A bad allowlist downloads an arbitrary URL. A bad window or pitch size shifts every
metre the offside and foul reviews measure.
"""

import json

import pytest

from var_cv import analyze

HOST = analyze.ALLOWED_HOST
OK = f"https://{HOST}/espn/clip.mp4"


def test_only_https_mp4s_from_the_clip_host_are_accepted():
    analyze.check_url(OK)
    analyze.check_url(f"https://{HOST}/espn/clip.mp4?token=1")


@pytest.mark.parametrize("url", [
    f"http://{HOST}/espn/clip.mp4",
    "https://evil.example/espn/clip.mp4",
    f"https://{HOST}.evil.example/clip.mp4",
    f"https://not{HOST}/clip.mp4",
    f"https://{HOST}/espn/clip.mp4.txt",
    f"https://{HOST}/espn/clip.MP4",
    f"https://{HOST}/espn/clip.mp4/file",
    "https:///clip.mp4",
    "",
])
def test_other_sources_are_refused(url):
    with pytest.raises(analyze.UserError, match="refusing source URL"):
        analyze.check_url(url)


def _args(out, **over):
    base = {"clip-id": "clip1", "source-url": OK, "start": "1", "end": "3", "out": str(out)}
    base.update(over)
    argv = []
    for key, value in base.items():
        argv += [f"--{key}", value]
    return argv


@pytest.mark.parametrize("over, reason", [
    ({"clip-id": "../secret"}, "invalid clip id"),
    ({"clip-id": "a" * 41}, "invalid clip id"),
    ({"start": "0", "end": "10.06"}, "window must satisfy"),  # rounds to 10.1s, past the 10s cap
    ({"start": "-0.06", "end": "1"}, "window must satisfy"),
    ({"start": "4", "end": "4"}, "window must satisfy"),
    ({"pitch-length": "89"}, "pitch dimensions"),
    ({"pitch-length": "120.1"}, "pitch dimensions"),
    ({"pitch-width": "44.9"}, "pitch dimensions"),
    ({"pitch-width": "90.1"}, "pitch dimensions"),
    ({"source-url": f"http://{HOST}/espn/clip.mp4"}, "refusing source URL"),
    ({"source-url": f"https://{HOST}.evil.example/clip.mp4"}, "refusing source URL"),
])
def test_rejected_inputs_are_recorded_and_never_downloaded(tmp_path, monkeypatch, over, reason):
    def fail_download(*_a, **_k):
        raise AssertionError("downloaded")

    monkeypatch.setattr(analyze.urllib.request, "urlopen", fail_download)
    out = tmp_path / "out"
    assert analyze.main(_args(out, **over)) == 1
    assert reason in json.loads((out / "error.json").read_text())["error"]
    assert not (out / "analysis.json").exists()


def test_venue_lookup_and_rounding_do_not_fetch_video(tmp_path):
    known = analyze.parse(_args(tmp_path, start="1.26", end="4.24", venue="  Estadi Johan Cruyff "))
    assert (known.start, known.end) == (1.3, 4.2)
    assert known.pitch[:2] == (105.0, 68.0)
    assert "unverified" not in known.pitch[2]

    unknown = analyze.parse(_args(tmp_path, venue="Some Other Ground"))
    assert unknown.pitch == analyze.DEFAULT_PITCH
    assert "unverified" in unknown.pitch[2]

    override = analyze.parse(_args(tmp_path, venue="Estadi Johan Cruyff", **{"pitch-length": "100"}))
    assert override.pitch == (100.0, 68.0, "caller-provided")

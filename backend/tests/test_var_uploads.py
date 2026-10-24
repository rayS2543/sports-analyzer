import io
import json
from unittest.mock import patch

import pytest

from routes import var_analysis

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setenv("VAR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VAR_CV_PYTHON", str(python))
    monkeypatch.setattr(var_analysis, "_job", None)
    return tmp_path / "data"


def send(client, data=MP4, name="my clip.mp4", **form):
    return client.post("/var/upload", data={"file": (io.BytesIO(data), name), **form}, content_type="multipart/form-data")


def test_an_uploaded_mp4_is_stored_under_an_id_that_cannot_clash_with_espn(client, env):
    result = send(client, title="  Corner, 34'  ")
    clip = result.json["clip"]
    assert result.status_code == 201 and clip["id"].startswith("9") and len(clip["id"]) == 11
    assert clip["title"] == "Corner, 34'" and clip["bytes"] == len(MP4)
    assert (env / clip["id"] / "video.mp4").read_bytes() == MP4
    assert client.get(f"/var/video/{clip['id']}").status_code == 200  # served like an ESPN clip
    assert [c["id"] for c in client.get("/var/uploads").json["clips"]] == [clip["id"]]


def test_the_same_file_uploaded_twice_is_one_clip(client):
    assert send(client).json["clip"]["id"] == send(client, name="again.mp4").json["clip"]["id"]
    assert len(client.get("/var/uploads").json["clips"]) == 1


@pytest.mark.parametrize("data,name,status", [(MP4, "clip.mov", 400), (b"not a video at all, just text", "clip.mp4", 400), (b"", "clip.mp4", 400)])
def test_only_real_mp4_files_are_accepted(client, data, name, status):
    assert send(client, data=data, name=name).status_code == status
    assert client.get("/var/uploads").json["clips"] == []


def test_a_file_over_the_limit_is_refused_and_not_kept(client, env, monkeypatch):
    monkeypatch.setattr("routes.var_uploads.MAX_UPLOAD_BYTES", 32)
    assert send(client).status_code == 413
    assert client.get("/var/uploads").json["clips"] == []
    assert not list((env / "uploads-tmp").glob("*.part"))


def test_the_filename_never_picks_where_the_file_is_stored(client, env):
    clip = send(client, name="../../etc/passwd.mp4").json["clip"]
    assert clip["filename"] == "passwd.mp4" and (env / clip["id"] / "video.mp4").is_file()


def test_analysing_an_uploaded_clip_needs_no_league_event_or_url(client, env):
    clip_id = send(client).json["clip"]["id"]
    with patch("routes.var_analysis.subprocess.Popen") as popen, patch("routes.var_clips.requests.get") as get:
        popen.return_value.poll.return_value = None
        result = client.post("/var/analyze", json={"clip": clip_id, "start": 2, "end": 6})
    assert result.status_code == 202 and result.json["clip"] == clip_id
    args = popen.call_args.args[0]
    assert "--local" in args and "--source-url" not in args
    assert args[args.index("--video") + 1] == str(env.resolve() / clip_id / "video.mp4")
    get.assert_not_called()


def test_an_id_that_was_never_uploaded_still_needs_a_league_and_event(client):
    with patch("routes.var_analysis.subprocess.Popen") as popen:
        assert client.post("/var/analyze", json={"clip": "90000000001", "start": 2, "end": 6}).status_code == 400
    popen.assert_not_called()


def test_an_espn_video_picked_by_link_is_analysed_without_a_league_or_match(client, env):
    from unittest.mock import Mock
    source = "https://espnmedia-cdn.akamaized.net/espn/media/mbappe.mp4"
    data = {"videos": [{"id": 44656413, "headline": "Sent off", "duration": 65, "links": {"source": {"href": source}}}]}
    with patch("routes.var_clips.requests.get", return_value=Mock(status_code=200, json=lambda: data, raise_for_status=lambda: None)), \
            patch("routes.var_analysis.subprocess.Popen") as popen:
        popen.return_value.poll.return_value = None
        result = client.post("/var/analyze", json={"clip": "44656413", "start": 2, "end": 6})
    assert result.status_code == 202
    args = popen.call_args.args[0]
    assert args[args.index("--source-url") + 1] == source and "--local" not in args


def test_an_espn_id_with_no_downloadable_video_is_not_analysed(client):
    from unittest.mock import Mock
    with patch("routes.var_clips.requests.get", return_value=Mock(status_code=404)), patch("routes.var_analysis.subprocess.Popen") as popen:
        assert client.post("/var/analyze", json={"clip": "44656413", "start": 2, "end": 6}).status_code == 404
    popen.assert_not_called()


def test_mp4s_dropped_into_the_inbox_folder_become_clips_and_leave_the_folder(client, env):
    inbox = env / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "Corner 34 min.mp4").write_bytes(MP4)
    (inbox / "notes.txt").write_text("not a clip")
    (inbox / "fake.mp4").write_bytes(b"this is text pretending to be a video")
    clips = client.get("/var/uploads").json["clips"]
    assert [c["title"] for c in clips] == ["Corner 34 min"]
    assert (env / clips[0]["id"] / "video.mp4").read_bytes() == MP4
    assert sorted(p.name for p in inbox.iterdir()) == ["fake.mp4", "notes.txt"]  # only the real MP4 was taken in


def test_the_same_file_dropped_again_is_not_kept_twice(client, env):
    inbox = env / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "a.mp4").write_bytes(MP4)
    first = client.get("/var/uploads").json["clips"]
    (inbox / "again.mp4").write_bytes(MP4)
    second = client.get("/var/uploads").json["clips"]
    assert [c["id"] for c in first] == [c["id"] for c in second] and len(second) == 1
    assert list(inbox.iterdir()) == []


def test_a_symlink_in_the_inbox_is_not_followed(client, env, tmp_path):
    inbox = env / "inbox"
    inbox.mkdir(parents=True)
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(MP4)
    (inbox / "link.mp4").symlink_to(secret)
    assert client.get("/var/uploads").json["clips"] == [] and secret.exists()

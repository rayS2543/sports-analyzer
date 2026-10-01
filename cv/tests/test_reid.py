"""reid on a synthetic video: kit-coloured boxes on grass, a tracker swap, a live cut and a replay."""

import cv2
import numpy as np

from var_cv import reid

W, H, FPS = 640, 360, 10.0
GRASS = (40, 140, 40)
SKIN = (120, 160, 210)
KITS = {  # head, shirt, shorts, socks (BGR)
    "A": (SKIN, (40, 40, 200), (240, 240, 240), (40, 40, 200)),
    "B": (SKIN, (200, 90, 30), (200, 90, 30), (240, 240, 240)),
    "ref": (SKIN, (20, 20, 20), (20, 20, 20), (20, 20, 20)),
    "gk": (SKIN, (0, 140, 255), (20, 20, 20), (0, 140, 255)),
}


def draw(img, box, kit):
    x1, y1, x2, y2 = (int(v) for v in box)
    h = y2 - y1
    cuts = [y1, y1 + int(0.16 * h), y1 + int(0.5 * h), y1 + int(0.72 * h), y2]
    for colour, a, b in zip(kit, cuts, cuts[1:]):
        cv2.rectangle(img, (x1, a), (x2, b), colour, -1)


def box_at(u, v, h=60):
    return [u - 12, v - h, u + 12, v]


def write_video(path, frames_people):
    """frames_people: list (per video frame) of [(box, kit)] drawn back to front."""
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for people in frames_people:
        img = np.full((H, W, 3), GRASS, np.uint8)
        for box, kit in people:
            draw(img, box, kit)
        vw.write(img)
    vw.release()


def player(tid, box, team, role="player", x=None, y=None):
    return {"track_id": tid, "role": role, "team": team, "x": x, "y": y, "bbox": box,
            "foot": [(box[0] + box[2]) / 2, box[3]]}


def test_crossing_swap_is_repaired(tmp_path):
    frames, video = [], []
    for k in range(30):
        u1, u2 = 100 + 14 * k, 520 - 14 * k  # cross at k = 15
        b1, b2, b3 = box_at(u1, 200), box_at(u2, 205), box_at(320, 320)
        video.append([(b2, KITS["B"]), (b1, KITS["A"]), (b3, KITS["A"])])
        # the tracker swapped the two ids at the crossing; team is the (wrong) per-track majority vote
        t1, t2 = (2, 1) if k > 15 else (1, 2)
        frames.append({"t": k / FPS, "shot": 0, "calibration": {"ok": False}, "ball": None, "players": [
            player(t1, b1, "AB"[t1 - 1]), player(t2, b2, "AB"[t2 - 1]), player(3, b3, "A")]})
    write_video(tmp_path / "v.mp4", video)
    an = {"video": {"fps": FPS, "width": W, "height": H}, "frames": frames}
    reid.apply(an, tmp_path / "v.mp4")
    for f in an["frames"]:
        by_u = sorted(f["players"], key=lambda p: p["bbox"][1])  # y: person 1 at 200, 2 at 205, 3 at 320
        assert [p["track_id"] for p in by_u] == [1, 2, 3], f["t"]
        assert by_u[1]["team"] == "B"  # majority team recomputed on the repaired track
    assert len({p["global_id"] for f in an["frames"] for p in f["players"]}) == 3
    assert [s["track_ids"] for s in an["identity"]["swaps_fixed"]] == [[1, 2]]


def test_same_kit_players_are_not_swapped(tmp_path):
    frames, video = [], []
    for k in range(30):
        b1, b2 = box_at(100 + 14 * k, 200), box_at(520 - 14 * k, 205)
        video.append([(b2, KITS["A"]), (b1, KITS["A"])])
        frames.append({"t": k / FPS, "shot": 0, "calibration": {"ok": False}, "ball": None,
                       "players": [player(1, b1, "A"), player(2, b2, "A")]})
    write_video(tmp_path / "v.mp4", video)
    an = {"video": {"fps": FPS, "width": W, "height": H}, "frames": frames}
    reid.apply(an, tmp_path / "v.mp4")
    assert an["identity"]["swaps_fixed"] == []  # no appearance evidence either way: leave it


def test_ids_carry_over_a_live_cut_and_a_replay(tmp_path):
    # four people on the pitch: two same-kit teammates, an opponent and the referee
    people = [("A", "player", (30.0, 20.0), (3.0, 0.0)), ("A", "player", (36.0, 24.0), (-2.0, 1.0)),
              ("B", "player", (40.0, 30.0), (0.0, -2.0)), (None, "referee", (33.0, 34.0), (1.0, 1.0))]
    kit = lambda team, role: KITS["ref"] if role == "referee" else KITS[team]
    frames, video = [], []
    for k in range(60):
        t = k / FPS
        shot = 0 if k < 20 else (1 if k < 40 else 2)
        if k >= 40:
            t += 5.0  # the replay shows earlier action, 5 s later in source time (not contiguous)
        ps, drawn = [], []
        members = list(enumerate(people)) + ([(4, ("B", "player", (45.0, 22.0), (0.0, 0.0)))] if shot == 1 else [])
        for n, (team, role, p0, v) in members:
            x, y = p0[0] + v[0] * (k / FPS), p0[1] + v[1] * (k / FPS)
            if shot == 0:
                u, vv = 40 + 12 * x, 40 + 8 * y
            elif shot == 1:  # another camera: different, mirrored image layout
                u, vv = 600 - 11 * (x - 20), 330 - 7 * y
            else:
                u, vv = 60 + 9 * (x - 20), 80 + 6 * y
            box = box_at(u, vv)
            drawn.append((box, kit(team, role)))
            tid = [3, 1, 4, 2, 5][n] if shot == 1 else n + 1  # the tracker numbers each shot afresh
            ps.append(player(tid, box, team, role, *(round(x, 2), round(y, 2)) if shot < 2 else (None, None)))
            ps[-1]["_who"] = n
        video.append(drawn)
        frames.append({"t": round(t, 3), "shot": shot, "calibration": {"ok": shot < 2}, "ball": None, "players": ps})
    # video time: the replay frames sit 5 s later in the file, so pad with 50 empty frames
    write_video(tmp_path / "v.mp4", video[:40] + [[]] * 50 + video[40:])
    an = {"video": {"fps": FPS, "width": W, "height": H}, "frames": frames}
    reid.apply(an, tmp_path / "v.mp4")
    gid = {}
    for f in an["frames"]:
        for p in f["players"]:
            gid.setdefault((f["shot"], p["_who"]), p["global_id"])
    for n in range(4):  # live cut: everybody keeps their id, including the same-kit teammates
        assert gid[(0, n)] == gid[(1, n)], n
    assert gid[(1, 4)] not in {gid[(0, n)] for n in range(4)}  # newcomer gets a fresh id
    assert gid[(2, 3)] == gid[(0, 3)]  # replay: the referee's kit is unique -> matched by appearance
    # same-kit players are ambiguous without positions -> fresh ids rather than a guess
    assert gid[(2, 0)] not in {gid[(0, 0)], gid[(0, 1)]}
    assert gid[(2, 2)] not in {gid[(0, 2)], gid[(1, 4)]}
    kinds = [c["kind"] for c in an["identity"]["cuts"]]
    assert kinds == ["first", "live", "appearance"]

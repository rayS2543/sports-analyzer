"""Identity gates between samples: how far a player may step, grow, or disappear."""

import numpy as np

from var_cv import track


def _box(x, y, h, w=30.0):
    return [x - w / 2, y - h, x + w / 2, y]


def _ids(frames, tangles=True):
    seq = []
    for boxes, *rest in frames:
        teams = rest[0] if rest else None
        arr = np.zeros((0, 4)) if len(boxes) == 0 else np.asarray(boxes, float).reshape(-1, 4)
        frame = (arr, lambda p: p) if teams is None else (arr, lambda p: p, teams)
        seq.append(frame)
    return track.assign_ids(seq, tangles=tangles)


def test_eight_missed_samples_keep_the_player_and_the_ninth_ends_the_track():
    home = ([_box(200, 300, 80)],)
    gap = ([],)
    back = _ids([home] + [gap] * track.MAX_MISSED + [home])
    assert int(back[0][0]) == int(back[-1][0])
    gone = _ids([home] + [gap] * (track.MAX_MISSED + 1) + [home])
    assert int(gone[0][0]) != int(gone[-1][0])


def test_a_step_at_the_gate_is_the_same_player_and_past_it_is_not():
    h = 10.0
    limit = track.GATE * h  # foot distance / box height
    same = _ids([([_box(200, 300, h)],), ([_box(200 + limit, 300, h)],)])
    assert int(same[0][0]) == int(same[1][0])
    new = _ids([([_box(200, 300, h)],), ([_box(200 + limit + 0.2, 300, h)],)])
    assert int(new[0][0]) != int(new[1][0])


def test_box_height_may_change_by_the_scale_cap_and_no_more():
    h = 80.0
    cap = track.MAX_SCALE * h
    same = _ids([([_box(200, 300, h)],), ([_box(200, 300, cap)],)])
    assert int(same[0][0]) == int(same[1][0])
    new = _ids([([_box(200, 300, h)],), ([_box(200, 300, cap + 0.5)],)])
    assert int(new[0][0]) != int(new[1][0])


def test_close_up_association_keeps_a_track_through_a_kit_flicker_and_a_size_jump():
    # Close-ups (tangles=False) match the last position only. A flickering kit or a box that
    # suddenly fills the frame is still the same person; the wide-shot gates stay off.
    big = _box(200, 300, 80)
    tiny = _box(200, 300, 20)
    kit = _ids([([big], ["A"]), ([big], ["B"])], tangles=False)
    assert int(kit[0][0]) == int(kit[1][0])
    sized = _ids([([big],), ([tiny],)], tangles=False)
    assert int(sized[0][0]) == int(sized[1][0])

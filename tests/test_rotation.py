"""Uploaded phone videos carry a rotation flag that OpenCV ignores; the job must turn them upright."""
import numpy as np
import pytest

av = pytest.importorskip("av")


def _rotated_mp4(path, rotation=-90, w=64, h=32, n=6):
    """Landscape pixels (w x h) plus a display-matrix rotation, like a portrait phone recording."""
    with av.open(str(path), "w") as out:
        s = out.add_stream("libx264", rate=10)
        s.width, s.height, s.pix_fmt = w, h, "yuv420p"
        try:
            s.metadata["rotate"] = str(-rotation % 360)  # older muxers
        except Exception:
            pass
        for i in range(n):
            img = np.zeros((h, w, 3), np.uint8)
            img[:, : w // 4] = 255  # a bright band on the left edge marks the orientation
            fr = av.VideoFrame.from_ndarray(img, format="rgb24")
            fr.pts = i
            for p in s.encode(fr):
                out.mux(p)
        for p in s.encode():
            out.mux(p)


def test_video_rotation_reads_flag_and_normalize_makes_upright(tmp_path):
    from civil.video.frames import video_info, video_rotation
    from civil.video.normalize import normalize_recording

    src = tmp_path / "phone.mp4"
    _rotated_mp4(src)
    rot = video_rotation(src)
    if rot == 0:  # PyAV cannot write the flag; add it with ffmpeg when one is available
        import os, shutil, subprocess
        ff = os.environ.get("CIVIL_FFMPEG") or shutil.which("ffmpeg")
        if not ff:
            pytest.skip("no ffmpeg to write a rotation flag")
        flagged = tmp_path / "phone-flagged.mp4"
        subprocess.run([ff, "-v", "error", "-display_rotation", "90", "-i", str(src), "-c", "copy", str(flagged)], check=True)
        src = flagged
        rot = video_rotation(src)
    assert rot in (90, 270)
    dst = tmp_path / "upright.mp4"
    normalize_recording(src, dst, fps=10)
    info = video_info(dst)
    assert video_rotation(dst) == 0
    assert info["height"] > info["width"]  # portrait after applying the flag


def test_video_rotation_zero_for_plain_video(tmp_path):
    from civil.video.frames import video_rotation

    src = tmp_path / "plain.mp4"
    with av.open(str(src), "w") as out:
        s = out.add_stream("libx264", rate=10)
        s.width, s.height, s.pix_fmt = 64, 32, "yuv420p"
        for i in range(3):
            fr = av.VideoFrame.from_ndarray(np.zeros((32, 64, 3), np.uint8), format="rgb24")
            fr.pts = i
            for p in s.encode(fr):
                out.mux(p)
        for p in s.encode():
            out.mux(p)
    assert video_rotation(src) == 0

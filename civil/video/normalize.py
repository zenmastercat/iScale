"""Turn a browser recording into a constant-frame-rate MP4 the video pipeline can read.

Phones record in the browser (MediaRecorder) as WebM or MP4 with a variable frame rate, and
WebM files from Chrome carry no duration or frame count. OpenCV then reports 0 frames, and
frame N is not at N / fps seconds, which would break the GPS track's time base. This decodes
the recording with PyAV and writes H.264 at a fixed rate, repeating or dropping frames so that
output frame k is the picture shown at k / fps seconds after the first frame. The recorded GPS
track uses the same zero (the recorder's start, within a frame or two of the first frame), so
the two stay in step.

Safari on iPhone stores an upright recording as landscape pixels plus a rotation flag; the flag
is applied here so the road is the right way up for the detector and LingBot-Map.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _upright(rgb: np.ndarray, rotation: float) -> np.ndarray:
    """Apply the display rotation (degrees counter-clockwise, as PyAV reports it)."""
    theta = int(round(-rotation / 90.0)) % 4  # quarter turns clockwise, as ffmpeg's autorotate does
    return np.ascontiguousarray(np.rot90(rgb, k=-theta)) if theta else rgb


def normalize_recording(src: Path, dst: Path, fps: float = 30.0, max_width: int = 1920) -> dict:
    import av
    import cv2

    with av.open(str(src)) as inp:
        if not inp.streams.video:
            raise ValueError("the recording has no video; record again with the camera on")
        vin = inp.streams.video[0]
        vin.thread_type = "AUTO"
        out = av.open(str(dst), "w")
        try:
            vout = None
            t0 = None
            k = 0          # next output frame index
            last = None    # last decoded picture, upright, at the output size
            for frame in inp.decode(vin):
                if frame.time is None:
                    continue
                if t0 is None:
                    t0 = frame.time
                t = frame.time - t0
                rgb = _upright(frame.to_ndarray(format="rgb24"), getattr(frame, "rotation", 0) or 0)
                if vout is None:
                    h, w = rgb.shape[:2]
                    if max(w, h) > max_width:  # keep the long side at most max_width
                        f = max_width / max(w, h)
                        w, h = int(w * f), int(h * f)
                    vout = out.add_stream("libx264", rate=int(round(fps)))
                    vout.width, vout.height = w - w % 2, h - h % 2
                    vout.pix_fmt = "yuv420p"
                    vout.options = {"crf": "20", "preset": "veryfast"}
                if rgb.shape[1] != vout.width or rgb.shape[0] != vout.height:
                    rgb = cv2.resize(rgb, (vout.width, vout.height), interpolation=cv2.INTER_AREA)
                # emit every output time step that falls before this frame, showing the previous picture
                while last is not None and k / fps < t:
                    _write(out, vout, last, k)
                    k += 1
                last = rgb
            if last is not None:
                _write(out, vout, last, k)
                k += 1
            if vout is None:
                raise ValueError("the recording has no video frames; record again")
            for pkt in vout.encode():
                out.mux(pkt)
        finally:
            out.close()
    return {"frames": k, "fps": fps, "duration": k / fps}


def _write(out, vout, rgb, k: int) -> None:
    import av

    vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
    vf.pts = k
    for pkt in vout.encode(vf):
        out.mux(pkt)

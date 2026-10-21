"""Frames from the capture card (Walksnail VRX -> HDMI -> USB), a video file, or a photo folder."""
from __future__ import annotations

import os

from PIL import Image

import config

IMAGE_EXT = (".jpg", ".jpeg", ".png")


class FrameSource:
    """Call .get() for the newest frame as a PIL image. Works the same for every source type."""

    def __init__(self, source: str | int | None = None):
        source = config.CAMERA_SOURCE if source is None else source
        self.folder: list[str] | None = None
        self.cap = None
        if isinstance(source, str) and os.path.isdir(source):
            self.folder = sorted(os.path.join(source, f) for f in os.listdir(source)
                                 if f.lower().endswith(IMAGE_EXT))
            self.i = 0
            if not self.folder:
                raise SystemExit(f"No images in {source}")
        else:
            import cv2
            self.cv2 = cv2
            src = int(source) if str(source).isdigit() else source
            self.cap = cv2.VideoCapture(src)
            if not self.cap.isOpened():
                raise SystemExit(f"Could not open camera/video source {source!r}")
            self.live = isinstance(src, int)

    def get(self) -> Image.Image | None:
        if self.folder is not None:
            if self.i >= len(self.folder):
                return None
            img = Image.open(self.folder[self.i]).convert("RGB")
            self.i += 1
            return img
        if self.live:  # drop buffered frames so we act on what the camera sees now
            for _ in range(4):
                self.cap.grab()
        ok, frame = self.cap.read()
        if not ok:
            return None
        return Image.fromarray(self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB))

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()


if __name__ == "__main__":
    # Quick check: save one frame from the configured source.
    src = FrameSource()
    img = src.get()
    if img is None:
        raise SystemExit("No frame received.")
    img.save("frame_test.jpg")
    print(f"Saved frame_test.jpg ({img.width}x{img.height})")
    src.close()

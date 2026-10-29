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
        if config.MASK_OSD:
            # Black out the Walksnail on-screen text (voltage/bitrate bar along the bottom, SD box top right)
            # so the model doesn't read it as part of the floor. Rows stay where they were, so the
            # distance calibration is unaffected.
            h, w = frame.shape[:2]
            frame[int(h * 0.92):, :] = 0
            frame[: int(h * 0.20), int(w * 0.85):] = 0
        return Image.fromarray(self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB))

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()


def find_cameras(max_index: int = 5) -> list[int]:
    """Return the camera indexes that open. The capture card is usually 1 if the laptop has a webcam."""
    import cv2
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened() and cap.read()[0]:
            found.append(i)
        cap.release()
    return found


def preview(source: str | int | None = None) -> None:
    """Live window of the FPV feed. Press S to save a frame (good for test_photos), Q to quit."""
    import cv2
    source = config.CAMERA_SOURCE if source is None else source
    cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera {source!r}. Try: python brain/video_in.py --list")
    saved = 0
    print("Live preview: S = save frame to test_photos/, Q = quit")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("No frame from the capture card.")
            break
        cv2.imshow("Rescue Scout FPV", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            out = os.path.join(os.path.dirname(__file__), "..", "test_photos", f"fpv_{saved:03d}.jpg")
            cv2.imwrite(out, frame)
            print("saved", os.path.normpath(out))
            saved += 1
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    import sys
    if "--list" in sys.argv:
        cams = find_cameras()
        print("Cameras that work:", cams or "none found")
        print("Put the capture card's number in .env as CAMERA_SOURCE")
    elif "--show" in sys.argv:
        preview()
    elif "--snap" in sys.argv:
        # No window needed: press Enter in the terminal to save the current camera frame.
        src = FrameSource()
        out_dir = os.path.join(os.path.dirname(__file__), "..", "test_photos")
        n = 0
        print("Press Enter to save a photo, type q then Enter to finish.")
        while input(f"photo {n + 1}: ").strip().lower() != "q":
            for _ in range(3):  # flush old buffered frames so the photo is from now
                img = src.get()
            if img is None:
                print("No frame from the capture card.")
                continue
            path = os.path.normpath(os.path.join(out_dir, f"cal_{n:02d}.jpg"))
            img.save(path)
            print("saved", path)
            n += 1
        src.close()
    else:
        # Quick check: save one frame from the configured source.
        src = FrameSource()
        img = src.get()
        if img is None:
            raise SystemExit("No frame received.")
        img.save("frame_test.jpg")
        print(f"Saved frame_test.jpg ({img.width}x{img.height})")
        src.close()

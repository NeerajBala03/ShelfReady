"""
ShelfReady — Stage 4: images.

Prepares the main product image to each channel's specification. In a full build
this uses Pillow/OpenCV + a background remover; here it operates on the image's
metadata (size, background, overlay) which is all the validator needs, and it
makes the SAME decisions a real resizer would:

  * downscale to spec                      -> always fine
  * modest upscale / pad (<= MAX_UPSCALE)  -> allowed, recorded as a fix
  * big upscale needed (too low-res)       -> NOT fabricated; escalate to review
  * normalise background to white          -> recorded as a fix
  * strip text/watermark overlay           -> recorded as a fix

Returns the processed image meta + the list of fixes applied + whether a
higher-resolution source asset must be requested.
"""
from __future__ import annotations
import copy

MAX_UPSCALE = 1.5   # beyond this we won't invent pixels


def process_for_channel(image: dict, spec: dict) -> dict:
    img = copy.deepcopy(image or {})
    fixes, needs_better_asset = [], False

    # Resolution.
    src_px = img.get("px", 0)
    min_px = spec.get("min_px", 0)
    if src_px < min_px:
        if min_px <= src_px * MAX_UPSCALE:
            img["px"] = min_px
            fixes.append(f"upscaled {src_px}px → {min_px}px")
        else:
            needs_better_asset = True
            fixes.append(f"source only {src_px}px, channel needs {min_px}px — request higher-res asset")
    elif src_px > min_px:
        fixes.append(f"resized {src_px}px → {min_px}px")
        img["px"] = min_px

    # Background.
    want_bg = spec.get("background")
    if want_bg not in (None, "any") and img.get("bg") != want_bg:
        img["bg"] = want_bg
        fixes.append(f"background normalised to {want_bg}")

    # Overlay / watermark.
    if spec.get("text_overlay") is False and img.get("text_overlay"):
        img["text_overlay"] = False
        fixes.append("removed text/watermark overlay")

    return {"image": img, "fixes": fixes, "needs_better_asset": needs_better_asset}

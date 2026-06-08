from __future__ import annotations

import io

import PIL.Image
import PIL.ImageOps

_MAX_SIDE = 1600
_JPEG_QUALITY = 90


def preprocess_receipt(img_bytes: bytes) -> bytes:
    """Normalize a receipt photo for OCR: fix rotation, boost contrast, resize."""
    img = PIL.Image.open(io.BytesIO(img_bytes))
    img = PIL.ImageOps.exif_transpose(img)

    img = img.convert("L")
    img = PIL.ImageOps.autocontrast(img, cutoff=2)
    img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest > _MAX_SIDE:
        scale = _MAX_SIDE / longest
        img = img.resize((int(w * scale), int(h * scale)), PIL.Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buf.getvalue()

"""Dump raw OCR blocks for a screenshot, optionally cropped to chat_region.

Usage:
  python scripts/dump_ocr.py <png>            # full image OCR
  python scripts/dump_ocr.py <png> chat      # crop to config chat_region then OCR
"""
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.rpa.ocr_engine import OcrEngine
import yaml

CFG = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))


def main():
    path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "full"
    img = np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()  # RGB->BGR
    H, W = img.shape[:2]
    print(f"image size (WxH): {W} x {H}   mode={mode}")

    if mode == "chat":
        cr = CFG["chat_region"]
        l = int(W * cr["left_ratio"])
        t = int(H * cr["top_ratio"])
        r = int(W * cr["right_ratio"])
        b = int(H * cr["bottom_ratio"])
        print(f"chat_region crop (l,t,r,b)=({l},{t},{r},{b})")
        img = img[t:b, l:r]

    items = OcrEngine.get({}).extract(img)
    items.sort(key=lambda i: i["center_y"])
    out = []
    for it in items:
        out.append({
            "text": it["text"],
            "conf": round(it["confidence"], 3),
            "cx": it["center_x"],
            "cy": it["center_y"],
            "w": it["width"],
            "h": it["height"],
            "box": it["box"],
        })
    dump = Path(f"data/ocr_dump_{mode}.json")
    dump.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {dump} ({len(out)} blocks)\n")
    for o in out:
        print(f"y={o['cy']:>4} x={o['cx']:>4} w={o['w']:>3} h={o['h']:>2} conf={o['conf']:.2f} | {o['text']}")


if __name__ == "__main__":
    main()

"""Render installer/mockingbird.ico from the logo, in the studio colours.

    python installer/icon.py

Rasterised by headless Edge, which every Windows 11 install has. 32 px and under use the
favicon cut, as the browser tab does; larger sizes use the full mark.
"""

from __future__ import annotations

import base64
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "installer" / "mockingbird.ico"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
# The shell's own sizes at 100-200% scaling; 256 is stored as PNG, the rest as 32-bit DIBs.
SIZES = [16, 20, 24, 32, 40, 48, 64, 256]

# Tile and logo colours are theme.css's studio room: --studio-800, --lit-100, --tally-lit.
JS = r"""
function prep(text, w, h) {
  text = text.replace(/@media[^{]*\{\s*:root\s*\{[^}]*\}\s*\}/, '')
             .replace('#14222b', '#f2f4f7').replace('#d8313a', '#f0646a');
  return text.replace('<svg ', `<svg width="${w}" height="${h}" `);
}
(async () => {
  const out = {};
  for (const size of SIZES) {
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const g = c.getContext('2d');
    g.fillStyle = '#111c22';
    g.beginPath();
    g.roundRect(0, 0, size, size, Math.max(2, size * 0.18));
    g.fill();
    const w = size * 0.8, h = w * 365 / 485;
    const img = new Image();
    img.src = 'data:image/svg+xml;charset=utf-8,' +
      encodeURIComponent(prep(size <= 32 ? SVGS.small : SVGS.brand, w, h));
    await img.decode();
    g.drawImage(img, (size - w) / 2, (size - h) / 2, w, h);
    const rgba = g.getImageData(0, 0, size, size).data;
    let bin = '';
    for (let i = 0; i < rgba.length; i++) bin += String.fromCharCode(rgba[i]);
    out[size] = {png: c.toDataURL('image/png').split(',')[1], rgba: btoa(bin)};
  }
  document.getElementById('out').textContent = JSON.stringify(out);
})();
"""


def render() -> dict[int, dict[str, bytes]]:
    svgs = {"brand": (REPO / "ui/static/brand/mockingbird.svg").read_text(encoding="utf-8"),
            "small": (REPO / "ui/static/favicon.svg").read_text(encoding="utf-8")}
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "icon.html"
        page.write_text("<!doctype html><meta charset=utf-8><pre id=out></pre><script>"
                        "const SVGS=%s;const SIZES=%s;%s</script>"
                        % (json.dumps(svgs), json.dumps(SIZES), JS), encoding="utf-8")
        r = subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run",
                            "--force-device-scale-factor=1", "--user-data-dir=" + str(Path(tmp) / "p"),
                            "--virtual-time-budget=15000", "--dump-dom", page.as_uri()],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    if not m or not m.group(1).strip():
        sys.exit("Edge rendered nothing:\n%s" % (r.stderr or r.stdout)[-2000:])
    return {int(s): {k: base64.b64decode(v) for k, v in e.items()}
            for s, e in json.loads(m.group(1)).items()}


def dib(size: int, rgba: bytes) -> bytes:
    """BITMAPINFOHEADER, bottom-up BGRA, then the 1-bit AND mask set where fully transparent."""
    rows = [rgba[y * size * 4:(y + 1) * size * 4] for y in range(size)]
    xor = b"".join(bytes(b for i in range(0, len(row), 4)
                         for b in (row[i + 2], row[i + 1], row[i], row[i + 3]))
                   for row in reversed(rows))
    stride = (size + 31) // 32 * 4
    mask = bytearray()
    for row in reversed(rows):
        bits = bytearray(stride)
        for x in range(size):
            if row[x * 4 + 3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits
    head = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(xor) + len(mask),
                       0, 0, 0, 0)
    return head + xor + bytes(mask)


def ico(images: dict[int, dict[str, bytes]]) -> bytes:
    blobs = [(s, images[s]["png"] if s >= 256 else dib(s, images[s]["rgba"])) for s in SIZES]
    out = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    for s, blob in blobs:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return out + b"".join(blob for _, blob in blobs)


def main() -> int:
    OUT.write_bytes(ico(render()))
    print("wrote %s (%d bytes, %s px)" % (OUT, OUT.stat().st_size, ", ".join(map(str, SIZES))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

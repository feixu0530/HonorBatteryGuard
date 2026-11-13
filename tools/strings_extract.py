#!/usr/bin/env python3
"""Extract ASCII and UTF-16LE printable strings from a PE/binary file, with offsets.

Usage: python strings_extract.py <input_binary> <output_txt> [min_ascii] [min_utf16]
"""
import re
import sys
from pathlib import Path

ASCII_RE = re.compile(rb"[\x20-\x7e]{%d,}" )
UTF16_RE = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    min_ascii = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    min_utf16 = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    data = src.read_bytes()
    a_re = re.compile(rb"[\x20-\x7e]{" + str(min_ascii).encode() + rb",}")
    w_re = re.compile(rb"(?:[\x20-\x7e]\x00){" + str(min_utf16).encode() + rb",}")
    lines: list[str] = [f"# SOURCE: {src}", f"# SIZE: {len(data)} bytes"]
    for m in a_re.finditer(data):
        lines.append(f"A 0x{m.start():08X} {m.group().decode('ascii', 'replace')}")
    for m in w_re.finditer(data):
        s = m.group().decode("utf-16le", "replace")
        lines.append(f"W 0x{m.start():08X} {s}")
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{src.name}: {len(data)} bytes -> {len(lines) - 2} strings -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

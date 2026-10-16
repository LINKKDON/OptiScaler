#!/usr/bin/env python3
"""Apply Chinese localization to a pristine OptiScaler checkout.

- Applies tools_cn/dict_v10.json to OptiScaler/menu/*.cpp (via apply_dict_v10 logic)
- Embeds the CJK font: adds #include and the merge block to menu_common.cpp
- Idempotent: safe to run multiple times.

Usage: python tools_cn/localize.py  (run from repo root)
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MENU = REPO / "OptiScaler" / "menu"
DICT_PATH = REPO / "tools_cn" / "dict_v10.json"
FONT_HEADER = "font/CJK_Compressed.h"

DICT = json.loads(DICT_PATH.read_text(encoding="utf-8"))
assert all(v for v in DICT.values()), "empty translation value"


def decode_c(s: str) -> str:
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c); i += 1; continue
        i += 1
        if i >= n:
            out.append("\\"); break
        e = s[i]; i += 1
        m = {"n": "\n", "r": "\r", "t": "\t", "a": "\a", "b": "\b",
             "f": "\f", "v": "\v", "0": "\0"}.get(e)
        if m:
            out.append(m)
        elif e in "\\\"'?":
            out.append(e)
        elif e == "x":
            h = s[i:i + 2]; out.append(chr(int(h, 16)) if h else "x"); i += len(h)
        elif e == "u":
            h = s[i:i + 4]; out.append(chr(int(h, 16)) if len(h) == 4 else "u"); i += len(h)
        elif e == "U":
            h = s[i:i + 8]; out.append(chr(int(h, 16)) if len(h) == 8 else "U"); i += len(h)
        else:
            out.append(e)
    return "".join(out)


def encode_c(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def process_line(line: str, in_block: bool):
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if in_block:
            end = line.find("*/", i)
            if end == -1:
                out.append(line[i:]); return "".join(out), True
            out.append(line[i:end + 2]); i = end + 2; in_block = False; continue
        if line.startswith("//", i):
            out.append(line[i:]); return "".join(out), False
        if c == "/" and i + 1 < n and line[i + 1] == "*":
            end = line.find("*/", i + 2)
            if end == -1:
                out.append(line[i:]); return "".join(out), True
            out.append(line[i:end + 2]); i = end + 2; continue
        if c == '"':
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2; continue
                if line[j] == '"':
                    j += 1; break
                j += 1
            value = decode_c(line[i + 1:j - 1])
            if value in DICT:
                out.append('"' + encode_c(DICT[value]) + '"')
            else:
                out.append(line[i:j])
            i = j; continue
        out.append(c); i += 1
    return "".join(out), in_block


def apply_dict(path: Path) -> int:
    data = path.read_bytes()
    had_bom = data.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in data
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    in_block = False
    for li, line in enumerate(lines):
        lines[li], in_block = process_line(line, in_block)
    new_text = "\n".join(lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    # count replacements
    cnt = sum(
        max(0, text.count(f'"{encode_c(k)}"') - new_text.count(f'"{encode_c(k)}"'))
        for k in DICT
    )
    path.write_text(new_text, encoding="utf-8-sig" if had_bom else "utf-8",
                    newline="\r\n" if crlf else "\n")
    return cnt


FONT_MERGE_BLOCK = """
    // [CN] Merge the embedded CJK subset font so the Chinese UI renders correctly.
    {
        ImFontAtlas* atlas = io.Fonts;

        // Ensure a base font exists even when the HQ font is disabled.
        if (atlas->Fonts.empty())
            io.FontDefault = atlas->AddFontDefault();

        ImFontConfig cjkConfig;
        cjkConfig.MergeMode = true;
        cjkConfig.FontNo = 0;
        cjkConfig.OversampleH = 1;
        cjkConfig.OversampleV = 1;

        static const ImWchar cjkGlyphRanges[] = {
            0x0020, 0x00FF, // Basic Latin + Latin-1 Supplement
            0x2000, 0x2BFF, // Punctuation, symbols, arrows, math
            0x3000, 0x303F, // CJK Symbols and Punctuation
            0xFF00, 0xFFEF, // Halfwidth and Fullwidth Forms
            0x4E00, 0x9FAF, // CJK Unified Ideographs
            0,
        };

        atlas->AddFontFromMemoryCompressedTTF(cjk_compressed_data, cjk_compressed_size, fontSize, &cjkConfig,
                                              cjkGlyphRanges);
    }
"""


def apply_font() -> bool:
    """Integrate the CJK font into menu_common.cpp. Returns True if changed."""
    p = MENU / "menu_common.cpp"
    text = p.read_text(encoding="utf-8")
    changed = False

    # 1. Add #include (idempotent)
    inc = '#include "font/CJK_Compressed.h"'
    if inc not in text:
        text = text.replace('#include "font/Hack_Compressed.h"',
                            '#include "font/Hack_Compressed.h"\n' + inc, 1)
        changed = True

    # 2. Add merge block after the font-loading if-block (idempotent)
    if "[CN] Merge the embedded CJK subset font" not in text:
        anchor = "    if (!Config::Instance()->OverlayMenu.value_or_default())"
        if anchor in text:
            text = text.replace(anchor, FONT_MERGE_BLOCK.strip("\n") + "\n\n" + anchor, 1)
            changed = True

    if changed:
        # preserve line endings
        data = p.read_bytes()
        crlf = b"\r\n" in data
        p.write_text(text, encoding="utf-8", newline="\r\n" if crlf else "\n")
    return changed


def main() -> int:
    total = 0
    for f in sorted(MENU.glob("*.cpp")):
        n = apply_dict(f)
        total += n
        print(f"{f.name}: {n} keys translated")
    print(f"Total keys translated: {total}")

    if apply_font():
        print("CJK font integration applied to menu_common.cpp")
    else:
        print("CJK font integration already present")

    # verify the font header exists
    if not (MENU / "font" / "CJK_Compressed.h").exists():
        print("ERROR: OptiScaler/menu/font/CJK_Compressed.h missing!", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

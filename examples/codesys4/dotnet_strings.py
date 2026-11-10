"""Print the user-string heap (#US) literals of .NET assemblies, one per line, prefixed by file name.

Usage: python -I dotnet_strings.py [--grep REGEX] <dll> [<dll> ...]
"""
import re
import struct
import sys
from pathlib import Path


def user_strings(data):
    """Yield string literals from the #US metadata stream of a PE/.NET file."""
    root = data.find(b"BSJB")
    if root < 0:
        return
    version_length = struct.unpack_from("<I", data, root + 12)[0]
    pos = root + 16 + version_length + 2
    stream_count = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    for _ in range(stream_count):
        offset, size = struct.unpack_from("<II", data, pos)
        name_end = data.index(b"\0", pos + 8)
        name = data[pos + 8:name_end].decode("ascii")
        pos = (name_end + 4) & ~3
        if name != "#US":
            continue
        heap = data[root + offset:root + offset + size]
        i = 1
        while i < len(heap):
            first = heap[i]
            if first & 0x80 == 0:
                length, i = first, i + 1
            elif first & 0xC0 == 0x80:
                length, i = ((first & 0x3F) << 8) | heap[i + 1], i + 2
            else:
                length = ((first & 0x1F) << 24) | (heap[i + 1] << 16) | (heap[i + 2] << 8) | heap[i + 3]
                i += 4
            if length > 1:
                yield heap[i:i + length - 1].decode("utf-16-le", errors="replace")
            i += length


def main():
    args = sys.argv[1:]
    pattern = None
    if args[:1] == ["--grep"]:
        pattern, args = re.compile(args[1]), args[2:]
    for path in args:
        for text in user_strings(Path(path).read_bytes()):
            if pattern is None or pattern.search(text):
                print(f"{Path(path).name}: {text!r}")


if __name__ == "__main__":
    main()

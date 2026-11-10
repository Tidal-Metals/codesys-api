"""List the JSON-RPC method names the CODESYS 4 browser UI calls, grouped by service.

The minified bundles build names as `${prefix}.Method` with prefix = "CODESYS.C4.Modules...". Resolve
the prefix variables per file and print every method found.
Usage: python -I extract_rpc_methods.py [<dist dir>]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

DIST = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\CODESYS-4\dist")
PREFIX = re.compile(r'([\w$]+)="(CODESYS\.C4\.[\w.]+)"')
TEMPLATE = re.compile(r'`\$\{([\w$]+)\}\.([A-Z]\w+)`')
LITERAL = re.compile(r'"(CODESYS\.C4\.Modules\.[\w.]+\.[A-Z]\w+)"')


def main():
    methods = defaultdict(set)
    for path in DIST.rglob("*"):
        if path.suffix not in (".js", ".mjs"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        prefixes = dict(PREFIX.findall(text))
        for var, name in TEMPLATE.findall(text):
            if var in prefixes:
                methods[prefixes[var]].add(name)
        for full in LITERAL.findall(text):
            service, _, name = full.rpartition(".")
            methods[service].add(name)
    for service in sorted(methods):
        print(service)
        for name in sorted(methods[service]):
            print(f"    {name}")


if __name__ == "__main__":
    main()

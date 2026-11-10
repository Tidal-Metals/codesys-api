"""Turn docs/codesys4/schemas/_raw.json (from dump_schemas.py) into one named .schema.json per file pattern.

Usage: python split_schemas.py <schemas dir>
"""
import json
import re
import sys
from pathlib import Path


def main(folder):
    folder = Path(folder)
    for old in folder.glob("schema*.json"):
        old.unlink()
    raw = json.loads((folder / "_raw.json").read_text(encoding="utf-8"))
    for entry in (e for batch in raw for e in batch):
        pattern = entry["uriPattern"]
        schema = json.loads(entry["schemaString"])
        name = re.sub(r"[^A-Za-z0-9.]+", "_", pattern.replace("**/", "").replace("*", "x")).strip("_")
        path = folder / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        print(f"{pattern:45} -> {path.name:45} {schema.get('title', '')}")
    (folder / "_raw.json").unlink()


if __name__ == "__main__":
    main(sys.argv[1])

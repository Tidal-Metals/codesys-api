#!/usr/bin/env python
"""Execute a script through the already-running PERSISTENT_SESSION.py IDE bridge."""

import argparse
import json
import logging
from pathlib import Path

from script_executor import ScriptExecutor


def execute(code, timeout=60):
    # The legacy runner separates globals and locals. A module-style namespace
    # lets functions in a submitted script resolve its other functions/imports.
    wrapped = "_scope = dict(globals())\nexec(%r, _scope, _scope)\nresult = _scope.get('result', {'success': False, 'error': 'Script did not set result'})\n" % code
    root = Path(__file__).resolve().parent
    return ScriptExecutor(str(root / "requests"), str(root / "results")).execute_script(wrapped, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    result = execute(args.script.read_text(encoding="utf-8"), args.timeout)
    print(json.dumps(result, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

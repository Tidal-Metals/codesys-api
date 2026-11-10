"""Resolve a CODESYS 4 application's libraries, importing any missing ones from the CODESYS 3 library store.

Runs `c4-cli library resolve`; for each "'<Name>, <version> (<Company>)': Library not found" it copies the
matching compiled library from C:\\ProgramData\\CODESYS\\Managed Libraries into the CODESYS 4 user
repository with `c4-cli librepo install`, then resolves again until nothing more can be imported.

Usage: python import_missing_libraries.py <path to Application.iecapp>
"""
import re
import subprocess
import sys
from pathlib import Path

C4_CLI = r"C:\Program Files\CODESYS-4\c4-cli.exe"
C3_STORE = Path(r"C:\ProgramData\CODESYS\Managed Libraries")
C4_REPO = Path.home() / r"AppData\Local\CODESYS-4\managed-libraries"
MISSING = re.compile(r"to '([^,']+), ([\d.]+) \(([^)]+)\)': Library not found")
LIBRARY_SUFFIXES = (".compiled-library-v3", ".compiled-library-ge33", ".compiled-library", ".library")


def run_cli(*args):
    result = subprocess.run([C4_CLI, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def find_in_c3_store(name, version, company):
    for folder in (C3_STORE / company / name).glob("*"):
        if folder.name.rstrip(".0") == version.rstrip(".0") or folder.name.startswith(version + "."):
            for file in sorted(folder.iterdir()):
                if file.name.endswith(LIBRARY_SUFFIXES):
                    return file
    return None


def main(app_path):
    attempted = set()
    while True:
        code, output = run_cli("library", "resolve", app_path)
        missing = set(MISSING.findall(output)) - attempted
        if code == 0 or not missing:
            print(f"resolve exit={code}; still missing: {sorted(set(MISSING.findall(output)))}")
            return code
        for name, version, company in sorted(missing):
            attempted.add((name, version, company))
            source = find_in_c3_store(name, version, company)
            if source is None:
                print(f"not in CODESYS 3 store: {name} {version} ({company})")
                continue
            install_code, _ = run_cli("librepo", "install", str(C4_REPO), "--skip-existing", str(source))
            print(f"imported {name} {version} ({company}) from {source.parent} exit={install_code}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

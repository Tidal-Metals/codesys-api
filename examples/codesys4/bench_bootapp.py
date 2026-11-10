"""Time `c4-cli bootapp compile`, check output determinism, and run builds in parallel.

Usage: python bench_bootapp.py <device project dir (.fbsdev)> <scratch dir>
Copies the project to <scratch>/copyN so parallel builds don't share a folder.
"""
import hashlib
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

C4_CLI = r"C:\Program Files\CODESYS-4\c4-cli.exe"


def compile_app(project, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result = subprocess.run([C4_CLI, "bootapp", "compile", str(project / "Application.iecapp"), str(out_dir)],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    elapsed = time.perf_counter() - started
    summary = [line for line in result.stdout.splitlines() if "Build complete" in line or "Compilation" in line]
    return elapsed, result.returncode, summary


def digest(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in sorted(folder.glob("*")) if p.is_file()}


def main(project, scratch):
    project, scratch = Path(project).resolve(), Path(scratch).resolve()
    if scratch.exists():
        shutil.rmtree(scratch)
    copies = []
    for n in range(2):
        copy = scratch / f"copy{n}" / project.name
        shutil.copytree(project, copy, ignore=shutil.ignore_patterns(".bootapp"))
        copies.append(copy)
    print("sequential, same project:")
    for n in range(2):
        elapsed, code, summary = compile_app(copies[0], scratch / f"seq{n}")
        print(f"  run {n}: {elapsed:.1f}s exit={code} {summary}")
    print("  outputs identical:", digest(scratch / "seq0") == digest(scratch / "seq1"), digest(scratch / "seq0"))
    print("one-file change:")
    st = next((copies[0] / "Application.iecapp^").glob("*.st"))
    st.write_text(st.read_text().replace("> 10", "> 11"))
    elapsed, code, summary = compile_app(copies[0], scratch / "changed")
    print(f"  {elapsed:.1f}s exit={code} {summary}")
    print("parallel, two copies:")
    started = time.perf_counter()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda c: compile_app(c[1], scratch / f"par{c[0]}"), enumerate(copies)))
    for n, (elapsed, code, summary) in enumerate(results):
        print(f"  copy {n}: {elapsed:.1f}s exit={code} {summary}")
    print(f"  wall: {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

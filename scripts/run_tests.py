"""Run the offline test suite in logical groups, one pytest process per group, so memory is returned between them.

Usage: python scripts/run_tests.py [GROUP ...] [--list] [-- PYTEST_ARGS ...]

With no group, every group runs in order and the script exits non-zero if any failed. Each group gets its own
--basetemp under .pytest_tmp, so groups never share temporary files. Extra arguments after -- go to every pytest
call, for example `-- -x` or `-- -k entity`.
"""

import argparse
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# Grouped by the part of the system they cover. Modules that import fixtures from another test module still work
# alone, because pytest puts tests/ on the import path.
GROUPS = {
    "core": ["test_schemas.py", "test_settings.py", "test_registry.py", "test_safety.py", "test_normalization.py",
             "test_segmentation.py", "test_loaders.py", "test_ingest.py", "test_online.py", "test_chunking.py", "test_scans.py"],
    "retrieval": ["test_versioning.py", "test_indexing.py", "test_cli.py", "test_hybrid.py", "test_rerank.py"],
    "answering": ["test_evaluation.py", "test_generation.py", "test_citations.py", "test_sufficiency.py", "test_profiling.py"],
    "enrichment": ["test_entities.py", "test_keyphrases.py", "test_nlp_gold.py", "test_enrichment.py", "test_classification.py",
                   "test_enrichment_eval.py"],
}


def ungrouped() -> list[str]:
    grouped = {name for files in GROUPS.values() for name in files}
    return sorted(path.name for path in (ROOT / "tests").glob("test_*.py") if path.name not in grouped)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("groups", nargs="*", metavar="GROUP", help=f"one of: {', '.join(GROUPS)}")
    parser.add_argument("--list", action="store_true", help="show the groups and their modules")
    args = parser.parse_args(argv)
    unknown = [name for name in args.groups if name not in GROUPS]
    if unknown:
        parser.error(f"unknown group {', '.join(unknown)}; choose from {', '.join(GROUPS)}")
    missing = ungrouped()
    if args.list:
        for name, files in GROUPS.items():
            print(f"{name}: {' '.join(files)}")
        if missing:
            print(f"not grouped: {' '.join(missing)}")
        return 0
    if missing:
        # A new test module must be added to a group, or it would silently never run here.
        print(f"Test modules not in any group: {', '.join(missing)}. Add them to GROUPS in scripts/run_tests.py.", file=sys.stderr)
        return 2
    results = []
    for name in args.groups or list(GROUPS):
        files = [f"tests/{item}" for item in GROUPS[name] if (ROOT / "tests" / item).exists()]
        command = [sys.executable, "-m", "pytest", *files, f"--basetemp=.pytest_tmp/{name}", "-p", "no:cacheprovider", *extra]
        print(f"== {name}: {len(files)} modules", flush=True)
        started = time.perf_counter()
        code = subprocess.run(command, cwd=ROOT).returncode
        results.append((name, code, time.perf_counter() - started))
    print("\n== summary")
    for name, code, seconds in results:
        print(f"{name:<12} {'passed' if code == 0 else f'FAILED (exit {code})':<18} {seconds:7.1f} s")
    return 0 if all(code == 0 for _, code, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

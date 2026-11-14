"""Phase 11 secret and private-text scan (P11-7, AC-23.4).

Usage: python scripts/scan_secrets.py [--config FILE] [--json]

1. Secrets: key-shaped strings in every tracked file, the whole git history (`git log -p --all`), and the local
   runtime outputs under <data>/logs and <data>/evaluation. A hit is reported by place and pattern, with the
   matched value masked, so the scan never prints a secret again. Every hit is reviewed by hand.
2. Private supplement: no passage of any chunk of a document outside the frozen evaluation manifest may appear in a
   tracked file or in the history. Both sides are reduced to lowercase letters and digits, after decoding JSON
   string escapes, and a shared run of at least --min-run such characters (160, about 200 characters of prose)
   is a leak. Only counts and file names are printed, never the text.

Exit status 0 when nothing is found, 1 when anything is.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    # Each prefix must start a token, so prose such as "task-scheduling-..." is not taken for "sk-...".
    "openai_key": r"(?<![A-Za-z0-9_\-])sk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}",
    "anthropic_key": r"(?<![A-Za-z0-9_\-])sk-ant-[A-Za-z0-9_\-]{20,}",
    "huggingface_token": r"(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}",
    "github_token": r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})",
    "aws_access_key": r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])",
    "google_api_key": r"(?<![A-Za-z0-9_])AIza[0-9A-Za-z_\-]{35}",
    "slack_token": r"(?<![A-Za-z0-9_])xox[abposr]-[A-Za-z0-9\-]{10,}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "key_assignment": r"(?i)\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*[=:]\s*['\"]?[A-Za-z0-9_\-+/=.]{16,}",
}
COMPILED = {name: re.compile(pattern) for name, pattern in PATTERNS.items()}
WINDOW = 40
MIN_RUN = 160
ESCAPES = re.compile(r"\\u([0-9a-fA-F]{4})|\\[nrtbf\"\\/]")


def mask(value: str) -> str:
    return f"{value[:4]}...({len(value)} chars)"


def secret_hits(text: str, place: str) -> list[dict]:
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in COMPILED.items():
            for found in pattern.finditer(line):
                hits.append({"place": place, "line": number, "pattern": name, "value": mask(found.group(0))})
    return hits


def normalized(text: str) -> str:
    """Lowercase letters and digits only, after decoding JSON string escapes, so a JSON-escaped copy still matches."""
    decoded = ESCAPES.sub(lambda match: chr(int(match.group(1), 16)) if match.group(1) else " ", text)
    return re.sub(r"[^0-9a-z]+", "", decoded.casefold())


def private_windows(texts: list[str]) -> set[int]:
    windows = set()
    for text in texts:
        value = normalized(text)
        windows.update(hash(value[index:index + WINDOW]) for index in range(len(value) - WINDOW + 1))
    return windows


def longest_shared_run(text: str, windows: set[int]) -> int:
    """Length in normalized characters of the longest run of text shared with the private windows."""
    value = normalized(text)
    best = run = 0
    for index in range(len(value) - WINDOW + 1):
        if hash(value[index:index + WINDOW]) in windows:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best + WINDOW - 1 if best else 0


def git(*arguments) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, check=True).stdout.decode("utf-8", "replace")


def tracked_files() -> dict[str, str]:
    files = {}
    for name in git("ls-files", "-z").split("\0"):
        if not name:
            continue
        path = ROOT / name
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        files[name] = data.decode("utf-8", "replace")
    return files


def history() -> dict[str, str]:
    """Each commit's patch, keyed by its short hash, from every ref."""
    commits = git("rev-list", "--all").split()
    return {commit[:12]: git("show", "--no-color", "--format=%H%n%an%n%s%n%b", "-p", commit) for commit in commits}


def runtime_outputs(data_directory: Path) -> dict[str, str]:
    files = {}
    for folder in ("logs", "evaluation"):
        for path in sorted((data_directory / folder).rglob("*")) if (data_directory / folder).exists() else []:
            if path.is_file() and path.suffix in (".log", ".jsonl", ".json", ".md", ".txt"):
                files[str(path.relative_to(data_directory))] = path.read_bytes().decode("utf-8", "replace")
    return files


def private_texts(settings, registry, manifest_path: Path) -> list[str]:
    from techdocqa.ingestion.chunks import stored_chunks
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public = {item["source_key"] for item in manifest["documents"] if item["evaluation_included"]}
    return [chunk["text"] for record in registry.eligible_versions() if record.source_key not in public
            for chunk in stored_chunks(record, settings)]


def scan(settings, registry, manifest_path: Path, min_run: int = MIN_RUN) -> dict:
    files, commits = tracked_files(), history()
    outputs = runtime_outputs(Path(settings.data_directory))
    hits = [hit for name, text in files.items() for hit in secret_hits(text, f"tracked {name}")]
    hits += [hit for commit, text in commits.items() for hit in secret_hits(text, f"commit {commit}")]
    hits += [hit for name, text in outputs.items() for hit in secret_hits(text, f"data {name}")]
    texts = private_texts(settings, registry, manifest_path)
    windows = private_windows(texts)
    leaks = []
    for kind, items in (("tracked", files), ("commit", commits)):
        for name, text in items.items():
            run = longest_shared_run(text, windows)
            if run >= min_run:
                leaks.append({"place": f"{kind} {name}", "longest_shared_run": run})
    return {"secrets": {"tracked_files": len(files), "commits": len(commits), "runtime_outputs": len(outputs),
                        "patterns": sorted(PATTERNS), "hits": hits},
            "private_supplement": {"chunks": len(texts), "normalized_characters": sum(len(normalized(text)) for text in texts),
                                   "window": WINDOW, "min_run": min_run, "leaks": leaks}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "default.toml")
    parser.add_argument("--manifest", type=Path, default=ROOT / "datasets" / "corpus_manifest.json")
    parser.add_argument("--min-run", type=int, default=MIN_RUN)
    args = parser.parse_args(argv)
    from techdocqa.registry import Registry
    from techdocqa.settings import load_settings
    settings = load_settings(args.config)
    with Registry(Path(settings.data_directory) / "registry.sqlite3") as registry:
        report = scan(settings, registry, args.manifest, args.min_run)
    print(json.dumps(report, indent=1))
    return 1 if report["secrets"]["hits"] or report["private_supplement"]["leaks"] else 0


if __name__ == "__main__":
    sys.exit(main())

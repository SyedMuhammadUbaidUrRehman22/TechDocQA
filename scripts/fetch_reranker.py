"""Download the pinned reranker files named in [retrieval.reranker] (P10-5) and verify each SHA-256.

Run once from the repository root; the reranker runs offline afterwards:
    .venv\\Scripts\\python.exe scripts\\fetch_reranker.py [--config config/default.toml]

Only the files pinned in `files_sha256` are fetched, at the pinned revision, from huggingface.co, with no credentials
sent. They go to <data_directory>/models/<model with / as -->/<revision>, which must not exist yet. A file whose hash
does not match is deleted and the script fails.
"""

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

from techdocqa.retrieval.cross_encoder import REQUIRED_FILES, model_directory
from techdocqa.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("config/default.toml"))
    settings = load_settings(parser.parse_args().config)
    reranker = settings.retrieval.reranker
    if not (reranker.model and reranker.revision and set(REQUIRED_FILES) <= set(reranker.files_sha256)):
        print("No reranker is pinned in [retrieval.reranker].", file=sys.stderr)
        return 2
    target = model_directory(settings)
    if target.exists():
        print(f"{target} already exists; nothing downloaded.", file=sys.stderr)
        return 2
    for name, expected in sorted(reranker.files_sha256.items()):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(f"https://huggingface.co/{reranker.model}/resolve/{reranker.revision}/{name}",
                                         headers={"User-Agent": "python-urllib"})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, open(path, "wb") as handle:
            while block := response.read(1 << 20):
                digest.update(block)
                handle.write(block)
        if digest.hexdigest() != expected:
            path.unlink()
            print(f"{name}: SHA-256 does not match its pin; deleted.", file=sys.stderr)
            return 1
        print(f"{name}: verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

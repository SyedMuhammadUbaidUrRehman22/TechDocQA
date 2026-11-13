"""The local cross-encoder reranker (P10-5): an ONNX export on onnxruntime and tokenizers, with no torch and no network.

The files are read from `<data_directory>/models/<model with / as -->/<revision>`. Each file named in
`[retrieval.reranker] files_sha256` must match its pinned hash before a session opens, so the scale the reranker's
thresholds were calibrated on cannot change silently. Each (query, chunk) pair is scored alone, on a fixed number of
CPU threads, so padding and batch composition cannot move a score: a score depends only on its pair.
"""

from functools import lru_cache
import hashlib
import json
from pathlib import Path

from techdocqa.errors import TechDocQAError

MODEL_FILE = "onnx/model.onnx"
TOKENIZER_FILE = "tokenizer.json"
CONFIG_FILE = "config.json"
REQUIRED_FILES = (MODEL_FILE, TOKENIZER_FILE, CONFIG_FILE)
# Query and chunk are encoded as one pair and cut together to max_length tokens, longest sequence first, so a
# 1,000-character query still fits; a 1,000-character chunk plus a short query is within 512 tokens.
TRUNCATION = "longest_first"
# Fixed, not taken from the machine: the gate measured 1 and 4 threads giving identical scores, and 4 meets NFR-02.
THREADS = 4
INPUTS = ("input_ids", "attention_mask", "token_type_ids")


def unavailable(message: str) -> TechDocQAError:
    return TechDocQAError("RERANKER_UNAVAILABLE", message, stage="rerank")


def model_directory(settings) -> Path:
    reranker = settings.retrieval.reranker
    return Path(settings.data_directory) / "models" / reranker.model.replace("/", "--") / (reranker.revision or "unpinned")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


class OnnxCrossEncoder:
    def __init__(self, directory: Path, files_sha256: dict[str, str], max_length: int):
        if not set(REQUIRED_FILES) <= set(files_sha256):
            raise unavailable("The reranker configuration does not pin every file it needs.")
        for name, expected in sorted(files_sha256.items()):
            path = directory / name
            if not path.is_file() or sha256(path) != expected:
                raise unavailable("The reranker's files are missing or do not match their pinned hashes.")
        try:
            import numpy
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError:
            raise unavailable("The reranker runtime is not installed.") from None
        config = json.loads((directory / CONFIG_FILE).read_text(encoding="utf-8"))
        if max_length > config.get("max_position_embeddings", 0):
            raise unavailable("The reranker's max_length exceeds the model's position limit.")
        tokenizer = Tokenizer.from_file(str(directory / TOKENIZER_FILE))
        tokenizer.no_padding()
        tokenizer.enable_truncation(max_length, strategy=TRUNCATION)
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = THREADS
        options.inter_op_num_threads = THREADS
        options.log_severity_level = 3
        session = onnxruntime.InferenceSession(str(directory / MODEL_FILE), options, providers=["CPUExecutionProvider"])
        names = [item.name for item in session.get_inputs()]
        if not set(names) <= set(INPUTS) or "input_ids" not in names:
            raise unavailable("The reranker model has unexpected inputs.")
        self.numpy, self.tokenizer, self.session, self.inputs = numpy, tokenizer, session, names

    def score(self, query: str, texts: list[str]) -> list[float]:
        scores = []
        for text in texts:
            encoding = self.tokenizer.encode(query, text)
            values = {"input_ids": encoding.ids, "attention_mask": encoding.attention_mask, "token_type_ids": encoding.type_ids}
            feed = {name: self.numpy.array([values[name]], dtype=self.numpy.int64) for name in self.inputs}
            logits = self.session.run(None, feed)[0]
            scores.append(float(logits.reshape(-1)[0]))
        return scores


@lru_cache(maxsize=2)
def load(directory: str, files: tuple[tuple[str, str], ...], max_length: int) -> OnnxCrossEncoder:
    """One session per process and identity; hashes are checked when it is first loaded."""
    return OnnxCrossEncoder(Path(directory), dict(files), max_length)


def from_settings(settings) -> OnnxCrossEncoder:
    reranker = settings.retrieval.reranker
    if not reranker.revision:
        raise unavailable("The reranker revision is not pinned.")
    return load(str(model_directory(settings)), tuple(sorted(reranker.files_sha256.items())), reranker.max_length)

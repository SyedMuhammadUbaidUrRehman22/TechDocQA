"""The Phase 11 secret and private-text scan (P11-7): patterns, masking and passage matching, offline."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scan_secrets", ROOT / "scripts" / "scan_secrets.py")
scan_secrets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_secrets)


def fake(*parts: str) -> str:
    """Joined at run time, so no key-shaped literal sits in this file for the scan of tracked files to find."""
    return "".join(parts)


def test_every_secret_pattern_is_found_and_masked():
    samples = {
        "openai_key": fake("s", "k-proj-", "Ab3" * 10), "anthropic_key": fake("s", "k-ant-", "x9Y" * 10),
        "huggingface_token": fake("h", "f_", "Q7w" * 12), "github_token": fake("g", "hp_", "Z4r" * 13),
        "aws_access_key": fake("AK", "IA", "J7QX4Z2B9L3M8N5P"), "google_api_key": fake("AI", "za", "S" * 35),
        "slack_token": fake("xo", "xb-", "1234567890-abcdef"), "private_key": fake("-----BEGIN RSA ", "PRIVATE KEY-----"),
        "key_assignment": fake("OPENAI_API", "_KEY=", "r4nd0mV4lu3s0mething"),
    }
    assert set(samples) == set(scan_secrets.PATTERNS)
    for name, value in samples.items():
        hits = scan_secrets.secret_hits(f"before\n  {value}  \n", "tracked x.py")
        assert any(hit["pattern"] == name for hit in hits), name
        assert all(hit["line"] == 2 and value not in hit["value"] and hit["value"].endswith("chars)") for hit in hits)


def test_ordinary_technical_text_is_not_taken_for_a_secret():
    text = ("Airflow handles task-scheduling-and-dependencies-for-every-dag.\n"
            'chat_tokenizer = "byte-bpe"\nmax_output_tokens = 512\n"prompt_tokens": 1822\n'
            'embedding_model_digest = "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"\n'
            "Use disk-based-storage-for-the-write-ahead-log and pass --api-key-file instead.")
    assert scan_secrets.secret_hits(text, "tracked docs.md") == []


def test_a_private_passage_is_found_even_when_json_escaped():
    private = ("Replication means keeping a copy of the same data on multiple machines that are connected via a network. "
               "There are several reasons why you might want to replicate data: to keep data geographically close to users, "
               "to allow the system to continue working even if some of its parts have failed, and to scale out reads.")
    windows = scan_secrets.private_windows([private])
    excerpt = private[40:260]
    escaped = json.dumps({"text": "The answer: “" + excerpt.replace(" ", "\n", 3) + "”"})
    assert scan_secrets.longest_shared_run(escaped, windows) >= scan_secrets.MIN_RUN
    # A short quotation, under the minimum run, is not a leak.
    assert scan_secrets.longest_shared_run(json.dumps(private[:120]), windows) < scan_secrets.MIN_RUN
    assert scan_secrets.longest_shared_run("Kafka brokers replicate partitions across the cluster.", windows) == 0
    assert scan_secrets.normalized(json.dumps("A’b\nC\\d")) == scan_secrets.normalized("A’b\nC\\d")

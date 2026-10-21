import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest
import urllib3

from techdocqa.cli import main
from techdocqa.errors import TechDocQAError
from techdocqa.ingestion import fetching, online
from techdocqa.ingestion.html import extract_html
from techdocqa.ingestion.online_worker import process_page
from techdocqa.registry import Registry
from techdocqa.settings import OnlineSource, load_settings

ROOT = Path(__file__).resolve().parents[1]
CODE = '  config = {"max.poll.interval.ms": 300000}\n  print("C++ HTTP/2 std::vector<int> --max-poll-records=500")\n'
HTML = ('<!doctype html><html><head><title>Kafka Consumer Configuration</title></head><body>'
        '<nav>NAV_MARKER</nav><header>HEADER_MARKER</header><aside>ASIDE_MARKER</aside>'
        '<div id="cookie-banner">COOKIE_MARKER</div><main><h1>Consumers</h1><h2>Settings</h2>'
        '<p>Set <code>max.poll.interval.ms</code> carefully. Kafka supports consumers, producers, '
        'brokers, and durable event streams. These documentation examples preserve technical '
        'identifiers and source structure for later retrieval.</p><pre><code>'
        + CODE.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') + '</code></pre>'
        '<ul><li>TTL and key-value</li></ul><table><tr><th>name</th><th>default</th></tr>'
        '<tr><td>poll</td><td>500</td></tr></table></main><footer>FOOTER_MARKER</footer>'
        '<script>BAD_SCRIPT</script><style>BAD_STYLE</style></body></html>').encode()


class Response:
    def __init__(self, body=HTML, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}
        self.closed = False
        self.reads = []

    def read(self, amount, **kwargs):
        self.reads.append(amount)
        return self.body[:amount]

    def close(self):
        self.closed = True


@pytest.fixture
def online_settings(settings):
    configured = load_settings(ROOT / "config/default.toml")
    settings.online = configured.online
    return settings


@pytest.fixture
def network(monkeypatch):
    queue, pools, requests, sleeps = [], [], [], []
    monkeypatch.setattr(fetching.socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(fetching.time, "sleep", sleeps.append)
    class Pool:
        def __init__(self, address, **kwargs):
            pools.append((address, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def urlopen(self, method, path, **kwargs):
            requests.append((method, path, kwargs))
            assert queue, "Unexpected extra HTTP request"
            result = queue.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
    monkeypatch.setattr(fetching.urllib3, "HTTPSConnectionPool", Pool)
    return queue, pools, requests, sleeps


@pytest.fixture
def inline_worker(monkeypatch):
    def run(source, url, settings, directory):
        return process_page(source, url, settings.online, settings.ingestion.max_file_bytes,
                            settings.ingestion.min_text_characters, directory)
    monkeypatch.setattr(online, "run_page_worker", run)


@pytest.mark.parametrize("source_id", ["apache_kafka", "apache_airflow"])
def test_official_source_ingestion(source_id, online_settings, registry, network, inline_worker):
    response = Response(headers={"ETag": '"abc"', "Last-Modified": "Wed, 21 Oct 2026 00:00:00 GMT"})
    network[0].append(response)
    result = online.ingest_online([source_id], [], online_settings, registry)
    assert (result.pages_attempted, result.pages_succeeded, result.pages_failed) == (1, 1, 0)
    assert result.run.status == "completed"
    attempt = result.outcomes[0]
    record = registry.get_document(attempt.result.document_id)
    provenance = record.online
    source = next(item for item in online_settings.online.sources if item.source_id == source_id)
    assert record.source_key == record.source_url == provenance.canonical_url == source.pages[0]
    assert record.technology == source.technology and record.title == "Kafka Consumer Configuration"
    assert record.doc_type == "html" and record.raw_hash == hashlib.sha256(HTML).hexdigest()
    assert record.content_hash is None and not record.finalized and not record.is_active
    assert provenance.retrieved_at.endswith("+00:00") and provenance.http_status == 200
    assert provenance.source_id == source_id and provenance.content_type == "text/html"
    assert provenance.snapshot_id == record.raw_hash and provenance.usage_status == "unverified"
    assert provenance.etag == '"abc"' and provenance.last_modified is not None
    assert provenance.normalized_hash is None and provenance.extraction_status == "extracted"
    assert not Path(provenance.snapshot_path).is_absolute()
    assert (Path(online_settings.data_directory) / provenance.snapshot_path).read_bytes() == HTML
    text = (Path(online_settings.data_directory) / provenance.extracted_path).read_text(encoding="utf-8")
    assert CODE in text and "max.poll.interval.ms" in text and "TTL and key-value" in text
    assert all(marker not in text for marker in ["NAV_MARKER", "FOOTER_MARKER", "COOKIE_MARKER", "BAD_SCRIPT", "BAD_STYLE", "ASIDE_MARKER"])
    assert provenance.headings[1]["section_path"] == ["Consumers", "Settings"]
    assert any(text[span["start"]:span["end"]] == CODE for span in provenance.code_spans if span["kind"] == "block")
    assert provenance.extraction_dependencies["langchain-community"] == "0.4.2"
    assert len(provenance.configuration_id) == 64
    assert response.closed and network[1][0][0] == "93.184.216.34"
    assert network[1][0][1]["server_hostname"] == network[1][0][1]["assert_hostname"] == source.pages[0].split("/")[2]
    assert network[2][0][2]["redirect"] is False and network[2][0][2]["retries"] is False
    assert network[2][0][2]["headers"]["Accept-Encoding"] == "identity"
    manifest = json.loads((Path(online_settings.data_directory) / result.manifest_path).read_text())
    assert manifest["status"] == "draft" and manifest["dataset_id"] is None
    assert manifest["documents"][0]["online"] == provenance.model_dump()
    assert manifest["documents"][0]["format"] == "html" and len(manifest["retrievals"]) == 1


def test_enable_catalogued_postgresql_without_adapter_changes(online_settings, registry, network, inline_worker):
    source = next(item for item in online_settings.online.sources if item.source_id == "postgresql")
    assert online.ingest_online(["postgresql"], [], online_settings, registry).outcomes[0].error.code == "SOURCE_NOT_APPROVED"
    source.enabled = True
    network[0].append(Response())
    result = online.ingest_online(["postgresql"], [], online_settings, registry)
    assert registry.get_document(result.outcomes[0].result.document_id).technology == "PostgreSQL"


@pytest.mark.parametrize("value", [
    "https://example.org/docs/", "https://kafka.apache.org/private/", "https://kafka.apache.org/43/not-configured/",
    "http://kafka.apache.org/documentation/", "file:///etc/passwd", "https://user:password@kafka.apache.org/documentation/",
    "https://127.0.0.1/", "https://10.1.2.3/", "https://169.254.169.254/", "https://[::1]/",
    "https://kafka.apache.org/documentation/../private/", "https://kafka.apache.org/documentation/%2e%2e/private/",
    "https://kafka.apache.org/documentation/?token=private", "https://kafka.apache.org:8443/documentation/",
])
def test_unapproved_urls_fail_without_network(value, online_settings, registry):
    result = online.ingest_online([], [value], online_settings, registry)
    assert result.pages_failed == 1 and result.outcomes[0].error.code == "URL_NOT_ALLOWED"
    assert value not in result.model_dump_json()


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1", "2001:db8::1", "::ffff:127.0.0.1"])
def test_public_host_resolving_to_nonpublic_address_is_blocked(address, online_settings, network, monkeypatch):
    monkeypatch.setattr(fetching.socket, "getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", (address, 443))])
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(online_settings.online.sources[0].pages[0], online_settings.online.sources[0])
    assert caught.value.response.error.code == "URL_NOT_ALLOWED" and not network[2]


def test_mixed_public_and_private_dns_answers_fail_closed(online_settings, network, monkeypatch):
    monkeypatch.setattr(fetching.socket, "getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", (address, 443)) for address in ["93.184.216.34", "192.168.1.1"]])
    with pytest.raises(TechDocQAError):
        fetching.public_addresses("kafka.apache.org")
    assert not network[2]


@pytest.mark.parametrize("destination", ["https://evil.example/docs", "http://kafka.apache.org/43/", "https://kafka.apache.org/admin/", "https://127.0.0.1/", "https://169.254.169.254/"])
def test_redirect_destinations_are_validated(destination, online_settings, network):
    network[0].append(Response(status=302, headers={"Location": destination}))
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(online_settings.online.sources[0].pages[0], online_settings.online.sources[0])
    assert caught.value.response.error.code == "URL_NOT_ALLOWED" and len(network[2]) == 1


def test_redirect_dns_rebinding_is_blocked(online_settings, network, monkeypatch):
    calls = []
    def resolve(*args, **kwargs):
        calls.append(args)
        return [(0, 0, 0, "", ("93.184.216.34" if len(calls) == 1 else "127.0.0.1", 443))]
    monkeypatch.setattr(fetching.socket, "getaddrinfo", resolve)
    network[0].append(Response(status=302, headers={"Location": "/43/"}))
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(online_settings.online.sources[0].pages[0], online_settings.online.sources[0])
    assert caught.value.response.error.code == "URL_NOT_ALLOWED" and len(network[2]) == 1


def test_valid_redirect_retains_requested_identity(online_settings, registry, network, inline_worker):
    network[0].extend([Response(status=301, headers={"Location": "/43/"}), Response()])
    result = online.ingest_online(["apache_kafka"], [], online_settings, registry)
    provenance = result.outcomes[0].online
    assert provenance.final_url == "https://kafka.apache.org/43/"
    assert provenance.canonical_url == online_settings.online.sources[0].pages[0]


def test_redirect_limit(online_settings, network):
    network[0].extend(Response(status=302, headers={"Location": "/43/"}) for _ in range(4))
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(online_settings.online.sources[0].pages[0], online_settings.online.sources[0])
    assert caught.value.response.error.code == "REDIRECT_LIMIT" and len(network[2]) == 4


@pytest.mark.parametrize("headers,body,code", [
    ({"Content-Length": "10001"}, b"x", "FILE_TOO_LARGE"),
    ({}, b"x" * 10001, "FILE_TOO_LARGE"),
    ({"Content-Type": "application/pdf"}, HTML, "UNSUPPORTED_CONTENT_TYPE"),
    ({"Content-Type": ""}, HTML, "UNSUPPORTED_CONTENT_TYPE"),
    ({"Content-Encoding": "gzip"}, HTML, "UNSUPPORTED_CONTENT_ENCODING"),
    ({"Content-Length": "invalid"}, HTML, "INVALID_RESPONSE"),
])
def test_response_policy(headers, body, code, online_settings, network):
    response = Response(body, headers=headers)
    network[0].append(response)
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(online_settings.online.sources[0].pages[0], online_settings.online.sources[0])
    assert caught.value.response.error.code == code and response.closed


@pytest.mark.parametrize("status,code,retryable,count", [(404, "HTTP_NOT_FOUND", False, 1), (429, "HTTP_RATE_LIMITED", True, 3), (503, "HTTP_SERVER_ERROR", True, 3)])
def test_http_errors_and_retry_exhaustion(status, code, retryable, count, online_settings, network):
    network[0].extend(Response(status=status) for _ in range(count))
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(online_settings.online.sources[0].pages[0], online_settings.online.sources[0])
    assert caught.value.response.error.code == code and caught.value.response.error.retryable == retryable
    assert len(network[2]) == count


def test_timeout_retries_are_bounded_and_sensitive_diagnostics_hidden(online_settings, registry, network, inline_worker, tmp_path):
    marker = "private-" + tmp_path.name
    network[0].extend(urllib3.exceptions.ReadTimeoutError(None, "/", marker) for _ in range(3))
    result = online.ingest_online(["apache_kafka"], [], online_settings, registry)
    assert result.outcomes[0].error.code == "FETCH_TIMEOUT" and result.outcomes[0].error.retryable
    assert marker not in result.model_dump_json() and len(network[2]) == 3


def test_rate_limit_then_success_and_conservative_pacing(online_settings, network):
    network[0].extend([Response(status=429, headers={"Retry-After": "2"}), Response()])
    source = online_settings.online.sources[0]
    assert fetching.SafeFetcher(online_settings.online, 10000).fetch(source.pages[0], source).body == HTML
    assert 2 in network[3] and len(network[2]) == 2


def test_long_retry_after_defers_without_retrying_early(online_settings, network):
    network[0].append(Response(status=429, headers={"Retry-After": "300"}))
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(online_settings.online.sources[0].pages[0], online_settings.online.sources[0])
    assert caught.value.response.error.retryable and len(network[2]) == 1


@pytest.mark.parametrize("body,code", [(b"not HTML", "MALFORMED_HTML"), (b"<html><body><p>short</p></body></html>", "NO_TEXT_EXTRACTED")])
def test_extraction_failures_preserve_fetched_evidence(body, code, online_settings, registry, network, inline_worker):
    network[0].append(Response(body))
    result = online.ingest_online(["apache_kafka"], [], online_settings, registry)
    attempt = result.outcomes[0]
    assert attempt.error.code == code and attempt.online.extraction_status == "extraction_failed"
    assert attempt.result is None and attempt.online.snapshot_id == hashlib.sha256(body).hexdigest()
    assert (Path(online_settings.data_directory) / attempt.online.snapshot_path).read_bytes() == body
    assert registry.list_documents() == []


@pytest.mark.parametrize("title", [b"", b"<title></title>", b"<title>one</title><title>two</title>", b"<title><b>bad</b></title>"])
def test_missing_or_invalid_titles_warn_without_inventing_original_title(title, online_settings, registry, network, inline_worker):
    network[0].append(Response(HTML.replace(b"<title>Kafka Consumer Configuration</title>", title)))
    result = online.ingest_online(["apache_kafka"], [], online_settings, registry)
    record = registry.get_document(result.outcomes[0].result.document_id)
    assert record.online.original_title is None and record.title == online_settings.online.sources[0].title
    assert "MISSING_OR_INVALID_TITLE" in record.online.warnings


def test_http_declared_encoding_and_exact_raw_hash(online_settings, registry, network, inline_worker):
    body = HTML.replace(b"These documentation", "Caf\u00e9 documentation".encode("latin-1"))
    network[0].append(Response(body, headers={"Content-Type": "text/html; charset=iso-8859-1"}))
    result = online.ingest_online(["apache_kafka"], [], online_settings, registry)
    provenance = result.outcomes[0].online
    assert provenance.encoding == "iso8859-1" and provenance.content_type_header == "text/html; charset=iso-8859-1"
    assert provenance.snapshot_id == hashlib.sha256(body).hexdigest()
    assert "Caf\u00e9" in (Path(online_settings.data_directory) / provenance.extracted_path).read_text(encoding="utf-8")


def test_invalid_declared_encoding_is_structured(online_settings, registry, network, inline_worker):
    network[0].append(Response(HTML, headers={"Content-Type": "text/html; charset=not-a-codec"}))
    result = online.ingest_online(["apache_kafka"], [], online_settings, registry)
    assert result.outcomes[0].error.code == "DECODE_FAILED"


def test_repeat_snapshot_and_changed_bytes_preserve_history(online_settings, registry, network, inline_worker):
    network[0].extend([Response(), Response(), Response(HTML.replace(b"300000", b"400000"))])
    first, repeat, changed = [online.ingest_online(["apache_kafka"], [], online_settings, registry) for _ in range(3)]
    one, two, three = [result.outcomes[0] for result in [first, repeat, changed]]
    assert one.result.document_id == two.result.document_id == three.result.document_id
    assert one.result.version_id == two.result.version_id != three.result.version_id
    assert two.result.deduplicated and repeat.run.skipped == 1
    assert one.online.extracted_hash == two.online.extracted_hash
    assert one.online.snapshot_path == two.online.snapshot_path != three.online.snapshot_path
    assert one.online.retrieval_id != two.online.retrieval_id
    history = registry.history(one.result.document_id)
    assert len(history["registrations"]) == 2
    assert history["registrations"][1]["previous_version_id"] == one.result.version_id
    assert all(not record["finalized"] and record["content_hash"] is None for record in history["registrations"])
    assert [event["decision"] for event in history["events"]] == ["REGISTERED", "DUPLICATE_SKIPPED", "CHANGED_BYTES_REGISTERED"]
    with Registry(registry.path) as reopened:
        assert reopened.get_run(repeat.run.run_id).outcomes[0].online.retrieval_id == two.online.retrieval_id
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == 1
    manifest = json.loads((Path(online_settings.data_directory) / changed.manifest_path).read_text())
    assert len(manifest["documents"]) == 2 and len(manifest["retrievals"]) == 3


def test_partial_batch_keeps_success(online_settings, registry, network, inline_worker):
    network[0].extend([Response(), Response(status=404)])
    result = online.ingest_online(["apache_kafka", "apache_airflow"], [], online_settings, registry)
    assert result.run.status == "completed_with_errors" and (result.pages_succeeded, result.pages_failed) == (1, 1)
    assert len(registry.list_documents()) == 1


def test_unknown_source_does_not_discard_valid_batch_members(online_settings, registry, network, inline_worker):
    network[0].append(Response())
    result = online.ingest_online(["apache_kafka", "private-invalid-source"], [], online_settings, registry)
    assert result.run.status == "completed_with_errors" and result.pages_succeeded == 1
    assert result.outcomes[1].error.code == "SOURCE_NOT_APPROVED"
    assert "private-invalid-source" not in result.model_dump_json()


def test_dns_failure_and_tls_failure_are_safe(online_settings, network, monkeypatch):
    def failure(*args, **kwargs):
        raise socket.gaierror("sensitive diagnostic")
    original = fetching.socket.getaddrinfo
    monkeypatch.setattr(fetching.socket, "getaddrinfo", failure)
    source = online_settings.online.sources[0]
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(source.pages[0], source)
    assert caught.value.response.error.code == "DNS_FAILED" and caught.value.response.error.retryable
    assert "sensitive" not in caught.value.response.model_dump_json()
    monkeypatch.setattr(fetching.socket, "getaddrinfo", original)
    network[0].append(urllib3.exceptions.SSLError("sensitive TLS diagnostic"))
    with pytest.raises(TechDocQAError) as caught:
        fetching.SafeFetcher(online_settings.online, 10000).fetch(source.pages[0], source)
    assert caught.value.response.error.code == "TLS_FAILED" and len(network[2]) == 1


def test_catalog_configuration_errors_use_existing_json_contract(tmp_path, capsys):
    config = tmp_path / "invalid.toml"
    config.write_text('[[online.sources]]\nsource_id="private"\ntechnology="Kafka"\ntitle="Docs"\nentry_url="http://private.example/"\nscopes=["http://private.example/"]\npages=["http://private.example/"]\n')
    assert main(["config-check", "--config", str(config)]) == 1
    output = capsys.readouterr()
    assert json.loads(output.err)["error"]["code"] == "INVALID_CONFIGURATION"
    assert "private.example" not in output.err


def test_snapshot_storage_cannot_follow_escape_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "data"
    root.mkdir()
    try:
        (root / "online").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation unavailable")
    with pytest.raises(TechDocQAError) as caught:
        online.store_snapshot(root, "snapshots", HTML, ".html")
    assert caught.value.response.error.code == "UNSAFE_STORAGE" and not list(outside.iterdir())


def test_overall_worker_timeout_terminates_real_process(online_settings, tmp_path, monkeypatch):
    original = subprocess.run
    def sleeping_worker(command, **kwargs):
        return original([sys.executable, "-I", "-c", "import time; time.sleep(30)"], **kwargs)
    monkeypatch.setattr(online.subprocess, "run", sleeping_worker)
    online_settings.ingestion.parse_timeout_seconds = 1
    with pytest.raises(TechDocQAError) as caught:
        online.run_page_worker(online_settings.online.sources[0], online_settings.online.sources[0].pages[0], online_settings, tmp_path)
    assert caught.value.response.error.code == "PAGE_TIMEOUT" and caught.value.response.error.retryable


def test_finite_selection_limit_and_no_link_discovery(online_settings, registry, network, inline_worker):
    source = online_settings.online.sources[0]
    online_settings.online.max_pages_per_run = 1
    with pytest.raises(TechDocQAError):
        online.ingest_online([source.source_id, "apache_airflow"], [], online_settings, registry)
    network[0].append(Response(HTML.replace(b"</main>", b'<a href="https://evil.example/">follow me</a></main>')))
    online.ingest_online([source.source_id], [], online_settings, registry)
    assert len(network[2]) == 1


def test_cli_json_modes_and_document_query(online_settings, network, inline_worker, tmp_path, capsys):
    config = tmp_path / "online.toml"
    config.write_text((ROOT / "config/default.toml").read_text(encoding="utf-8"), encoding="utf-8")
    # This config's relative data directory is still beneath the test's temporary root.
    config.write_text(config.read_text(encoding="utf-8").replace('data_directory = "../data"', 'data_directory = "runtime"'), encoding="utf-8")
    network[0].append(Response())
    assert main(["ingest", "--source", "apache_kafka", "--config", str(config), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run"]["stage"] == "registration" and payload["pages_succeeded"] == 1
    identifier = payload["outcomes"][0]["result"]["document_id"]
    assert main(["status", "--document-id", identifier, "--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["document"]["online"]["source_id"] == "apache_kafka"
    network[0].extend([Response(), Response(status=404)])
    source = online_settings.online.sources[0]
    airflow = online_settings.online.sources[1]
    assert main(["--json", "ingest", "--url", source.pages[0], "--url", airflow.pages[0], "--config", str(config)]) == 1
    assert json.loads(capsys.readouterr().out)["pages_failed"] == 1


@pytest.mark.parametrize("arguments", [[], ["path.txt", "--source", "apache_kafka"], ["--source", "apache_kafka", "--url", "https://example.org/"], ["--source", "apache_kafka", "--logical-name", "private"], ["--source", "apache_kafka", "--source-url", "https://example.org/"]])
def test_cli_malformed_online_selection_is_standard_json(arguments, capsys):
    assert main(["ingest", *arguments]) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["error"]["code"] == "INVALID_ARGUMENT"
    assert "private" not in output.err


def test_isolated_worker_honors_offline_guard(online_settings, tmp_path):
    output = online.run_page_worker(online_settings.online.sources[0], online_settings.online.sources[0].pages[0], online_settings, tmp_path)
    assert output["error"]["code"] == "NETWORK_DISABLED"


def test_network_guard_rejects_accidental_requests():
    with pytest.raises(AssertionError, match="Unexpected outbound"):
        socket.getaddrinfo("kafka.apache.org", 443)


def test_manifest_failure_does_not_undo_registration(online_settings, registry, network, inline_worker, monkeypatch):
    network[0].append(Response())
    def denied(*args):
        raise PermissionError("private detail")
    monkeypatch.setattr(online, "export_manifest", denied)
    result = online.ingest_online(["apache_kafka"], [], online_settings, registry)
    assert result.pages_succeeded == 1 and result.warnings == ["MANIFEST_EXPORT_FAILED"]
    assert len(registry.list_documents()) == 1


def test_corrupt_existing_snapshot_is_not_overwritten(tmp_path):
    path, digest = online.store_snapshot(tmp_path, "snapshots", HTML, ".html")
    path.write_bytes(b"corrupt")
    with pytest.raises(TechDocQAError) as caught:
        online.store_snapshot(tmp_path, "snapshots", HTML, ".html")
    assert caught.value.response.error.code == "SNAPSHOT_MISMATCH" and path.read_bytes() == b"corrupt"


@pytest.mark.live
@pytest.mark.parametrize("source_id", ["apache_kafka", "apache_airflow"])
def test_live_official_documentation_smoke(source_id, online_settings, registry):
    result = online.ingest_online([source_id], [], online_settings, registry)
    assert result.pages_succeeded == 1, result.model_dump_json()
    assert result.outcomes[0].online.extraction_status == "extracted"

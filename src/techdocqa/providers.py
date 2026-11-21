"""Ollama's installed models, listed one way for indexing, answering and `check` (FR-24, P12-3).

The three used to list and match models separately, so `check` could pass a model that indexing then refused. Names
are compared tagged: Ollama serves an untagged name as its `latest` tag and lists every model with a tag.
"""


def tagged(name: str) -> str:
    """`nomic-embed-text` is `nomic-embed-text:latest`; a registry host's port is not a tag."""
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


def ollama_models(model, timeout: float | None) -> dict[str, str]:
    """Installed models by tagged name, with their digests. Whatever the client raises is the caller's to map."""
    import ollama
    return {tagged(item.model): item.digest for item in ollama.Client(host=model.base_url, timeout=timeout).list().models}


def installed_digest(installed: dict[str, str], name: str | None) -> str | None:
    """The installed digest of a configured model, or None when it is not installed."""
    return installed.get(tagged(name)) if name else None

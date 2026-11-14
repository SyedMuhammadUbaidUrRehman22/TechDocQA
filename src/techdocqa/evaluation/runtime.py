"""What a run ran on (NFR-05, P11-5): library versions, the Ollama server and its loaded models, and the machine.

Recorded beside each run and outside every fingerprint, so it can never move a result. Nothing here may fail a run:
a value that cannot be read is null. Ollama updates itself, so its server version is read from the server each time.
"""

import ctypes
from importlib import metadata
import os
import platform
import sys

LIBRARIES = ("langchain-core", "langchain-community", "langchain-chroma", "langchain-ollama", "langchain-text-splitters", "chromadb",
             "rank-bm25", "pydantic", "numpy", "ollama", "onnxruntime", "tokenizers", "pypdf")
OLLAMA_TIMEOUT_SECONDS = 2.0


def library_versions(names=LIBRARIES) -> dict:
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def processor_split(size: int, size_vram: int) -> str:
    """The PROCESSOR column of `ollama ps`: where a loaded model's weights sit."""
    if size <= 0:
        return "unknown"
    gpu = round(100 * size_vram / size)
    if gpu <= 0:
        return "100% CPU"
    if gpu >= 100:
        return "100% GPU"
    return f"{100 - gpu}%/{gpu}% CPU/GPU"


def ollama_state(base_url: str) -> dict:
    """The server version and the models loaded right now. Offline (TECHDOCQA_OFFLINE=1) nothing is contacted."""
    if os.environ.get("TECHDOCQA_OFFLINE") == "1":
        return {"version": None, "loaded": None, "note": "offline: not contacted"}
    try:
        import httpx
        with httpx.Client(base_url=base_url, timeout=OLLAMA_TIMEOUT_SECONDS) as client:
            version = client.get("/api/version").raise_for_status().json().get("version")
            models = client.get("/api/ps").raise_for_status().json().get("models") or []
    except Exception:
        return {"version": None, "loaded": None, "note": "unreachable"}
    loaded = [{"model": item.get("name") or item.get("model"), "size": item.get("size"), "size_vram": item.get("size_vram"),
               "processor": processor_split(int(item.get("size") or 0), int(item.get("size_vram") or 0))}
              for item in models]
    return {"version": version, "loaded": sorted(loaded, key=lambda item: item["model"] or "")}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong), ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong), ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong), ("available_extended_virtual", ctypes.c_ulonglong)]


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ac_line_status", ctypes.c_ubyte), ("battery_flag", ctypes.c_ubyte), ("battery_life_percent", ctypes.c_ubyte),
                ("system_status_flag", ctypes.c_ubyte), ("battery_life_time", ctypes.c_ulong), ("battery_full_life_time", ctypes.c_ulong)]


def machine() -> dict:
    """CPU, memory and power at the moment of recording. Memory and power are read on Windows only."""
    values = {"processor": platform.processor() or None, "machine": platform.machine() or None, "logical_cpus": os.cpu_count(),
              "ram_total_bytes": None, "ram_available_bytes": None, "ac_power": None}
    if sys.platform != "win32":
        return values
    try:
        memory = _MemoryStatus()
        memory.length = ctypes.sizeof(_MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            values["ram_total_bytes"], values["ram_available_bytes"] = memory.total_physical, memory.available_physical
        power = _PowerStatus()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)):
            values["ac_power"] = {0: False, 1: True}.get(power.ac_line_status)
    except (AttributeError, OSError):
        pass
    return values


def runtime(settings) -> dict:
    """Python, platform, libraries, the Ollama server when it is the provider, and the machine."""
    values = {"python": platform.python_version(), "platform": platform.platform(), "libraries": library_versions()}
    if settings.model.provider == "ollama":
        values["ollama"] = ollama_state(settings.model.base_url)
    values["machine"] = machine()
    return values


def summary_line(values: dict) -> str:
    """One Markdown line for a report header. Reports from before Phase 11 are re-rendered by --record-review."""
    if "machine" not in values:
        return "- Runtime: not recorded (run before Phase 11)"
    parts = []
    ollama = values.get("ollama")
    if ollama is not None:
        models = ", ".join(f"{item['model']} {item['processor']}" for item in ollama.get("loaded") or [])
        parts.append(f"Ollama {ollama.get('version') or 'unknown'}" + (f" ({models})" if models else ""))
    host = values.get("machine") or {}
    gigabytes = lambda value: f"{value / 2**30:.1f}" if value else "?"
    parts.append(f"{host.get('logical_cpus') or '?'} logical CPUs, RAM {gigabytes(host.get('ram_available_bytes'))} of "
                 f"{gigabytes(host.get('ram_total_bytes'))} GB free")
    if host.get("ac_power") is not None:
        parts.append("on AC power" if host["ac_power"] else "on battery")
    return f"- Runtime: Python {values.get('python')}; " + "; ".join(parts)

"""Per-file registration orchestration; no text loading or model calls."""

from pathlib import Path

from techdocqa.errors import TechDocQAError
from techdocqa.ingestion.safety import allowed_path, validate_file
from techdocqa.registry import Registry
from techdocqa.schemas import BatchResult, RegistrationMetadata
from techdocqa.settings import Settings


def expand_inputs(paths: list[Path], settings: Settings) -> list[tuple[Path, TechDocQAError | None]]:
    inputs = []
    for path in paths:
        try:
            resolved = allowed_path(Path(path), settings)
            if resolved.is_dir():
                children = sorted(resolved.iterdir(), key=lambda item: (item.name.casefold(), item.name))
                if not children:
                    raise TechDocQAError("EMPTY_DIRECTORY", "Directory contains no input files.")
                # Deliberately one level: nested directories get their own explicit error.
                inputs.extend((child, None) for child in children)
            else:
                inputs.append((resolved, None))
        except TechDocQAError as error:
            inputs.append((Path(path), error))
        except (OSError, ValueError, RuntimeError):
            inputs.append((Path(path), TechDocQAError("SOURCE_NOT_ACCESSIBLE", "Input directory is unreadable or unsafe.")))
    return inputs


def register_paths(paths: list[Path], settings: Settings, registry: Registry, *,
                   metadata: RegistrationMetadata | None = None, logical_name: str | None = None) -> BatchResult:
    if not paths:
        raise TechDocQAError("INVALID_ARGUMENT", "At least one input is required.", stage="arguments")
    metadata = metadata if metadata is not None else RegistrationMetadata()
    with registry.registration_lock():
        registry.recover_interrupted_runs()
        inputs = expand_inputs(paths, settings)
        run_id, attempts = registry.start_run(len(inputs))
        for (path, preflight_error), attempt_id in zip(inputs, attempts, strict=True):
            try:
                if preflight_error is not None:
                    raise preflight_error
                source = validate_file(path, settings)
                registry.register(source, metadata, logical_name, attempt_id)
            except TechDocQAError as error:
                registry.fail_attempt(attempt_id, error.response.error)
        registry.finish_run(run_id)
        return registry.get_run(run_id)

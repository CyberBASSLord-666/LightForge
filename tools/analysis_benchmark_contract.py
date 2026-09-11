#!/usr/bin/env python3
"""Versioned diagnostics, cache, checkpoint, and benchmark contracts.

This module is deliberately dependency-free so it can be used by local Android
test runners, desktop parity harnesses, and CI.  It does not perform musical
analysis; it records and validates the evidence needed to evaluate an analysis
implementation without silently weakening it.

The contract keeps three identities separate:

* workload: the immutable audio/corpus/settings being measured;
* implementation: source and model versions under test; and
* environment: hardware/runtime/accelerator conditions.

Only a comparable workload and environment may be used for a baseline versus
candidate performance claim.  A choreography-only setting therefore belongs
outside an analysis cache identity and cannot invalidate expensive stems.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, Mapping, MutableMapping, Optional

try:  # ``resource`` is absent on some non-POSIX benchmark hosts.
    import resource
except ImportError:  # pragma: no cover - exercised by Windows consumers.
    resource = None


SCHEMA_VERSION = 1
CACHE_FORMAT_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGE_ID = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_CACHE_KEY = re.compile(r"^sha256:[0-9a-f]{64}$")
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_\-.])(token|secret|password|authorization|api[_\-.]?key)(?:$|[_\-.])",
    re.IGNORECASE,
)
_PRIVATE_DIAGNOSTIC_KEY = re.compile(
    r"(?:^|[_\-.])(path|filepath|uri|url|audio[_\-.]?(?:data|payload)|raw[_\-.]?audio|lyrics?|email|phone|exception[_\-.]?message)(?:$|[_\-.])",
    re.IGNORECASE,
)
_STAGE_STATUSES = frozenset({"completed", "reused", "skipped", "failed", "cancelled"})
_CACHE_STATUSES = frozenset({"hit", "miss", "disabled", "not_applicable"})
_CHECKPOINT_STATUSES = frozenset({"written", "reused", "not_applicable"})
_TIME_FIELDS = frozenset(
    {
        "wall_clock_seconds",
        "cpu_seconds",
        "model_initialization_seconds",
        "preprocessing_seconds",
        "inference_seconds",
        "postprocessing_seconds",
        "waiting_seconds",
    }
)
_BYTE_FIELDS = frozenset(
    {
        "peak_rss_bytes",
        "peak_accelerator_bytes",
        "allocation_bytes",
        "read_bytes",
        "write_bytes",
        "temporary_storage_bytes",
    }
)


class ContractValidationError(ValueError):
    """Raised when a report is insufficient for a trustworthy comparison."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class CacheCorruptionError(RuntimeError):
    """A cache/checkpoint record exists but cannot safely be reused."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _require_mapping(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        errors.append(f"{path} must be an object")
        return {}
    return value


def _require_string(value: Any, path: str, errors: list[str], *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        errors.append(f"{path} must be a non-empty string")
        return ""
    return value


def _require_sha256(value: Any, path: str, errors: list[str]) -> str:
    value = _require_string(value, path, errors)
    if value and not _SHA256.fullmatch(value):
        errors.append(f"{path} must be a lower-case SHA-256 digest")
    return value


def _validate_json_value(value: Any, path: str, errors: list[str]) -> None:
    """Validate JSON compatibility and prevent accidental credential capture."""
    if value is None or isinstance(value, (str, bool)):
        return
    if _is_number(value):
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                errors.append(f"{path} contains a non-string key")
                continue
            if _SENSITIVE_KEY.search(key):
                errors.append(f"{path}.{key} is not allowed in diagnostics")
            if _PRIVATE_DIAGNOSTIC_KEY.search(key):
                errors.append(f"{path}.{key} is not allowed in diagnostics")
            _validate_json_value(child, f"{path}.{key}", errors)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{path}[{index}]", errors)
        return
    errors.append(f"{path} is not JSON-compatible")


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON representation suitable for identity hashes."""
    errors: list[str] = []
    _validate_json_value(value, "value", errors)
    if errors:
        raise ContractValidationError(errors)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_address(domain: str, identity: Mapping[str, Any]) -> str:
    """Create a deterministic, domain-separated cache identity.

    ``identity`` should contain only inputs that affect this cache domain.  For
    example, a stem identity includes audio/model/preprocessing versions, while
    a choreography identity additionally includes the choreography settings.
    """
    if not isinstance(domain, str) or not _STAGE_ID.fullmatch(domain):
        raise ValueError("domain must be a stable lower-case identifier")
    if not isinstance(identity, Mapping):
        raise ValueError("identity must be an object")
    return "sha256:" + digest_json(
        {"cache_format_version": CACHE_FORMAT_VERSION, "domain": domain, "identity": identity}
    )


def analysis_cache_identity(
    *,
    audio_sha256: str,
    model_versions: Mapping[str, str],
    analysis_configuration: Mapping[str, Any],
    preprocessing_version: str,
    pipeline_version: str,
) -> dict[str, Any]:
    """Construct the mandatory identity inputs for analysis-domain caches."""
    errors: list[str] = []
    _require_sha256(audio_sha256, "audio_sha256", errors)
    _require_string(preprocessing_version, "preprocessing_version", errors)
    _require_string(pipeline_version, "pipeline_version", errors)
    if not isinstance(model_versions, Mapping):
        errors.append("model_versions must be an object")
    if not isinstance(analysis_configuration, Mapping):
        errors.append("analysis_configuration must be an object")
    _validate_json_value(model_versions, "model_versions", errors)
    _validate_json_value(analysis_configuration, "analysis_configuration", errors)
    if errors:
        raise ContractValidationError(errors)
    return {
        "audio_sha256": audio_sha256,
        "model_versions": copy.deepcopy(dict(model_versions)),
        "analysis_configuration": copy.deepcopy(dict(analysis_configuration)),
        "preprocessing_version": preprocessing_version,
        "pipeline_version": pipeline_version,
    }


def _rss_bytes() -> Optional[int]:
    """Best-effort process high-water RSS; resource reports bytes on macOS, KiB on Linux."""
    if resource is None:
        return None
    try:
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError):
        return None
    return rss if platform.system() == "Darwin" else rss * 1024


def _validate_provenance(provenance: Any, errors: list[str]) -> None:
    provenance = _require_mapping(provenance, "provenance", errors)
    workload = _require_mapping(provenance.get("workload"), "provenance.workload", errors)
    implementation = _require_mapping(provenance.get("implementation"), "provenance.implementation", errors)
    environment = _require_mapping(provenance.get("environment"), "provenance.environment", errors)

    _require_string(workload.get("corpus_id"), "provenance.workload.corpus_id", errors)
    _require_sha256(workload.get("corpus_manifest_sha256"), "provenance.workload.corpus_manifest_sha256", errors)
    audio = _require_mapping(workload.get("audio"), "provenance.workload.audio", errors)
    _require_sha256(audio.get("content_sha256"), "provenance.workload.audio.content_sha256", errors)
    duration = audio.get("duration_seconds")
    if not _is_number(duration) or float(duration) <= 0:
        errors.append("provenance.workload.audio.duration_seconds must be a positive finite number")
    rate = audio.get("canonical_sample_rate")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
        errors.append("provenance.workload.audio.canonical_sample_rate must be a positive integer")
    channels = audio.get("channels")
    if not isinstance(channels, int) or isinstance(channels, bool) or channels <= 0:
        errors.append("provenance.workload.audio.channels must be a positive integer")
    configuration = _require_mapping(
        workload.get("analysis_configuration"), "provenance.workload.analysis_configuration", errors
    )
    _validate_json_value(configuration, "provenance.workload.analysis_configuration", errors)

    _require_string(implementation.get("pipeline_version"), "provenance.implementation.pipeline_version", errors)
    _require_string(implementation.get("preprocessing_version"), "provenance.implementation.preprocessing_version", errors)
    models = _require_mapping(implementation.get("model_versions"), "provenance.implementation.model_versions", errors)
    if not models:
        errors.append("provenance.implementation.model_versions must not be empty")
    for name, version in models.items():
        _require_string(name, "provenance.implementation.model_versions key", errors)
        _require_string(version, f"provenance.implementation.model_versions.{name}", errors)

    _require_string(environment.get("hardware_fingerprint"), "provenance.environment.hardware_fingerprint", errors)
    _require_string(environment.get("runtime_backend"), "provenance.environment.runtime_backend", errors)
    _require_string(environment.get("runtime_version"), "provenance.environment.runtime_version", errors)
    accelerator = _require_mapping(environment.get("accelerator"), "provenance.environment.accelerator", errors)
    _validate_json_value(accelerator, "provenance.environment.accelerator", errors)
    if "random_seed" not in environment or isinstance(environment.get("random_seed"), bool):
        errors.append("provenance.environment.random_seed is required")
    elif not isinstance(environment.get("random_seed"), (int, str)):
        errors.append("provenance.environment.random_seed must be an integer or string")
    _require_string(environment.get("thermal_profile"), "provenance.environment.thermal_profile", errors)


def _validate_stage(stage: Any, index: int, errors: list[str]) -> tuple[str, int]:
    path = f"stages[{index}]"
    stage = _require_mapping(stage, path, errors)
    stage_id = _require_string(stage.get("stage_id"), f"{path}.stage_id", errors)
    if stage_id and not _STAGE_ID.fullmatch(stage_id):
        errors.append(f"{path}.stage_id is not a stable stage identifier")
    attempt = stage.get("attempt", 1)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append(f"{path}.attempt must be a positive integer")
        attempt = 0
    status = stage.get("status")
    if status not in _STAGE_STATUSES:
        errors.append(f"{path}.status must be one of {sorted(_STAGE_STATUSES)}")

    timings = _require_mapping(stage.get("timings"), f"{path}.timings", errors)
    wall = timings.get("wall_clock_seconds")
    if not _is_number(wall) or float(wall) < 0:
        errors.append(f"{path}.timings.wall_clock_seconds must be a non-negative finite number")
        wall = None
    for name, value in timings.items():
        if name not in _TIME_FIELDS:
            errors.append(f"{path}.timings.{name} is not a declared timing field")
        elif not _is_number(value) or float(value) < 0:
            errors.append(f"{path}.timings.{name} must be a non-negative finite number")
        elif wall is not None and name != "wall_clock_seconds" and float(value) > float(wall) + 0.001:
            errors.append(f"{path}.timings.{name} cannot exceed wall_clock_seconds")

    resources = _require_mapping(stage.get("resources", {}), f"{path}.resources", errors)
    for name, value in resources.items():
        if name not in _BYTE_FIELDS:
            errors.append(f"{path}.resources.{name} is not a declared resource field")
        elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{path}.resources.{name} must be a non-negative integer")

    cache = _require_mapping(stage.get("cache"), f"{path}.cache", errors)
    cache_status = cache.get("status")
    if cache_status not in _CACHE_STATUSES:
        errors.append(f"{path}.cache.status must be one of {sorted(_CACHE_STATUSES)}")
    cache_key = cache.get("key")
    if cache_status in {"hit", "miss"} and (not isinstance(cache_key, str) or not _CACHE_KEY.fullmatch(cache_key)):
        errors.append(f"{path}.cache.key is required for a cache hit or miss")
    if cache_status in {"disabled", "not_applicable"} and cache_key is not None:
        errors.append(f"{path}.cache.key is only valid for a cache hit or miss")

    checkpoint = _require_mapping(stage.get("checkpoint"), f"{path}.checkpoint", errors)
    checkpoint_status = checkpoint.get("status")
    if checkpoint_status not in _CHECKPOINT_STATUSES:
        errors.append(f"{path}.checkpoint.status must be one of {sorted(_CHECKPOINT_STATUSES)}")
    checkpoint_key = checkpoint.get("key")
    if checkpoint_status in {"written", "reused"} and (
        not isinstance(checkpoint_key, str) or not _CACHE_KEY.fullmatch(checkpoint_key)
    ):
        errors.append(f"{path}.checkpoint.key is required for a written or reused checkpoint")
    if checkpoint_status == "not_applicable" and checkpoint_key is not None:
        errors.append(f"{path}.checkpoint.key is only valid when checkpointing is used")
    _validate_json_value(stage.get("metadata", {}), f"{path}.metadata", errors)
    return stage_id, attempt


def validate_diagnostic(report: Any) -> None:
    """Fail closed on a diagnostic report that cannot support release evidence."""
    errors: list[str] = []
    _validate_json_value(report, "report", errors)
    report = _require_mapping(report, "report", errors)
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must equal {SCHEMA_VERSION}")
    _require_string(report.get("run_id"), "run_id", errors)
    _require_string(report.get("track_id"), "track_id", errors)
    _require_string(report.get("recorded_at"), "recorded_at", errors)
    _validate_provenance(report.get("provenance"), errors)
    execution = _require_mapping(report.get("execution"), "execution", errors)
    for field in ("wall_clock_seconds", "cpu_seconds"):
        value = execution.get(field)
        if not _is_number(value) or float(value) < 0:
            errors.append(f"execution.{field} must be a non-negative finite number")
    stages = report.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append("stages must be a non-empty array")
    else:
        seen: set[tuple[str, int]] = set()
        for index, stage in enumerate(stages):
            identity = _validate_stage(stage, index, errors)
            if identity in seen:
                errors.append(f"stages contains a duplicate stage/attempt {identity[0]}#{identity[1]}")
            seen.add(identity)
    metrics = _require_mapping(report.get("metrics"), "metrics", errors)
    _validate_json_value(metrics, "metrics", errors)
    _validate_json_value(report.get("outputs", {}), "outputs", errors)
    _validate_json_value(report.get("warnings", []), "warnings", errors)
    if errors:
        raise ContractValidationError(errors)


def validate_corpus_manifest(manifest: Any) -> None:
    errors: list[str] = []
    _validate_json_value(manifest, "manifest", errors)
    manifest = _require_mapping(manifest, "manifest", errors)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"manifest.schema_version must equal {SCHEMA_VERSION}")
    _require_string(manifest.get("corpus_id"), "manifest.corpus_id", errors)
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("manifest.tracks must be a non-empty array")
    else:
        identities: set[str] = set()
        for index, track in enumerate(tracks):
            path = f"manifest.tracks[{index}]"
            track = _require_mapping(track, path, errors)
            track_id = _require_string(track.get("track_id"), f"{path}.track_id", errors)
            if track_id in identities:
                errors.append(f"manifest.tracks has duplicate track_id {track_id}")
            identities.add(track_id)
            audio = _require_mapping(track.get("audio"), f"{path}.audio", errors)
            _require_sha256(audio.get("content_sha256"), f"{path}.audio.content_sha256", errors)
            duration = audio.get("duration_seconds")
            if not _is_number(duration) or float(duration) <= 0:
                errors.append(f"{path}.audio.duration_seconds must be a positive finite number")
            tags = track.get("tags", [])
            if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
                errors.append(f"{path}.tags must be an array of non-empty strings")
            _validate_json_value(track.get("golden_artifacts", {}), f"{path}.golden_artifacts", errors)
    if errors:
        raise ContractValidationError(errors)


def corpus_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    validate_corpus_manifest(manifest)
    return digest_json(manifest)


def validate_against_corpus(report: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Confirm that a diagnostic is bound to a locked corpus entry."""
    validate_diagnostic(report)
    validate_corpus_manifest(manifest)
    workload = report["provenance"]["workload"]
    expected_hash = corpus_manifest_sha256(manifest)
    errors: list[str] = []
    if workload["corpus_id"] != manifest["corpus_id"]:
        errors.append("report corpus_id does not match the locked corpus")
    if workload["corpus_manifest_sha256"] != expected_hash:
        errors.append("report corpus_manifest_sha256 does not match the locked corpus")
    tracks = {track["track_id"]: track for track in manifest["tracks"]}
    expected = tracks.get(report["track_id"])
    if expected is None:
        errors.append("report track_id is not present in the locked corpus")
    else:
        actual_audio = workload["audio"]
        expected_audio = expected["audio"]
        if actual_audio["content_sha256"] != expected_audio["content_sha256"]:
            errors.append("report audio content hash does not match the locked corpus")
        if not math.isclose(float(actual_audio["duration_seconds"]), float(expected_audio["duration_seconds"]), abs_tol=1e-6):
            errors.append("report audio duration does not match the locked corpus")
    if errors:
        raise ContractValidationError(errors)


def comparability_differences(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """List immutable workload/environment differences that invalidate a speed claim.

    The pipeline source version is intentionally excluded: that is normally the
    thing under test.  Model versions are included because replacing a model is
    not a performance-only optimization.
    """
    validate_diagnostic(baseline)
    validate_diagnostic(candidate)
    paths = (
        ("track_id",),
        ("provenance", "workload", "corpus_id"),
        ("provenance", "workload", "corpus_manifest_sha256"),
        ("provenance", "workload", "audio"),
        ("provenance", "workload", "analysis_configuration"),
        ("provenance", "implementation", "preprocessing_version"),
        ("provenance", "implementation", "model_versions"),
        ("provenance", "environment", "hardware_fingerprint"),
        ("provenance", "environment", "runtime_backend"),
        ("provenance", "environment", "runtime_version"),
        ("provenance", "environment", "accelerator"),
        ("provenance", "environment", "random_seed"),
        ("provenance", "environment", "thermal_profile"),
    )
    differences: list[dict[str, Any]] = []
    for path in paths:
        left: Any = baseline
        right: Any = candidate
        for part in path:
            left = left[part]
            right = right[part]
        if canonical_json(left) != canonical_json(right):
            differences.append({"field": ".".join(path), "baseline": left, "candidate": right})
    return differences


def ensure_comparable(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    differences = comparability_differences(baseline, candidate)
    if differences:
        raise ContractValidationError([f"non-comparable baseline/candidate field: {row['field']}" for row in differences])


class _StageScope:
    def __init__(self, recorder: "AnalysisRunRecorder", stage_id: str, attempt: int, cache: Mapping[str, Any]):
        self._recorder = recorder
        self._stage_id = stage_id
        self._attempt = attempt
        self._cache = dict(cache)
        self._checkpoint: dict[str, Any] = {"status": "not_applicable"}
        self._metadata: dict[str, Any] = {}
        self._timings: dict[str, float] = {}
        self._resources: dict[str, int] = {}
        self._status = "completed"
        self._started_wall = 0.0
        self._started_cpu = 0.0

    def timing(self, field: str, seconds: float) -> None:
        if field not in _TIME_FIELDS - {"wall_clock_seconds", "cpu_seconds"}:
            raise ValueError(f"unknown stage timing field: {field}")
        if not _is_number(seconds) or float(seconds) < 0:
            raise ValueError("timing must be a non-negative finite number")
        self._timings[field] = float(seconds)

    def resource(self, field: str, value: int) -> None:
        if field not in _BYTE_FIELDS:
            raise ValueError(f"unknown resource field: {field}")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("resource value must be a non-negative integer")
        self._resources[field] = value

    def metadata(self, **values: Any) -> None:
        errors: list[str] = []
        _validate_json_value(values, "metadata", errors)
        if errors:
            raise ContractValidationError(errors)
        self._metadata.update(copy.deepcopy(values))

    def checkpoint(self, status: str, key: Optional[str] = None) -> None:
        if status not in _CHECKPOINT_STATUSES:
            raise ValueError("invalid checkpoint status")
        if status in {"written", "reused"} and (not isinstance(key, str) or not _CACHE_KEY.fullmatch(key)):
            raise ValueError("checkpoint key is required")
        if status == "not_applicable" and key is not None:
            raise ValueError("not_applicable checkpoints do not have a key")
        self._checkpoint = {"status": status}
        if key is not None:
            self._checkpoint["key"] = key

    def status(self, value: str) -> None:
        if value not in _STAGE_STATUSES:
            raise ValueError("invalid stage status")
        self._status = value

    def _finish(self, exception: Optional[BaseException]) -> None:
        if exception is not None:
            self._status = "failed"
            self._metadata.setdefault("error_type", type(exception).__name__)
        wall = max(0.0, time.perf_counter() - self._started_wall)
        cpu = max(0.0, time.process_time() - self._started_cpu)
        timings = {"wall_clock_seconds": wall, "cpu_seconds": cpu, **self._timings}
        resources = dict(self._resources)
        rss = _rss_bytes()
        if rss is not None:
            resources.setdefault("peak_rss_bytes", rss)
        record = {
            "stage_id": self._stage_id,
            "attempt": self._attempt,
            "status": self._status,
            "timings": timings,
            "resources": resources,
            "cache": self._cache,
            "checkpoint": self._checkpoint,
            "metadata": self._metadata,
        }
        self._recorder._append_stage(record)


class AnalysisRunRecorder:
    """Thread-safe stage profiler that emits a strict diagnostic document."""

    def __init__(self, track_id: str, provenance: Mapping[str, Any], *, run_id: Optional[str] = None):
        if not isinstance(track_id, str) or not track_id:
            raise ValueError("track_id is required")
        self._started_wall = time.perf_counter()
        self._started_cpu = time.process_time()
        self._lock = threading.Lock()
        self._report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id or str(uuid.uuid4()),
            "track_id": track_id,
            "recorded_at": _utc_now(),
            "provenance": copy.deepcopy(dict(provenance)),
            "execution": {},
            "stages": [],
            "metrics": {},
            "outputs": {},
            "warnings": [],
        }

    @contextlib.contextmanager
    def stage(
        self,
        stage_id: str,
        *,
        attempt: int = 1,
        cache_status: str = "not_applicable",
        cache_key: Optional[str] = None,
    ) -> Iterator[_StageScope]:
        if not isinstance(stage_id, str) or not _STAGE_ID.fullmatch(stage_id):
            raise ValueError("stage_id must be a stable lower-case identifier")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if cache_status not in _CACHE_STATUSES:
            raise ValueError("invalid cache status")
        if cache_status in {"hit", "miss"} and (not isinstance(cache_key, str) or not _CACHE_KEY.fullmatch(cache_key)):
            raise ValueError("cache key is required for a hit or miss")
        if cache_status in {"disabled", "not_applicable"} and cache_key is not None:
            raise ValueError("cache key is only valid for a hit or miss")
        cache: dict[str, Any] = {"status": cache_status}
        if cache_key is not None:
            cache["key"] = cache_key
        scope = _StageScope(self, stage_id, attempt, cache)
        scope._started_wall = time.perf_counter()
        scope._started_cpu = time.process_time()
        try:
            yield scope
        except BaseException as exc:
            scope._finish(exc)
            raise
        else:
            scope._finish(None)

    def _append_stage(self, stage: Mapping[str, Any]) -> None:
        with self._lock:
            self._report["stages"].append(copy.deepcopy(dict(stage)))

    def warning(self, message: str) -> None:
        if not isinstance(message, str) or not message:
            raise ValueError("warning must be a non-empty string")
        with self._lock:
            self._report["warnings"].append(message)

    def finalize(
        self,
        *,
        metrics: Optional[Mapping[str, Any]] = None,
        outputs: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        report = copy.deepcopy(self._report)
        report["execution"] = {
            "wall_clock_seconds": max(0.0, time.perf_counter() - self._started_wall),
            "cpu_seconds": max(0.0, time.process_time() - self._started_cpu),
        }
        report["metrics"] = copy.deepcopy(dict(metrics or {}))
        performance = report["metrics"].setdefault("performance", {})
        if not isinstance(performance, MutableMapping):
            raise ValueError("metrics.performance must be an object")
        performance.setdefault("total_wall_clock_seconds", report["execution"]["wall_clock_seconds"])
        report["outputs"] = copy.deepcopy(dict(outputs or {}))
        validate_diagnostic(report)
        return report


def atomic_write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    """Write JSON atomically, fsyncing the file and parent directory when supported."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (canonical_json(value) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".lightforge-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class CheckpointStore:
    """Atomic, content-addressed JSON checkpoint store with corruption detection."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not _CACHE_KEY.fullmatch(key):
            raise ValueError("checkpoint key must be a sha256 content address")
        digest = key.split(":", 1)[1]
        return self.root / digest[:2] / f"{digest}.json"

    def write(self, key: str, identity: Mapping[str, Any], payload: Mapping[str, Any]) -> Path:
        if not isinstance(identity, Mapping):
            raise ValueError("checkpoint identity must be an object")
        if not isinstance(payload, Mapping):
            raise ValueError("checkpoint payload must be an object")
        errors: list[str] = []
        _validate_json_value(identity, "checkpoint.identity", errors)
        _validate_json_value(payload, "checkpoint.payload", errors)
        if errors:
            raise ContractValidationError(errors)
        record = {
            "cache_format_version": CACHE_FORMAT_VERSION,
            "cache_key": key,
            "identity": copy.deepcopy(dict(identity)),
            "payload_sha256": digest_json(payload),
            "created_at": _utc_now(),
            "payload": copy.deepcopy(dict(payload)),
        }
        path = self._path(key)
        atomic_write_json(path, record)
        return path

    def read(self, key: str, *, expected_identity: Optional[Mapping[str, Any]] = None) -> Optional[dict[str, Any]]:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CacheCorruptionError(f"checkpoint cannot be decoded: {path.name}") from exc
        errors: list[str] = []
        _validate_json_value(record, "checkpoint", errors)
        record = _require_mapping(record, "checkpoint", errors)
        if record.get("cache_format_version") != CACHE_FORMAT_VERSION:
            errors.append("checkpoint cache format version does not match")
        if record.get("cache_key") != key:
            errors.append("checkpoint key does not match its path")
        identity = _require_mapping(record.get("identity"), "checkpoint.identity", errors)
        payload = _require_mapping(record.get("payload"), "checkpoint.payload", errors)
        payload_sha = _require_sha256(record.get("payload_sha256"), "checkpoint.payload_sha256", errors)
        if payload_sha and payload_sha != digest_json(payload):
            errors.append("checkpoint payload digest does not match")
        if expected_identity is not None and canonical_json(identity) != canonical_json(expected_identity):
            errors.append("checkpoint identity does not match this analysis")
        if errors:
            raise CacheCorruptionError("; ".join(errors))
        return copy.deepcopy(dict(payload))

    def discard(self, key: str) -> bool:
        path = self._path(key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False


def benchmark_run(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    """Project a complete diagnostic into a gate-compatible benchmark run."""
    validate_diagnostic(diagnostic)
    return {
        "track_id": diagnostic["track_id"],
        "run_id": diagnostic["run_id"],
        "metrics": copy.deepcopy(diagnostic["metrics"]),
        "provenance": copy.deepcopy(diagnostic["provenance"]),
        "diagnostic_sha256": digest_json(diagnostic),
    }


APP_RUN_OBSERVATION_SCHEMA_VERSION = 1
_APP_RUN_OBSERVATION_KIND = "lightforge.completed-analysis-run"
_APP_RUN_OBSERVATION_RUN_KIND = "fresh-completed"
_OBSERVATION_MAX_SECONDS = 21600.0
_OBSERVATION_MAX_COUNTER = 1_000_000
_OBSERVATION_STAGES = ("bass", "recurrence", "rhythm", "separation", "voice")
_OBSERVATION_SOURCES = frozenset({"performance.now", "date.now", "unavailable"})
_OBSERVATION_STATES = frozenset({"available", "fallback", "unavailable", "observed-error"})
_OBSERVATION_REASONS = frozenset({
    "clock-unavailable",
    "clock-observed-error",
    "worker-clock-unavailable",
    "worker-clock-observed-error",
    "restored-stage-zero-cost",
})
_OBSERVATION_IMPLEMENTATIONS = {
    "precision": {
        "rhythmModelFamily": "beat-this-full",
        "separationModelFamily": "deux",
    },
    "balanced": {
        "rhythmModelFamily": "beat-this-compact",
        "separationModelFamily": "mdx",
    },
}
_OBSERVATION_RUNTIME_KINDS = frozenset({"android-cpu-plus-web", "web-wasm", "unknown"})


def _observation_exact_keys(value: Any, expected: set[str], path: str, errors: list[str]) -> Mapping[str, Any]:
    value = _require_mapping(value, path, errors)
    actual = set(value)
    if actual != expected:
        errors.append(f"{path} must contain exactly {sorted(expected)}")
    return value


def _observation_counter(value: Any, path: str, errors: list[str]) -> Optional[int]:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > _OBSERVATION_MAX_COUNTER:
        errors.append(f"{path} must be a bounded non-negative integer")
        return None
    return value


def _validate_observed_timing(
    value: Any, path: str, errors: list[str], *, worker: bool = False, restored: bool = False
) -> Optional[float]:
    timing = _observation_exact_keys(value, {"reason", "seconds", "source", "status"}, path, errors)
    source = timing.get("source")
    status = timing.get("status")
    seconds = timing.get("seconds")
    reason = timing.get("reason")
    if not isinstance(source, str) or source not in _OBSERVATION_SOURCES:
        errors.append(f"{path}.source is invalid")
    if not isinstance(status, str) or status not in _OBSERVATION_STATES:
        errors.append(f"{path}.status is invalid")
    if seconds is not None and (
        not _is_number(seconds) or float(seconds) < 0 or float(seconds) > _OBSERVATION_MAX_SECONDS
    ):
        errors.append(f"{path}.seconds must be null or a bounded non-negative finite number")
    if reason is not None and (not isinstance(reason, str) or reason not in _OBSERVATION_REASONS):
        errors.append(f"{path}.reason is not an allowlisted observation reason")
    if status == "available":
        if source != "performance.now" or seconds is None or reason is not None:
            errors.append(f"{path} available timing must be measured by performance.now")
    elif status == "fallback":
        if source != "date.now" or seconds is None or reason is not None:
            errors.append(f"{path} fallback timing must be measured by date.now")
    elif status == "observed-error":
        expected_reason = "worker-clock-observed-error" if worker else "clock-observed-error"
        if source not in ("performance.now", "date.now") or seconds is not None or reason != expected_reason:
            errors.append(f"{path} observed-error timing is invalid")
    elif status == "unavailable":
        expected_reason = (
            "restored-stage-zero-cost"
            if restored
            else "worker-clock-unavailable"
            if worker
            else "clock-unavailable"
        )
        if source != "unavailable" or seconds is not None or reason != expected_reason:
            errors.append(f"{path} unavailable timing is invalid")
    return float(seconds) if _is_number(seconds) and 0 <= float(seconds) <= _OBSERVATION_MAX_SECONDS else None


def validate_completed_app_run_observation(observation: Any) -> None:
    """Fail closed on a privacy-bounded observation from one fresh completed app run.

    The static schema intentionally excludes audio, project identity, user text,
    paths, cache keys, raw model/runtime strings, timestamps, and diagnostics.
    It is supplementary evidence only and cannot establish a quality comparison.
    """
    errors: list[str] = []
    value = _observation_exact_keys(
        observation,
        {"analysis", "kind", "privacy", "resources", "runKind", "schemaVersion", "timing"},
        "observation",
        errors,
    )
    if value.get("schemaVersion") != APP_RUN_OBSERVATION_SCHEMA_VERSION:
        errors.append(f"observation.schemaVersion must equal {APP_RUN_OBSERVATION_SCHEMA_VERSION}")
    if value.get("kind") != _APP_RUN_OBSERVATION_KIND:
        errors.append("observation.kind is unsupported")
    if value.get("runKind") != _APP_RUN_OBSERVATION_RUN_KIND:
        errors.append("observation.runKind must identify a fresh completed analysis")

    privacy = _observation_exact_keys(
        value.get("privacy"), {"audioContent", "projectIdentity", "userContent"}, "observation.privacy", errors
    )
    for field in ("audioContent", "projectIdentity", "userContent"):
        if privacy.get(field) != "excluded":
            errors.append(f"observation.privacy.{field} must be excluded")

    timing = _observation_exact_keys(value.get("timing"), {"analysis", "choreography", "total"}, "observation.timing", errors)
    analysis_seconds = _validate_observed_timing(timing.get("analysis"), "observation.timing.analysis", errors)
    choreography_seconds = _validate_observed_timing(timing.get("choreography"), "observation.timing.choreography", errors)
    total_seconds = _validate_observed_timing(timing.get("total"), "observation.timing.total", errors)
    for name, phase_seconds in (("analysis", analysis_seconds), ("choreography", choreography_seconds)):
        if total_seconds is not None and phase_seconds is not None and total_seconds + 1e-6 < phase_seconds:
            errors.append(f"observation.timing.total is smaller than observation.timing.{name}")

    analysis = _observation_exact_keys(
        value.get("analysis"), {"cache", "implementation", "quality", "stages"}, "observation.analysis", errors
    )
    quality = analysis.get("quality")
    if not isinstance(quality, str) or quality not in _OBSERVATION_IMPLEMENTATIONS:
        errors.append("observation.analysis.quality is invalid")
    implementation = _observation_exact_keys(
        analysis.get("implementation"),
        {"rhythmModelFamily", "runtimeKind", "separationModelFamily"},
        "observation.analysis.implementation",
        errors,
    )
    expected = _OBSERVATION_IMPLEMENTATIONS.get(quality, {}) if isinstance(quality, str) else {}
    if (
        implementation.get("rhythmModelFamily") != expected.get("rhythmModelFamily")
        or implementation.get("separationModelFamily") != expected.get("separationModelFamily")
        or not isinstance(implementation.get("runtimeKind"), str)
        or implementation.get("runtimeKind") not in _OBSERVATION_RUNTIME_KINDS
    ):
        errors.append("observation.analysis.implementation is not an allowlisted family")

    stages = analysis.get("stages")
    restored_names: list[str] = []
    if not isinstance(stages, list) or not 1 <= len(stages) <= len(_OBSERVATION_STAGES):
        errors.append("observation.analysis.stages must be a non-empty bounded array")
    else:
        previous_index = -1
        for index, stage in enumerate(stages):
            path = f"observation.analysis.stages[{index}]"
            stage = _observation_exact_keys(stage, {"restored", "stageId", "timing"}, path, errors)
            stage_id = stage.get("stageId")
            if not isinstance(stage_id, str) or stage_id not in _OBSERVATION_STAGES:
                errors.append(f"{path}.stageId is not allowlisted")
                stage_index = previous_index
            else:
                stage_index = _OBSERVATION_STAGES.index(stage_id)
                if stage_index <= previous_index:
                    errors.append(f"{path}.stageId must be strictly ordered and unique")
            previous_index = stage_index
            restored = stage.get("restored")
            if not isinstance(restored, bool):
                errors.append(f"{path}.restored must be a boolean")
                restored = False
            _validate_observed_timing(stage.get("timing"), f"{path}.timing", errors, worker=True, restored=restored)
            stage_timing = stage.get("timing") if isinstance(stage.get("timing"), Mapping) else {}
            if restored is True:
                if not (
                    stage_timing.get("source") == "unavailable"
                    and stage_timing.get("status") == "unavailable"
                    and stage_timing.get("seconds") is None
                    and stage_timing.get("reason") == "restored-stage-zero-cost"
                ):
                    errors.append(f"{path} restored stage must not claim a measured or zero-cost time")
                if isinstance(stage_id, str):
                    restored_names.append(stage_id)

    cache = _observation_exact_keys(
        analysis.get("cache"),
        {"restoredStageCount", "restoredStageNames", "separationRestoredPassages"},
        "observation.analysis.cache",
        errors,
    )
    restored_count = _observation_counter(cache.get("restoredStageCount"), "observation.analysis.cache.restoredStageCount", errors)
    if cache.get("separationRestoredPassages") is not None:
        _observation_counter(cache.get("separationRestoredPassages"), "observation.analysis.cache.separationRestoredPassages", errors)
    names = cache.get("restoredStageNames")
    if (
        not isinstance(names, list)
        or any(not isinstance(name, str) or name not in _OBSERVATION_STAGES for name in names)
        or names != restored_names
        or restored_count != len(restored_names)
    ):
        errors.append("observation.analysis.cache restored stage summary is inconsistent")

    resources = _observation_exact_keys(
        value.get("resources"), {"observedStageCount", "schedulerWaitSeconds", "status"}, "observation.resources", errors
    )
    if not isinstance(resources.get("status"), str) or resources.get("status") not in {"available", "unavailable"}:
        errors.append("observation.resources.status is invalid")
    observed_stage_count = _observation_counter(resources.get("observedStageCount"), "observation.resources.observedStageCount", errors)
    if observed_stage_count is not None and observed_stage_count > len(_OBSERVATION_STAGES):
        errors.append("observation.resources.observedStageCount exceeds the static stage allowlist")
    wait = resources.get("schedulerWaitSeconds")
    if wait is not None and (
        not _is_number(wait) or float(wait) < 0 or float(wait) > _OBSERVATION_MAX_SECONDS
    ):
        errors.append("observation.resources.schedulerWaitSeconds must be null or a bounded non-negative finite number")
    if resources.get("status") == "unavailable" and (observed_stage_count != 0 or wait is not None):
        errors.append("unavailable observation resources must not claim measurements")
    if errors:
        raise ContractValidationError(errors)


def observed_app_run_time_projection(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a valid app observation into explicitly non-comparable evidence.

    The output has no workload, corpus, environment, model runtime string, or
    benchmark metric binding.  Unavailable timings stay ``None``; they are
    never converted to a synthetic zero.
    """
    validate_completed_app_run_observation(observation)
    timing = copy.deepcopy(dict(observation["timing"]))
    stages = {
        stage["stageId"]: copy.deepcopy(dict(stage["timing"]))
        for stage in observation["analysis"]["stages"]
    }
    observed = any(item["seconds"] is not None for item in [*timing.values(), *stages.values()])
    return {
        "schema_version": 1,
        "kind": "supplementary-observed-app-run-timing",
        "release_eligibility": {
            "status": "not_comparable",
            "reason": "unbound-completed-app-run-observation",
        },
        "observed_time_available": observed,
        "timing": timing,
        "stages": stages,
        "cache": copy.deepcopy(dict(observation["analysis"]["cache"])),
        "resources": copy.deepcopy(dict(observation["resources"])),
    }


def benchmark_run_with_observed_app_run(
    diagnostic: Mapping[str, Any], observation: Mapping[str, Any]
) -> dict[str, Any]:
    """Attach a supplemental observation without altering benchmark metrics or pass state."""
    result = benchmark_run(diagnostic)
    result["supplementary_observed_app_run"] = observed_app_run_time_projection(observation)
    return result

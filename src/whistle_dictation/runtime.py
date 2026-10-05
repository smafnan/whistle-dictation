"""Download verified, version-pinned public artifacts only on explicit setup."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import urllib.request
import zipfile
from pathlib import Path

ENGINE_REVISION = "c7c415a3d1b3d929014bc6e866d51ebb971f7089"
MODEL_REVISION = "b358ddadd89b7a713b5aa131f23032d3cca1b251"
MODEL_SHA256 = "b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb"
WHEELS = {
    "AMD64": ("win_amd64", "4f5fc86abfc50d551cdb237a34b501f36d82d4b6f5911ee7bec4e9532d44dd95"),
    "ARM64": ("win_arm64", "39806d54910c207cd0ac5dc60009c8c5330072ef729711d74061faf0e99e7a6c"),
}
LIBRARY_SHA256 = {
    "AMD64": "de2e2c39cd311fbd9971fad4736abc329ed970653674c203e149c4ef27fd1c62",
    "ARM64": "a4b13bfde65a188982c309b52133ab4ad7d0e63a9b46ba55c3b76a1d32927f7a",
}


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def configure_environment(root: Path) -> None:
    os.environ["NEEDLE_TELEMETRY"] = "0"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["NEEDLE3_LIB_PATH"] = str(root / "models" / "libneedle.dll")
    os.environ["NEEDLE_WHISTLE_WEIGHTS"] = str(root / "models" / "whistle.cact")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, target: Path, expected: str) -> None:
    if target.is_file() and sha256(target) == expected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "WhistleDictation/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as source, partial.open("wb") as output:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                output.write(block)
        if sha256(partial) != expected:
            raise RuntimeError(f"Integrity check failed for {target.name}; setup aborted.")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def download_runtime(root: Path) -> dict:
    if sys.platform != "win32" or platform.machine().upper() not in WHEELS:
        raise RuntimeError("This application supports 64-bit Windows AMD64/ARM64.")
    tag, wheel_hash = WHEELS[platform.machine().upper()]
    wheel_name = f"cactus_needle-3.1.0-py3-none-{tag}.whl"
    wheel = root / ".cache" / wheel_name
    _download(f"https://huggingface.co/Cactus-Compute/needle3/resolve/{ENGINE_REVISION}/python/{wheel_name}",
              wheel, wheel_hash)
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    library = models / "libneedle.dll"
    with zipfile.ZipFile(wheel) as archive:
        data = archive.read("needle/libneedle3.dll")
    temporary = library.with_suffix(".dll.partial")
    temporary.write_bytes(data)
    os.replace(temporary, library)
    weights = models / "whistle.cact"
    _download(f"https://huggingface.co/Cactus-Compute/whistle/resolve/{MODEL_REVISION}/whistle.cact",
              weights, MODEL_SHA256)
    manifest = {
        "package": "cactus-needle==3.1.0", "architecture": tag,
        "engine_revision": ENGINE_REVISION, "model_revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA256, "library_sha256": sha256(library),
        "wheel_sha256": wheel_hash,
    }
    (models / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_runtime(root: Path) -> dict:
    models = root / "models"
    try:
        manifest = json.loads((models / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Runtime manifest must be an object.")
        library, weights = models / "libneedle.dll", models / "whistle.cact"
        expected_library = LIBRARY_SHA256.get(platform.machine().upper())
        if sha256(weights) != MODEL_SHA256 or sha256(library) != expected_library:
            raise RuntimeError("Model/runtime checksum mismatch. Run Setup.ps1 again.")
        architecture = WHEELS.get(platform.machine().upper(), (None, None))[0]
        if manifest["architecture"] != architecture:
            raise RuntimeError("Runtime architecture mismatch. Run Setup.ps1 on this computer.")
        return manifest
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError("Whistle runtime is not ready. Run Setup.ps1 first.") from exc

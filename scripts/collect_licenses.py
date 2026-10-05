"""Copy installed dependency license resources for the portable distribution."""
from importlib import metadata
from pathlib import Path
import shutil
import sys
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / "dist" / "WhistleDictation" / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    interpreter_root = Path(sys.base_prefix)
    interpreter_license = next(
        (path for path in (interpreter_root / "LICENSE.txt", interpreter_root / "LICENSE")
         if path.is_file()), None
    )
    if interpreter_license is None:
        raise RuntimeError("The bundled Python interpreter license could not be found.")
    shutil.copyfile(interpreter_license, destination / "Python-LICENSE.txt")
    names = [line.split("==")[0] for line in
             (root / "requirements.lock.txt").read_text().splitlines()]
    # The executable includes PyInstaller's bootloader as well as Python.
    for name in dict.fromkeys([*names, "pyinstaller"]):
        package = metadata.distribution(name)
        for item in package.files or []:
            if any(part.lower().startswith(("license", "copying", "notice")) for part in item.parts):
                source = Path(package.locate_file(item))
                if source.is_file():
                    target = destination / name / Path(*item.parts[-3:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    # Upstream native model/runtime license, immutable official revision.
    license_path = root / "models" / "UPSTREAM-LICENSE.txt"
    if not license_path.exists():
        if "--offline" in sys.argv:
            raise RuntimeError("Run license collection once online before an offline build.")
        url = "https://huggingface.co/Cactus-Compute/whistle/resolve/b358ddadd89b7a713b5aa131f23032d3cca1b251/LICENSE"
        with urllib.request.urlopen(url, timeout=30) as response:
            license_path.write_bytes(response.read())
    shutil.copyfile(license_path, destination / "Cactus-Apache-2.0.txt")
    shutil.copyfile(root / "LICENSE", destination / "LICENSE")
    shutil.copyfile(root / "THIRD_PARTY.md", destination / "THIRD_PARTY.md")


if __name__ == "__main__":
    main()

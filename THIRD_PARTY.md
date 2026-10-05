# Third-party components

This app uses the installed package versions in `requirements.lock.txt`.
The project's own source is [MIT licensed](LICENSE). That license does not replace
the licenses of the model, runtime, Qt, or other dependencies.
The portable build retains separate native Qt and Whistle libraries and includes
dependency license resources in `licenses/`. Upstream components retain their
own copyrights and license terms.

| Component | Role | Upstream |
| --- | --- | --- |
| CPython | Bundled Python interpreter and standard library | https://www.python.org/ ; https://docs.python.org/3/license.html |
| Cactus Needle / Whistle | Speech API, native CPU runtime and model weights | https://github.com/cactus-compute/needle ; https://huggingface.co/Cactus-Compute/whistle |
| PySide6 / Qt | Window, tray and indicator | https://doc.qt.io/qtforpython-6/ |
| NumPy | Audio arrays and segmentation | https://numpy.org/ |
| python-sounddevice / PortAudio | Microphone capture | https://python-sounddevice.readthedocs.io/ |
| python-soxr / libsoxr | Sample-rate conversion | https://python-soxr.readthedocs.io/ |
| PyInstaller | Packaging and bundled executable bootloader | https://pyinstaller.org/ |

`scripts/collect_licenses.py` copies the interpreter license, installed dependency
and PyInstaller license files, and the official model's Apache-2.0 text into the
distribution. The source package and
model revisions are recorded in `models/manifest.json` and the architecture docs.

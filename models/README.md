Setup downloads `whistle.cact` and the Windows Needle3 speech runtime into this folder.
`manifest.json` records immutable upstream revisions and checksums. The app verifies
model and DLL hashes against constants in `runtime.py` before loading native code.
The model is Apache-2.0. See https://huggingface.co/Cactus-Compute/whistle and
https://github.com/cactus-compute/needle/blob/main/LICENSE for upstream licensing.
Do not replace these artifacts with a custom model without updating the compatibility
and integrity checks deliberately. No fine-tuned checkpoint is supplied in this version.

# Portable one-folder Windows build. Model/DLL are copied beside the exe by Build.ps1.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

project = Path(SPECPATH)
analysis = Analysis(
    [str(project / 'launcher.py')],
    pathex=[str(project / 'src')],
    binaries=[],
    datas=collect_data_files('_sounddevice_data'),
    hiddenimports=['needle.agent.whistle', 'needle.agent.fetch', 'soxr', 'sounddevice', '_cffi_backend'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['jax', 'jaxlib', 'torch', 'tensorflow', 'matplotlib', 'needle.model', 'pytest', 'pygments'],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
                 name='WhistleDictation', debug=False, bootloader_ignore_signals=False,
                 strip=False, upx=False, console=False, disable_windowed_traceback=False)
collection = COLLECT(executable, analysis.binaries, analysis.datas,
                     strip=False, upx=False, name='WhistleDictation')

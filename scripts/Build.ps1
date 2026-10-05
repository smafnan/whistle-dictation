$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot '.cache\pyinstaller'
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm WhistleDictation.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    $destination = Join-Path $projectRoot 'dist\WhistleDictation\models'
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    foreach ($name in @('libneedle.dll','whistle.cact','manifest.json')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot "models\$name") -Destination $destination -Force
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\PORTABLE.md') -Destination 'dist\WhistleDictation\README.md' -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'docs') -Destination 'dist\WhistleDictation' -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'THIRD_PARTY.md') -Destination 'dist\WhistleDictation\THIRD_PARTY.md' -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination 'dist\WhistleDictation\LICENSE' -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'settings.example.json') -Destination 'dist\WhistleDictation\settings.example.json' -Force
    & '.\.venv\Scripts\python.exe' scripts\collect_licenses.py
    if ($LASTEXITCODE -ne 0) { throw 'Dependency license collection failed.' }
    Write-Host 'Built dist\WhistleDictation\WhistleDictation.exe. Keep the entire folder together.'
} finally {
    Pop-Location
}

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    & $pythonPath -m ruff check src tests launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'Lint checks failed.' }
    & $pythonPath -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $pythonPath -m whistle_dictation --doctor
    if ($LASTEXITCODE -ne 0) { throw 'Runtime checks failed.' }
    & $pythonPath -m whistle_dictation --smoke-test
    if ($LASTEXITCODE -ne 0) { throw 'App smoke test failed.' }
} finally {
    Pop-Location
}

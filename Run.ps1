param([switch]$Hidden)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Run Setup.ps1 first.'
}
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$launchArgs = @('-m', 'whistle_dictation')
if ($Hidden) { $launchArgs += '--hidden' }
& $pythonPath @launchArgs
if ($LASTEXITCODE -ne 0) { throw 'Whistle Dictation exited with an error. Check data\app.log.' }

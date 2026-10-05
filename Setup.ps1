param([switch]$SkipModel, [switch]$SkipDev)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$previousEnvironment = @{}
foreach ($variableName in @('TEMP','TMP','PIP_CACHE_DIR','PYTHONPATH','NEEDLE_TELEMETRY','DO_NOT_TRACK')) {
    $previousEnvironment[$variableName] = [Environment]::GetEnvironmentVariable($variableName, 'Process')
}
Push-Location -LiteralPath $projectRoot
try {
    New-Item -ItemType Directory -Force -Path '.cache','models','data' | Out-Null
    $env:TEMP = Join-Path $projectRoot '.cache'
    $env:TMP = $env:TEMP
    $env:PIP_CACHE_DIR = Join-Path $projectRoot '.cache\pip'
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $env:NEEDLE_TELEMETRY = '0'
    $env:DO_NOT_TRACK = '1'
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3.12 -m venv .venv
        } else {
            & python -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Creating Python environment failed. Install Python 3.12 (64-bit).' }
    }
    & $pythonPath -c "import sys; assert sys.version_info[:2] == (3,12), 'Use Python 3.12 (64-bit)'; assert sys.maxsize > 2**32, 'Use 64-bit Python'"
    if ($LASTEXITCODE -ne 0) { throw 'This setup requires 64-bit Python 3.12.' }
    $requirements = if ($SkipDev) { 'requirements.lock.txt' } else { 'requirements-dev.lock.txt' }
    & $pythonPath -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    if (-not $SkipModel) {
        & $pythonPath -m whistle_dictation --download-model
        if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Re-run setup when connected.' }
        & $pythonPath -m whistle_dictation --doctor
        if ($LASTEXITCODE -ne 0) { throw 'Runtime checks failed. See the doctor output above.' }
    }
    Write-Host 'Setup complete. Run Run.cmd, then use Ctrl+Alt+Shift+Space in a textbox.'
} finally {
    foreach ($variableName in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($variableName, $previousEnvironment[$variableName], 'Process')
    }
    Pop-Location
}

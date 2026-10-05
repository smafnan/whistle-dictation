$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    New-Item -ItemType Directory -Force -Path '.cache' | Out-Null
    Add-Type -AssemblyName System.Speech
    $speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $speech.Rate = -2
        $speech.SetOutputToWaveFile((Join-Path $projectRoot '.cache\speech-long.wav'))
        $reference = Get-Content -LiteralPath 'tests\fixtures\synthetic-reference.txt' -Raw
        $speech.Speak($reference)
    } finally {
        $speech.Dispose()
    }
    & '.\.venv\Scripts\python.exe' scripts\verify_speech.py
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic speech verification failed.' }
} finally {
    Pop-Location
}

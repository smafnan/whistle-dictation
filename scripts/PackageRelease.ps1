param([string]$Version = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not $Version) {
        $Version = & '.\.venv\Scripts\python.exe' -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
        if ($LASTEXITCODE -ne 0) { throw 'Could not read project version.' }
    }
    if ($Version -notmatch '^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$') {
        throw 'Release version must be a semantic version, such as 0.1.0.'
    }
    $sourcePath = Join-Path $projectRoot 'dist\WhistleDictation'
    if (-not (Test-Path -LiteralPath (Join-Path $sourcePath 'WhistleDictation.exe'))) {
        throw 'Run scripts\Build.ps1 before packaging a release.'
    }
    $manifest = Get-Content -LiteralPath (Join-Path $sourcePath 'models\manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.architecture -ne 'win_amd64') {
        throw 'This release script currently packages the Windows AMD64 build only.'
    }
    foreach ($requiredFile in @('LICENSE','README.md','settings.example.json','models\libneedle.dll','models\whistle.cact','licenses\Cactus-Apache-2.0.txt','licenses\Python-LICENSE.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourcePath $requiredFile) -PathType Leaf)) {
            throw "Incomplete distribution: $requiredFile"
        }
    }
    $releasePath = Join-Path $projectRoot 'releases'
    New-Item -ItemType Directory -Force -Path $releasePath | Out-Null
    $archivePath = Join-Path $releasePath "WhistleDictation-v$Version-windows-x64.zip"
    $partialPath = $archivePath + '.partial'
    $releasePrefix = [System.IO.Path]::GetFullPath($releasePath).TrimEnd('\') + '\'
    foreach ($targetPath in @($archivePath, $partialPath)) {
        if (-not [System.IO.Path]::GetFullPath($targetPath).StartsWith(
            $releasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Release output escaped the intended release directory.'
        }
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $fileStream = [System.IO.File]::Open($partialPath, [System.IO.FileMode]::Create)
    $archive = New-Object System.IO.Compression.ZipArchive($fileStream, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $sourcePrefix = $sourcePath.TrimEnd('\') + '\'
        foreach ($file in (Get-ChildItem -LiteralPath $sourcePath -Recurse -File -Force)) {
            if (-not $file.FullName.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw 'A package input escaped the distribution directory.'
            }
            $relativePath = $file.FullName.Substring($sourcePrefix.Length).Replace('\', '/')
            if ($relativePath.StartsWith('data/', [System.StringComparison]::OrdinalIgnoreCase) -or
                $file.Extension -in @('.log','.wav','.pem','.key','.pfx','.p12') -or
                $file.Name -like '.env*') { continue }
            $entryName = 'WhistleDictation/' + $relativePath
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive, $file.FullName, $entryName, [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    } finally {
        $archive.Dispose()
        $fileStream.Dispose()
    }
    Move-Item -LiteralPath $partialPath -Destination $archivePath -Force
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([System.IO.Path]::GetFileName($archivePath))" |
        Set-Content -LiteralPath (Join-Path $releasePath 'SHA256SUMS.txt') -Encoding ascii
    Write-Host "Packaged $archivePath"
    Write-Host "SHA256 $hash"
} finally {
    Pop-Location
}

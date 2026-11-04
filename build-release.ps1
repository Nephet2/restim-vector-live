param([string]$WheelDirectory = "wheels")
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $project
try {
    python packaging/build_custom_source.py --wheel-dir $WheelDirectory --output dist
    if ($LASTEXITCODE -ne 0) { throw "Build failed. See docs/ARCHITECTURE.md for hash-locked wheel download instructions." }
    python packaging/check_archives.py
    if ($LASTEXITCODE -ne 0) { throw "Archive validation failed" }
} finally { Pop-Location }

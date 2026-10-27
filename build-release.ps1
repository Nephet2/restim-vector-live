$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = (Select-String -Path (Join-Path $project "vector1a\__init__.py") -Pattern '__version__ = "(.+)"').Matches.Groups[1].Value
$stage = Join-Path $project "dist\Vector1A-$version"
$zip = Join-Path $project "dist\Vector1A-$version-windows.zip"
$distRoot = [System.IO.Path]::GetFullPath((Join-Path $project "dist")) + [System.IO.Path]::DirectorySeparatorChar
foreach ($target in @($stage, $zip)) {
    if (-not [System.IO.Path]::GetFullPath($target).StartsWith($distRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Release target is outside dist: $target"
    }
}
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$files = @("vector1a", "tests", "packaging", "build-exe.ps1", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "PILLOW_LICENSE.txt", "CONTRIBUTING.md", "SECURITY.md", "pyproject.toml", "start-vector1a.bat", "build-release.ps1", "build-release.bat", "HOWL-SETUP.md", "CIVET_PRESSURE.md")
foreach ($item in $files) { Copy-Item -LiteralPath (Join-Path $project $item) -Destination $stage -Recurse }
Get-ChildItem -LiteralPath $project -Filter "RELEASE_NOTES_*.md" | Copy-Item -Destination $stage
Get-ChildItem -LiteralPath $stage -Recurse -Directory -Filter __pycache__ | ForEach-Object {
    $cachePath = [System.IO.Path]::GetFullPath($_.FullName)
    if ($cachePath.StartsWith([System.IO.Path]::GetFullPath($stage) + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $cachePath -Recurse -Force
    }
}
$privateSensorSettings = Join-Path $stage "vector1a\civet-pressure.json"
if (Test-Path -LiteralPath $privateSensorSettings) { Remove-Item -LiteralPath $privateSensorSettings -Force }
Compress-Archive -LiteralPath $stage -DestinationPath $zip
Write-Host "Created $zip"

$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$version = (Select-String -LiteralPath (Join-Path $project "vector1a\__init__.py") -Pattern '__version__ = "(.+)"').Matches.Groups[1].Value
$name = "Vector1A-$version"
$dist = Join-Path $project "dist-exe"
$work = Join-Path $project "build\pyinstaller"
$spec = Join-Path $project "build"
$entry = Join-Path $project "packaging\windows_entry.py"
# PyInstaller rebuilds only its own build outputs. User profiles are excluded.
python -m PyInstaller --noconfirm --clean --onedir --windowed --name $name --distpath $dist --workpath $work --specpath $spec --paths $project --collect-all bleak --add-data "$(Join-Path $project 'vector1a\event_definitions.yml');vector1a" $entry
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
$stage = Join-Path $dist $name
foreach ($file in @("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "PILLOW_LICENSE.txt", "HOWL-SETUP.md", "CIVET_PRESSURE.md", "RELEASE_NOTES_1.6.0-alpha83.md")) {
    Copy-Item -LiteralPath (Join-Path $project $file) -Destination $stage
}
$zip = Join-Path $project "dist\$name-windows-exe.zip"
New-Item -ItemType Directory -Path (Split-Path -Parent $zip) -Force | Out-Null
Compress-Archive -LiteralPath $stage -DestinationPath $zip -Force
Write-Host "Created $zip"

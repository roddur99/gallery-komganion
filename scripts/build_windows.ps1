param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .\build, .\dist
}

python -m pip install -e ".[packaging]"
python -m PyInstaller --noconfirm --clean .\gallery-komganion.spec

Write-Host ""
Write-Host "Built: dist\Gallery Komganion\Gallery Komganion.exe"

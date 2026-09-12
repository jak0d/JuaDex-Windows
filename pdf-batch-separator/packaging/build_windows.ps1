<#
.SYNOPSIS
    Builds PDF Batch Separator for 64-bit Windows: executable, installer and
    portable ZIP, with SHA-256 checksums.

.DESCRIPTION
    Run from the project root in a 64-bit Python 3.12 environment:

        powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1

.PARAMETER SkipInstaller
    Build only the application and the portable ZIP (no Inno Setup needed).

.PARAMETER Sign
    Sign the executable and installer with signtool using $env:PBS_CERT_THUMBPRINT.
#>

[CmdletBinding()]
param(
    [switch]$SkipInstaller,
    [switch]$Sign
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$AppName = "PDF Batch Separator"
$Version = "1.0.0"
$TimestampUrl = "http://timestamp.digicert.com"

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

# --- sanity checks ---------------------------------------------------------
Write-Step "Checking the build environment"

$arch = (Get-CimInstance Win32_Processor).AddressWidth
if ($arch -ne 64) { throw "A 64-bit build environment is required." }

$pythonArch = & python -c "import struct; print(struct.calcsize('P') * 8)"
if ($pythonArch.Trim() -ne "64") { throw "A 64-bit Python interpreter is required (found $pythonArch-bit)." }

$pyVersion = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Python $($pyVersion.Trim()) (64-bit)"
if ($pyVersion.Trim() -ne "3.12") {
    Write-Warning "Python 3.12 is the pinned target; found $($pyVersion.Trim())."
}

# --- dependencies ----------------------------------------------------------
Write-Step "Installing dependencies"
& python -m pip install --upgrade pip
& python -m pip install -e ".[dev,build]"

# --- tests -----------------------------------------------------------------
Write-Step "Running the test suite"
& python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; aborting the build." }

# --- licences --------------------------------------------------------------
Write-Step "Collecting dependency licences"
& python packaging\collect_licenses.py

# --- clean -----------------------------------------------------------------
Write-Step "Cleaning previous build output"
foreach ($directory in @("build", "dist", "installer_output")) {
    if (Test-Path $directory) { Remove-Item $directory -Recurse -Force }
}

# --- application -----------------------------------------------------------
Write-Step "Building the application with PyInstaller"
& python -m PyInstaller packaging\app.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$exePath = Join-Path "dist\$AppName" "$AppName.exe"
if (-not (Test-Path $exePath)) { throw "Expected executable not found: $exePath" }
Write-Host "Built $exePath"

# --- smoke test ------------------------------------------------------------
Write-Step "Smoke-testing the packaged application"
$process = Start-Process -FilePath $exePath -PassThru
Start-Sleep -Seconds 12
if ($process.HasExited) {
    throw "The packaged application exited immediately (code $($process.ExitCode))."
}
Stop-Process -Id $process.Id -Force
Write-Host "The application started and stayed running."

# --- signing ---------------------------------------------------------------
if ($Sign) {
    Write-Step "Signing the application"
    if (-not $env:PBS_CERT_THUMBPRINT) { throw "Set PBS_CERT_THUMBPRINT to sign." }
    & signtool sign /sha1 $env:PBS_CERT_THUMBPRINT /fd SHA256 `
        /tr $TimestampUrl /td SHA256 $exePath
    if ($LASTEXITCODE -ne 0) { throw "Signing the executable failed." }
}

# --- portable zip ----------------------------------------------------------
Write-Step "Creating the portable ZIP"
$zipName = "PDF-Batch-Separator-$Version-portable.zip"
if (Test-Path $zipName) { Remove-Item $zipName -Force }
Compress-Archive -Path "dist\$AppName\*" -DestinationPath $zipName
Write-Host "Created $zipName"

# --- installer -------------------------------------------------------------
if (-not $SkipInstaller) {
    Write-Step "Building the installer with Inno Setup"
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $iscc) {
        Write-Warning "Inno Setup 6 not found; skipping the installer."
    } else {
        & $iscc packaging\installer.iss
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

        $setup = "installer_output\PDF-Batch-Separator-$Version-Setup.exe"
        if ($Sign) {
            Write-Step "Signing the installer"
            & signtool sign /sha1 $env:PBS_CERT_THUMBPRINT /fd SHA256 `
                /tr $TimestampUrl /td SHA256 $setup
            if ($LASTEXITCODE -ne 0) { throw "Signing the installer failed." }
        }
        Write-Host "Created $setup"
    }
}

# --- checksums -------------------------------------------------------------
Write-Step "Computing SHA-256 checksums"
$checksumFile = "SHA256SUMS-$Version.txt"
if (Test-Path $checksumFile) { Remove-Item $checksumFile -Force }

Get-ChildItem -Path @($zipName, "installer_output\*.exe") -ErrorAction SilentlyContinue |
    ForEach-Object {
        $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
        "$hash  $($_.Name)" | Tee-Object -FilePath $checksumFile -Append
    }

Write-Step "Build complete"
Write-Host "Artefacts:"
Write-Host "  dist\$AppName\           (one-folder build)"
Write-Host "  $zipName"
if (-not $SkipInstaller) { Write-Host "  installer_output\" }
Write-Host "  $checksumFile"
if (-not $Sign) {
    Write-Host ""
    Write-Warning "This build is UNSIGNED. Windows SmartScreen will warn users;"
    Write-Warning "they must choose 'More info' then 'Run anyway'."
}

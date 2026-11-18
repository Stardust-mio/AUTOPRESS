<#
.SYNOPSIS
    Build the AutoPress release: dist\AutoPress\ (one-folder exe) and dist\AutoPress-<version>-win64.zip.

.DESCRIPTION
    OWNED BY G8 (SPEC 10.1). Run from any folder:
        powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1

    1. Uses the project's own Python (.venv\Scripts\python.exe) with PyInstaller 6.22.3
    2. Renders the icon (tools\make_icon.py) when autopress\resources\icon.ico is missing
    3. Clean PyInstaller build with autopress.spec -> dist\AutoPress\AutoPress.exe
    4. Self-test of the exe (AutoPress.exe --selftest report.json, must pass), then the same
       self-test from a copy in a folder whose path contains Chinese characters
    5. Zip: top folder AutoPress-<version> (exe + README, LICENSE, THIRD-PARTY-NOTICES.md,
       licenses\, docs\user_guide.md + docs\images\ when present) and 請先解壓縮再執行.txt next
       to it (running AutoPress.exe from inside the zip fails before any AutoPress code runs)
    Exit code 0 = success. The self-tests use a temporary data folder (AUTOPRESS_HOME), so the
    real %APPDATA%\AutoPress is never touched. This file is UTF-8 with BOM (Windows PowerShell
    5.1 reads BOM-less scripts in the ANSI code page).
#>

# Native tools (PyInstaller) log to stderr: judge success by exit codes, not by error records.
$ErrorActionPreference = 'Continue'

$Root      = $PSScriptRoot
$Python    = Join-Path $Root '.venv\Scripts\python.exe'
$Spec      = Join-Path $Root 'autopress.spec'
$Icon      = Join-Path $Root 'autopress\resources\icon.ico'
$DistDir   = Join-Path $Root 'dist'
$WorkDir   = Join-Path $Root 'build'
$AppDir    = Join-Path $DistDir 'AutoPress'
$AppExe    = Join-Path $AppDir 'AutoPress.exe'
$StageRoot = Join-Path $DistDir 'stage'
$SelfTestTimeoutMs = 180000
$UnzipNoteName = '請先解壓縮再執行.txt'
$UnzipNote = @'
請先把整個壓縮檔解壓縮（在壓縮檔上按右鍵 →「解壓縮全部」），
再打開解壓縮出來的 {TopName} 資料夾，執行裡面的 AutoPress.exe。
直接在壓縮檔裡面按兩下 AutoPress.exe 會無法啟動。

Unzip the whole archive first (right-click the zip -> "Extract All"),
then open the extracted {TopName} folder and run AutoPress.exe in it.
Starting AutoPress.exe from inside the zip does not work.
'@

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Stop-Build([string]$Text) {
    Write-Host ''
    Write-Host "BUILD FAILED: $Text" -ForegroundColor Red
    exit 1
}

function Remove-Path([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        } catch {
            Stop-Build "cannot remove $Path - is AutoPress still running? Close it and try again."
        }
    }
}

function Invoke-SelfTest([string]$Exe, [string]$WorkFolder) {
    # AutoPress.exe is a windowed program: Start-Process -Wait is the only way to get its exit code.
    $report = Join-Path $WorkFolder 'selftest.json'
    $home_ = Join-Path $WorkFolder 'data'
    New-Item -ItemType Directory -Force -Path $home_ | Out-Null
    $oldHome = $env:AUTOPRESS_HOME
    $env:AUTOPRESS_HOME = $home_
    try {
        $proc = Start-Process -FilePath $Exe -ArgumentList @('--selftest', ('"' + $report + '"')) -PassThru
        $null = $proc.Handle  # keeps the handle, so ExitCode is available after the exit
        if (-not $proc.WaitForExit($SelfTestTimeoutMs)) {
            try { $proc.Kill() } catch { }
            Stop-Build "the self-test of $Exe did not finish within $($SelfTestTimeoutMs / 1000) s."
        }
        $code = $proc.ExitCode
    } finally {
        $env:AUTOPRESS_HOME = $oldHome
    }
    if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
        Stop-Build "the self-test of $Exe wrote no report (exit code $code)."
    }
    $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($check in $result.checks) {
        $mark = if ($check.ok) { 'ok  ' } elseif ($check.required) { 'FAIL' } else { 'warn' }
        $first = ($check.detail -split "`n")[0]
        Write-Host ('  {0} {1,-11} {2}' -f $mark, $check.name, $first)
    }
    if ($code -ne 0 -or -not $result.ok) {
        Stop-Build "self-test failed (exit code $code); full report: $report"
    }
    Write-Host ('  passed in {0} s (Qt {1}, platform {2})' -f $result.seconds, $result.qt, $result.platform)
}

$clock = [System.Diagnostics.Stopwatch]::StartNew()
Set-Location -LiteralPath $Root

# Reproducible build environment (this PowerShell process only): PyInstaller also resolves DLL
# dependencies through PATH, so a third-party folder on PATH (e.g. Anaconda) could slip its own
# DLLs into the bundle - build with a minimal PATH; PYTHONPATH / PYTHONHOME of another Python
# install would break the .venv interpreter.
$env:PATH = @(
    (Join-Path $Root '.venv\Scripts'),
    (Join-Path $env:SystemRoot 'System32'),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot 'System32\Wbem'),
    (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')
) -join ';'
foreach ($name in @('PYTHONPATH', 'PYTHONHOME', 'QT_QPA_PLATFORM', 'QT_PLUGIN_PATH')) {
    if (Test-Path -LiteralPath "Env:$name") { Remove-Item -LiteralPath "Env:$name" }
}
$env:PYTHONIOENCODING = 'utf-8'

# 1. Python environment -------------------------------------------------------------------
Write-Step 'Checking the Python environment (.venv)'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Stop-Build ("$Python not found. Create it once with Python 3.12.10 (python.org):`n" +
        "    py -3.12 -m venv .venv`n" +
        "    .venv\Scripts\python.exe -m pip install -r requirements.txt")
}
# (no double quotes inside -c code: Windows PowerShell 5.1 does not escape them for native tools)
& $Python -c 'import sys, PyInstaller, PyQt6.QtWidgets, rapidocr; print(''Python'', sys.version.split()[0], ''/ PyInstaller'', PyInstaller.__version__)'
if ($LASTEXITCODE -ne 0) {
    Stop-Build ("PyInstaller, PyQt6 or rapidocr is missing in .venv. Install them with:`n" +
        "    .venv\Scripts\python.exe -m pip install pyinstaller==6.22.3 pyinstaller-hooks-contrib==2026.10")
}
$Version = (& $Python -c 'import autopress; print(autopress.__version__)' | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { Stop-Build 'cannot read autopress.__version__.' }
Write-Host "AutoPress $Version"

# 2. Icon ---------------------------------------------------------------------------------
Write-Step 'Checking the icon'
if (-not (Test-Path -LiteralPath $Icon -PathType Leaf)) {
    Write-Host 'icon.ico missing - rendering it with tools\make_icon.py'
    & $Python (Join-Path $Root 'tools\make_icon.py')
    if ($LASTEXITCODE -ne 0) { Stop-Build 'tools\make_icon.py failed.' }
} else {
    Write-Host 'icon.ico present.'
}

# 3. PyInstaller --------------------------------------------------------------------------
Write-Step 'Removing the previous build output'
Remove-Path $AppDir
Remove-Path $WorkDir
Remove-Path $StageRoot
Get-ChildItem -LiteralPath $DistDir -Filter 'AutoPress-*-win64.zip' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Path $_.FullName }

Write-Step 'Running PyInstaller with autopress.spec (a few minutes)'
& $Python -m PyInstaller --noconfirm --clean --log-level WARN --distpath $DistDir --workpath $WorkDir $Spec
if ($LASTEXITCODE -ne 0) { Stop-Build "PyInstaller exited with code $LASTEXITCODE (see the messages above)." }
if (-not (Test-Path -LiteralPath $AppExe -PathType Leaf)) { Stop-Build "PyInstaller finished but $AppExe is missing." }

# 4. Self-tests ---------------------------------------------------------------------------
$TestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('autopress-build-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
try {
    Write-Step 'Self-test: dist\AutoPress\AutoPress.exe --selftest'
    Invoke-SelfTest $AppExe (Join-Path $TestRoot 'plain')

    # Users' profile folders often have Chinese names (PX-21): run the same build from such a path.
    $CjkDir = Join-Path $TestRoot '中文 路徑\自我測試'
    Write-Step "Self-test from a copy in a folder with Chinese characters: $CjkDir"
    New-Item -ItemType Directory -Force -Path $CjkDir | Out-Null
    Copy-Item -LiteralPath $AppDir -Destination $CjkDir -Recurse
    Invoke-SelfTest (Join-Path $CjkDir 'AutoPress\AutoPress.exe') (Join-Path $CjkDir 'work')
} finally {
    Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
}

# 5. Zip ----------------------------------------------------------------------------------
Write-Step "Packing dist\AutoPress-$Version-win64.zip"
$TopName = "AutoPress-$Version"
$Stage = Join-Path $StageRoot $TopName
New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null
Copy-Item -LiteralPath $AppDir -Destination $Stage -Recurse
foreach ($file in @('README.md', 'LICENSE', 'THIRD-PARTY-NOTICES.md', 'CHANGELOG.md')) {
    $src = Join-Path $Root $file
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { Stop-Build "$file is missing." }
    Copy-Item -LiteralPath $src -Destination $Stage
}
Copy-Item -LiteralPath (Join-Path $Root 'licenses') -Destination $Stage -Recurse
$Guide = Join-Path $Root 'docs\user_guide.md'
if (Test-Path -LiteralPath $Guide -PathType Leaf) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'docs') | Out-Null
    Copy-Item -LiteralPath $Guide -Destination (Join-Path $Stage 'docs')
    $Images = Join-Path $Root 'docs\images'
    if (Test-Path -LiteralPath $Images) {
        # only the annotated images (not docs\images\raw\ or the screenshot manifest)
        $ImagesDst = Join-Path $Stage 'docs\images'
        New-Item -ItemType Directory -Force -Path $ImagesDst | Out-Null
        Get-ChildItem -LiteralPath $Images -Filter '*.png' -File | Copy-Item -Destination $ImagesDst
    }
}
$NotePath = Join-Path $StageRoot $UnzipNoteName
# UTF-8 with BOM, CRLF: readable in every Notepad version
$NoteText = $UnzipNote.Replace('{TopName}', $TopName)
[System.IO.File]::WriteAllText($NotePath, ($NoteText -replace "`r?`n", "`r`n") + "`r`n", (New-Object System.Text.UTF8Encoding($true)))
$Zip = Join-Path $DistDir "AutoPress-$Version-win64.zip"
# Python's zipfile stores forward slashes and UTF-8 names (flag 0x800) for the Chinese file name.
& $Python -m zipfile -c $Zip $Stage $NotePath
if ($LASTEXITCODE -ne 0) { Stop-Build "creating $Zip failed." }
& $Python -c 'import sys, zipfile; n = zipfile.ZipFile(sys.argv[1]).namelist(); top = {x.split(chr(47))[0] for x in n}; print(len(n), ''entries; top level:'', sorted(top)); sys.exit(0 if len(top) == 2 and sys.argv[2] in top else 1)' $Zip $TopName
if ($LASTEXITCODE -ne 0) { Stop-Build "$Zip does not have the expected layout." }
Remove-Path $StageRoot

# 6. Result -------------------------------------------------------------------------------
$clock.Stop()
$appMb = (Get-ChildItem -LiteralPath $AppDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
$zipMb = (Get-Item -LiteralPath $Zip).Length / 1MB
Write-Step ('Done in {0:N0} s: {1} ({2:N1} MB unpacked), {3} ({4:N1} MB)' -f $clock.Elapsed.TotalSeconds, $AppExe, $appMb, $Zip, $zipMb)
exit 0

[CmdletBinding()]
param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$pythonPath = [System.IO.Path]::GetFullPath((Join-Path $root $Python))
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Python build runtime was not found: $pythonPath" }
& $pythonPath -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Install build tools first: $pythonPath -m pip install -r requirements-build.txt" }
$architecture = @(& $pythonPath -c "import platform, struct; print(platform.machine()); print(struct.calcsize('P') * 8)")
if ($LASTEXITCODE -ne 0 -or $architecture.Count -lt 2 -or $architecture[-1].Trim() -ne '64' -or $architecture[0].Trim() -notin @('AMD64', 'x86_64')) {
    throw "The Windows x64 release must be built with 64-bit AMD64 Python. Detected: $($architecture -join ' ')"
}

& $pythonPath scripts\make_icon.py
if ($LASTEXITCODE -ne 0 -or -not (Test-Path static\book-ocr.ico)) { throw 'Icon generation failed.' }

foreach ($relative in @('build', 'dist\Book-OCR')) {
    $target = [System.IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $target.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe build target: $target" }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}

& $pythonPath -m PyInstaller --noconfirm --clean Book-OCR.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$dist = Join-Path $root 'dist\Book-OCR'
$exe = Join-Path $dist 'Book-OCR.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Expected executable was not produced.' }
Copy-Item -LiteralPath 'QUICK_START.txt' -Destination (Join-Path $dist 'QUICK_START.txt') -Force

$forbidden = Get-ChildItem -LiteralPath $dist -Recurse -Force | Where-Object {
    $relative = [System.IO.Path]::GetRelativePath($dist, $_.FullName)
    $segments = $relative -split '[\\/]'
    $rootUserDirectory = $segments.Count -eq 1 -and $_.PSIsContainer -and $_.Name -in @('books', 'data', 'exports', 'backups', 'config', 'diagnostics', 'logs')
    $developmentDirectory = $_.PSIsContainer -and $_.Name -in @('.git', '.venv', 'tests', '__pycache__')
    $sensitiveName = -not $_.PSIsContainer -and (
        $_.Name -eq 'secrets.json' -or $_.Name -match '^\.env(?:\.|$)' -or
        $_.Name -match '(?i)\.(db|sqlite|sqlite3)(-wal|-shm)?$' -or
        $_.Name -match '(?i)\.(pdf|bak|log|bookocr-keys|p12|pfx|key)$' -or
        $_.Name -match '(?i)\.bookocr(?:-collection)?\.zip$' -or
        ($_.Extension -eq '.pem' -and $relative -ne '_internal\certifi\cacert.pem')
    )
    $rootUserDirectory -or $developmentDirectory -or $sensitiveName
}
if ($forbidden) { throw "Distribution contains prohibited user/development data: $($forbidden.FullName -join ', ')" }

& $exe --smoke
if ($LASTEXITCODE -ne 0) { throw 'Packaged runtime smoke check failed.' }

# Verify the frozen folder works after being copied away from this checkout.
$cleanInstall = Join-Path ([System.IO.Path]::GetTempPath()) ("book-ocr-clean-install-" + [guid]::NewGuid())
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not ([System.IO.Path]::GetFullPath($cleanInstall).StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase))) { throw "Unsafe copied-install target: $cleanInstall" }
$copiedServer = $null
$oldCopiedData = $env:BOOK_OCR_DATA_DIR
try {
    Copy-Item -LiteralPath $dist -Destination (Join-Path $cleanInstall 'Book-OCR') -Recurse
    $env:BOOK_OCR_DATA_DIR = Join-Path $cleanInstall 'data'
    $copiedServer = Start-Process -FilePath (Join-Path $cleanInstall 'Book-OCR\Book-OCR.exe') -ArgumentList '--serve', '--port', '8877' -WindowStyle Hidden -PassThru
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 250
        try { $copiedResponse = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8877/' -TimeoutSec 2 } catch { $copiedResponse = $null }
    } until ($copiedResponse -or (Get-Date) -ge $deadline)
    if (-not $copiedResponse -or $copiedResponse.StatusCode -ne 200 -or $copiedResponse.Content -notmatch 'Book-OCR') { throw 'Copied distribution did not become ready.' }
    foreach ($path in @('/settings', '/transfer', '/search?q=fixture', '/static/favicon.svg', '/static/css/style.css')) {
        if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8877$path" -TimeoutSec 5).StatusCode -ne 200) { throw "Copied-distribution route failed: $path" }
    }
    try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8877/collections/missing' -TimeoutSec 5 | Out-Null; throw 'Missing collection route did not return 404.' }
    catch { if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw } }
} finally {
    if ($copiedServer -and -not $copiedServer.HasExited) { Stop-Process -Id $copiedServer.Id -Force; $copiedServer.WaitForExit() }
    $env:BOOK_OCR_DATA_DIR = $oldCopiedData
    Remove-Item -LiteralPath $cleanInstall -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $SkipSmokeTest) {
    $smoke = Join-Path ([System.IO.Path]::GetTempPath()) ("book-ocr-smoke-" + [guid]::NewGuid())
    if (-not ([System.IO.Path]::GetFullPath($smoke).StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase))) { throw "Unsafe smoke-test target: $smoke" }
    $oldData = $env:BOOK_OCR_DATA_DIR
    New-Item -ItemType Directory -Path $smoke | Out-Null
    try {
        $env:BOOK_OCR_DATA_DIR = $smoke
        $server = Start-Process -FilePath $exe -ArgumentList '--serve', '--port', '8876' -WindowStyle Hidden -PassThru
        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 250
            try { $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8876/' -TimeoutSec 2 } catch { $response = $null }
        } until ($response -or (Get-Date) -ge $deadline)
        if (-not $response -or $response.StatusCode -ne 200 -or $response.Content -notmatch 'Book-OCR') { throw 'Packaged server did not become ready.' }
        foreach ($path in @('/static/favicon.svg', '/static/css/style.css', '/settings', '/search?q=fixture')) {
            if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8876$path" -TimeoutSec 5).StatusCode -ne 200) { throw "Smoke route failed: $path" }
        }
    } finally {
        if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force; $server.WaitForExit() }
        $env:BOOK_OCR_DATA_DIR = $oldData
        Remove-Item -LiteralPath $smoke -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Windows distribution built successfully: $dist"

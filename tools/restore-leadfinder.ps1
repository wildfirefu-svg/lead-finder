param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [switch]$RestoreEnv,
    [switch]$RestoreExports
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$targetDbDir = Join-Path $projectRoot "data"
$targetDbPath = Join-Path $targetDbDir "leadfinder.sqlite"
$backupDbPath = Join-Path $BackupPath "leadfinder.sqlite"
$backupEnvPath = Join-Path $BackupPath ".env.backup"
$backupExportsPath = Join-Path $BackupPath "exports"

if (-not (Test-Path -LiteralPath $backupDbPath)) {
    throw "Backup database not found: $backupDbPath"
}

$null = New-Item -ItemType Directory -Path $targetDbDir -Force
Copy-Item -LiteralPath $backupDbPath -Destination $targetDbPath -Force

if ($RestoreExports -and (Test-Path -LiteralPath $backupExportsPath)) {
    $targetExports = Join-Path $projectRoot "exports"
    if (Test-Path -LiteralPath $targetExports) {
        Remove-Item -LiteralPath $targetExports -Recurse -Force
    }
    Copy-Item -LiteralPath $backupExportsPath -Destination $targetExports -Recurse -Force
}

if ($RestoreEnv -and (Test-Path -LiteralPath $backupEnvPath)) {
    Copy-Item -LiteralPath $backupEnvPath -Destination (Join-Path $projectRoot ".env") -Force
}

Write-Output "Restore complete from: $BackupPath"

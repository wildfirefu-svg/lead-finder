param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,
    [switch]$IncludeEnv,
    [switch]$IncludeExports
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$dbPath = Join-Path $projectRoot "data\\leadfinder.sqlite"
$exportsPath = Join-Path $projectRoot "exports"
$envPath = Join-Path $projectRoot ".env"

if (-not (Test-Path -LiteralPath $dbPath)) {
    throw "Database not found: $dbPath"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $DestinationRoot "leadfinder-backup-$timestamp"
$null = New-Item -ItemType Directory -Path $backupRoot -Force

Copy-Item -LiteralPath $dbPath -Destination (Join-Path $backupRoot "leadfinder.sqlite")

if ($IncludeExports -and (Test-Path -LiteralPath $exportsPath)) {
    Copy-Item -LiteralPath $exportsPath -Destination (Join-Path $backupRoot "exports") -Recurse -Force
}

if ($IncludeEnv -and (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $envPath -Destination (Join-Path $backupRoot ".env.backup")
}

$manifest = @{
    created_at = (Get-Date).ToString("s")
    project_root = $projectRoot
    database = "leadfinder.sqlite"
    included_env = [bool]$IncludeEnv
    included_exports = [bool]$IncludeExports
} | ConvertTo-Json -Depth 3

Set-Content -LiteralPath (Join-Path $backupRoot "manifest.json") -Value $manifest -Encoding UTF8

Write-Output "Backup created: $backupRoot"

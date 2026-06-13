param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "start",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8765,
    [int]$WaitSeconds = 12
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot "runtime"
$pidPath = Join-Path $runtimeDir "leadfinder-8765.pid"
$stdoutPath = Join-Path $runtimeDir "leadfinder-8765.out.log"
$stderrPath = Join-Path $runtimeDir "leadfinder-8765.err.log"
$url = "http://${BindHost}:${Port}/"

$null = New-Item -ItemType Directory -Path $runtimeDir -Force

function Get-WorkbenchPid {
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return $null
    }
    $raw = (Get-Content -LiteralPath $pidPath -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $raw) {
        return $null
    }
    $pidValue = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$pidValue)) {
        return $null
    }
    return $pidValue
}

function Get-WorkbenchProcess {
    $pidValue = Get-WorkbenchPid
    if (-not $pidValue) {
        return $null
    }
    return Get-Process -Id $pidValue -ErrorAction SilentlyContinue
}

function Remove-StalePidFile {
    if (Test-Path -LiteralPath $pidPath) {
        Remove-Item -LiteralPath $pidPath -Force
    }
}

function Get-PortOwner {
    $pattern = "^\s*TCP\s+\S+:" + [regex]::Escape("$Port") + "\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $matchLine = netstat -ano -p tcp | Select-String -Pattern $pattern | Select-Object -First 1
    if (-not $matchLine) {
        return $null
    }
    $match = [regex]::Match($matchLine.Line, $pattern)
    if (-not $match.Success) {
        return $null
    }
    return Get-Process -Id ([int]$match.Groups[1].Value) -ErrorAction SilentlyContinue
}

function Test-WorkbenchReady {
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 2
        return [bool]($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Wait-WorkbenchReady {
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-WorkbenchReady) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-Status {
    $managed = Get-WorkbenchProcess
    $owner = Get-PortOwner
    if ($managed) {
        Write-Output "Lead Finder 8765 is running. pid=$($managed.Id) url=$url"
        Write-Output "stdout=$stdoutPath"
        Write-Output "stderr=$stderrPath"
        return
    }
    if ($owner) {
        Remove-StalePidFile
        Write-Output "Port $Port is in use by external process pid=$($owner.Id) name=$($owner.ProcessName)."
        return
    }
    Remove-StalePidFile
    Write-Output "Lead Finder 8765 is stopped."
}

switch ($Action) {
    "status" {
        Show-Status
        exit 0
    }
    "stop" {
        $process = Get-WorkbenchProcess
        if ($process) {
            Stop-Process -Id $process.Id -Force
            Remove-StalePidFile
            Write-Output "Stopped Lead Finder 8765. pid=$($process.Id)"
            exit 0
        }
        Remove-StalePidFile
        Write-Output "Lead Finder 8765 is already stopped."
        exit 0
    }
    "restart" {
        $process = Get-WorkbenchProcess
        if ($process) {
            Stop-Process -Id $process.Id -Force
            Remove-StalePidFile
            Start-Sleep -Milliseconds 500
        }
        $Action = "start"
    }
}

$managed = Get-WorkbenchProcess
if ($managed) {
    Write-Output "Lead Finder 8765 is already running. pid=$($managed.Id) url=$url"
    exit 0
}

$owner = Get-PortOwner
if ($owner) {
    throw "Port $Port is already in use by pid=$($owner.Id) name=$($owner.ProcessName). Stop it first or use status."
}

$python = (Get-Command python -ErrorAction Stop).Source
$process = Start-Process `
    -FilePath $python `
    -ArgumentList @("cli.py", "serve", "--host", $BindHost, "--port", "$Port") `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

if (-not (Wait-WorkbenchReady)) {
    $stderrTail = ""
    if (Test-Path -LiteralPath $stderrPath) {
        $stderrTail = ((Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue | Select-Object -Last 20) -join [Environment]::NewLine).Trim()
    }
    if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
        Stop-Process -Id $process.Id -Force
    }
    Remove-StalePidFile
    if ($stderrTail) {
        throw "Lead Finder 8765 failed health check within ${WaitSeconds}s. stderr:`n$stderrTail"
    }
    throw "Lead Finder 8765 failed health check within ${WaitSeconds}s."
}

$listeningProcess = Get-PortOwner
if ($listeningProcess) {
    Set-Content -LiteralPath $pidPath -Value "$($listeningProcess.Id)" -Encoding ASCII
} else {
    Set-Content -LiteralPath $pidPath -Value "$($process.Id)" -Encoding ASCII
    $listeningProcess = $process
}

Write-Output "Lead Finder 8765 started. pid=$($listeningProcess.Id) url=$url"
Write-Output "stdout=$stdoutPath"
Write-Output "stderr=$stderrPath"

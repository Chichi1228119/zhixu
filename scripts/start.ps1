param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $projectRoot 'data'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$serviceUrl = 'http://127.0.0.1:18765'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

function Get-KnowledgeHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$serviceUrl/api/health" -TimeoutSec 2
        $result = [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray()) | ConvertFrom-Json
        if ($result.app_id -eq 'zhixu-local-knowledge' -and $result.status -eq 'ok' -and $result.data_location -eq $dataDir) { return $result }
    } catch { }
    return $null
}

if (Get-KnowledgeHealth) {
    Write-Host "知序已在运行：$serviceUrl"
    if (-not $NoBrowser) { Start-Process $serviceUrl }
    exit 0
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    & (Join-Path $PSScriptRoot 'setup.ps1')
    if ($LASTEXITCODE -ne 0) { throw '项目环境安装失败，请查看上方提示。' }
}

$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '18765') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataDir 'server.log') -RedirectStandardError (Join-Path $dataDir 'server-error.log') -PassThru
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $verifiedHealth = Get-KnowledgeHealth
    if ($verifiedHealth) {
        $workerProcess = Get-Process -Id ([int]$verifiedHealth.process_id)
        $record = @{ process_id = $workerProcess.Id; start_ticks = $workerProcess.StartTime.ToUniversalTime().Ticks.ToString(); executable = $workerProcess.Path; instance_id = $verifiedHealth.instance_id }
        $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataDir 'server-process.json') -Encoding UTF8
        Set-Content -LiteralPath (Join-Path $dataDir 'server.pid') -Value $workerProcess.Id -Encoding ASCII
        Write-Host "知序启动完成：$serviceUrl"
        Write-Host "资料与数据保存在：$dataDir"
        if (-not $NoBrowser) { Start-Process $serviceUrl }
        exit 0
    }
    if ($serverProcess.HasExited) {
        Get-Content -LiteralPath (Join-Path $dataDir 'server-error.log') -Tail 12
        throw '服务未能启动。请检查 18765 端口或项目 .env 配置。'
    }
    Start-Sleep -Milliseconds 300
}
throw '启动等待超时，请查看 data\server-error.log。不要重复启动多个服务。'

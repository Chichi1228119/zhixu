$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$recordPath = Join-Path $projectRoot 'data\server-process.json'
if (-not (Test-Path -LiteralPath $recordPath)) { Write-Host '没有由启动脚本记录的服务进程。'; exit 0 }
$record = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
$servicePid = [int]$record.process_id
$processInfo = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
if (-not $processInfo) { Write-Host '服务已停止。'; exit 0 }
if ($processInfo.Path -ne $record.executable -or $processInfo.StartTime.ToUniversalTime().Ticks.ToString() -ne $record.start_ticks) {
    throw '进程已变化，未停止任何程序。'
}
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:18765/api/health' -TimeoutSec 2
    if ($health.app_id -ne 'zhixu-local-knowledge' -or $health.instance_id -ne $record.instance_id -or $health.process_id -ne $servicePid) { throw '服务实例身份不匹配。' }
} catch {
    throw '服务身份无法验证，未停止任何程序。请检查服务状态。'
}
Stop-Process -Id $servicePid -ErrorAction Stop
Write-Host '知序服务已停止，资料保留在 data 文件夹。'

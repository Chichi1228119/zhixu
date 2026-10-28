$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) {
        & $bundledPython -m venv (Join-Path $projectRoot '.venv')
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv (Join-Path $projectRoot '.venv')
    } else {
        throw '请先安装 64 位 Python 3.12，然后按 README 创建项目环境。'
    }
    if ($LASTEXITCODE -ne 0) { throw '无法创建 Python 项目环境。' }
}
$wheelDir = Join-Path $projectRoot 'vendor\wheels'
if (Test-Path -LiteralPath $wheelDir) {
    & $pythonPath -m pip install --disable-pip-version-check --no-index --find-links $wheelDir -r (Join-Path $projectRoot 'requirements-lock.txt')
} else {
    & $pythonPath -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements.txt')
}
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络后重试；不会修改系统 Python。' }
Write-Host '项目依赖安装完成，仅安装在本项目 .venv。'

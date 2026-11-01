param([ValidateRange(1, 65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $projectPython)) {
    throw '找不到 venv，請依 README 建立 Python 環境。'
}
Write-Host "SCU Data Science Course Assistant: http://127.0.0.1:$Port/"
& $projectPython -m uvicorn scu_assistant.api:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE

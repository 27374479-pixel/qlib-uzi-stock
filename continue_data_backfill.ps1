param(
    [Parameter(Mandatory = $true)]
    [int]$DailyProcessId
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

Wait-Process -Id $DailyProcessId -ErrorAction SilentlyContinue
Set-Location $projectRoot
& $pythonPath "collect_industry_snapshots.py" "--start" "2015-01-05" "--end" "2026-05-29"
exit $LASTEXITCODE

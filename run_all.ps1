$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw ".venv tidak ditemukan di $root" }
if (-not (Test-NetConnection -ComputerName localhost -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
  throw "PostgreSQL tidak menjawab di port 5432. Nyalakan lewat Laragon."
}
& $py -m scripts.checks_role
if ($LASTEXITCODE -ne 0) { throw "Pemeriksaan role gagal. Sistem tidak dijalankan." }
$procs = @(
  @{ n = "poller";    a = "-m scripts.poll" },
  @{ n = "outbox";    a = "-m scripts.outbox_worker" },
  @{ n = "api";       a = "-m uvicorn app.api.main:app --host 127.0.0.1 --port 8000" },
  @{ n = "scheduler"; a = "-m scripts.scheduler" },
  @{ n = "dashboard"; a = "-m streamlit run dashboard/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false" }
)
foreach ($p in $procs) {
  $cmd = "`$Host.UI.RawUI.WindowTitle = 'enerva-$($p.n)'; Set-Location '$root'; & '$py' $($p.a)"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
}
Write-Host "Berjalan: poller, outbox, api, scheduler, dashboard. Dashboard: http://127.0.0.1:8501"

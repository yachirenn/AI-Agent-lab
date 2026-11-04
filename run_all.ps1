$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw ".venv tidak ditemukan di $root" }

# Pastikan environment UTF-8 aktif di Windows untuk mencegah UnicodeEncodeError
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# Verifikasi koneksi database (mendukung Supabase / remote maupun Postgres lokal)
Write-Host "Memeriksa koneksi database..." -ForegroundColor Cyan
& $py -c "from app.db import repo; repo.get_pool()"
if ($LASTEXITCODE -ne 0) {
    throw "Koneksi database gagal. Pastikan DATABASE_URL di .env sudah benar."
}
Write-Host "Database terhubung! [OK]" -ForegroundColor Green

$procs = @(
  @{ n = "poller";    a = "-m scripts.poll" },
  @{ n = "inbox";     a = "-m scripts.inbox_worker" },
  @{ n = "outbox";    a = "-m scripts.outbox_worker" },
  @{ n = "api";       a = "-m uvicorn app.api.main:app --host 127.0.0.1 --port 8000" },
  @{ n = "scheduler"; a = "-m scripts.scheduler" },
  @{ n = "dashboard"; a = "-m streamlit run dashboard/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false" }
)
foreach ($p in $procs) {
  $cmd = "[Console]::Title = 'enerva-$($p.n)'; `$env:PYTHONUTF8 = '1'; Set-Location '$root'; & '$py' $($p.a)"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
}
Write-Host "Berjalan: poller, inbox, outbox, api, scheduler, dashboard." -ForegroundColor Green
Write-Host "API Docs:  http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "Dashboard: http://127.0.0.1:8501" -ForegroundColor Cyan

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw ".venv tidak ditemukan di $root" }

# Pastikan environment UTF-8 aktif di Windows untuk mencegah UnicodeEncodeError
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# GOWA bukan Python process, jadi muat variabel yang dibutuhkan dari .env ke
# environment process ini tanpa pernah mencetak nilainya.
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line -match '^([^=]+)=(.*)$') {
      $name = $matches[1].Trim()
      $value = $matches[2].Trim()
      if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
          ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
      }
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

# Verifikasi koneksi database (mendukung Supabase / remote maupun Postgres lokal)
Write-Host "Memeriksa koneksi database..." -ForegroundColor Cyan
& $py -c "from app.db import repo; repo.get_pool()"
if ($LASTEXITCODE -ne 0) {
    throw "Koneksi database gagal. Pastikan DATABASE_URL di .env sudah benar."
}
Write-Host "Database terhubung! [OK]" -ForegroundColor Green

# Pastikan schema dasar dan seluruh migration tersedia sebelum worker dimulai.
Write-Host "Memeriksa dan menerapkan migrasi database..." -ForegroundColor Cyan
& $py -m scripts.migrate
if ($LASTEXITCODE -ne 0) {
    throw "Migrasi database gagal. Worker tidak dijalankan."
}
Write-Host "Migrasi database selesai! [OK]" -ForegroundColor Green

$procs = @(
  @{ n = "poller";    c = "& '$py' -m scripts.poll" },
  @{ n = "inbox";     c = "& '$py' -m scripts.inbox_worker" },
  @{ n = "outbox";    c = "& '$py' -m scripts.outbox_worker" },
  @{ n = "api";       c = "& '$py' -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000" },
  @{ n = "scheduler"; c = "& '$py' -m scripts.scheduler" },
  @{ n = "dashboard"; c = "& '$py' -m streamlit run dashboard/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false" }
)

$gowa = Join-Path $root "tools\gowa\whatsapp.exe"
if (Test-Path $gowa) {
  if (-not $env:WHATSAPP_WEBHOOK_SECRET) {
    throw "WHATSAPP_WEBHOOK_SECRET wajib diisi untuk mengamankan webhook GOWA."
  }
  $procs += @{
    n = "whatsapp"
    c = "& '$gowa' rest --host 127.0.0.1 --port 3000 --webhook 'http://127.0.0.1:8000/webhook/whatsapp/gowa' --webhook-secret '$env:WHATSAPP_WEBHOOK_SECRET' --webhook-events 'message'"
  }
}

foreach ($p in $procs) {
  $cmd = "[Console]::Title = 'enerva-$($p.n)'; `$env:PYTHONUTF8 = '1'; Set-Location '$root'; $($p.c)"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd
}

Write-Host "Berjalan: $($procs.n -join ', ')." -ForegroundColor Green
Write-Host "API Docs:     http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "Dashboard:    http://127.0.0.1:8501" -ForegroundColor Cyan
if (Test-Path $gowa) {
  Write-Host "WhatsApp Web: http://127.0.0.1:3000 (Scan QR code di sini)" -ForegroundColor Yellow
}

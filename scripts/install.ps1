<#
.SYNOPSIS
    Uzak Masaüstü Ajanı'nı OFİS bilgisayarına kurar.

.DESCRIPTION
    - Python yoksa winget ile kurar
    - Ajanı "C:\Program Files\RemoteAgent" altına kopyalar, sanal ortam oluşturur
    - Giriş parolasını sorar
    - Windows oturumu açıldığında ajanı otomatik başlatan bir Zamanlanmış Görev oluşturur
    - Güvenlik duvarında portu YALNIZCA Tailscale ağına (100.64.0.0/10) açar
    - Bilgisayarın prizdeyken uykuya geçmesini kapatır
    - İsteğe bağlı: Windows Uzak Masaüstü'nü (RDP) açar (yalnızca Pro/Enterprise)

.EXAMPLE
    # Yönetici olarak açılmış PowerShell'de, proje klasöründe:
    powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Port 8765 -AllowLan -EnableRdp
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$Name = $env:COMPUTERNAME,
    [string]$InstallDir = "$env:ProgramFiles\RemoteAgent",
    [string]$ConfigDir = "$env:ProgramData\RemoteAgent",
    # Tailscale dışında aynı yerel ağdan (ofis içi) erişime de izin ver
    [switch]$AllowLan,
    # Windows Uzak Masaüstü'nü de aç (kilit ekranında da çalışır; Home sürümünde yoktur)
    [switch]$EnableRdp,
    # Güç ayarlarına dokunma
    [switch]$KeepPowerSettings
)

$ErrorActionPreference = "Stop"
$TaskName = "RemoteAgent"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- 0. Yönetici kontrolü ---------------------------------------------------------
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Bu betiği 'Yönetici olarak çalıştır' ile açılmış PowerShell'de çalıştırın."
}
$UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name

# --- 1. Python ---------------------------------------------------------------------
Step "Python denetleniyor"
function Find-Python {
    foreach ($cmd in @("py", "python")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $pyArgs = if ($cmd -eq "py") { @("-3", "-c") } else { @("-c") }
        try {
            $path = & $exe.Source @pyArgs "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $path -and (Test-Path $path)) { return $path.Trim() }
        } catch { }
    }
    return $null
}
$Python = Find-Python
if (-not $Python) {
    Write-Host "Python 3.10+ bulunamadı, winget ile Python 3.12 kuruluyor..."
    winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $Python = Find-Python
    if (-not $Python) { Write-Error "Python kurulamadı. https://www.python.org adresinden elle kurup tekrar deneyin." }
}
Write-Host "Python: $Python"

# --- 2. Dosyalar ve sanal ortam -------------------------------------------------------
Step "Dosyalar kopyalanıyor: $InstallDir"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Remove-Item -Recurse -Force (Join-Path $InstallDir "remote_agent") -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force (Join-Path $RepoRoot "remote_agent") $InstallDir
Copy-Item -Force (Join-Path $RepoRoot "requirements.txt") $InstallDir
Get-ChildItem -Recurse -Directory -Filter "__pycache__" $InstallDir | Remove-Item -Recurse -Force

$Venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    & $Python -m venv $Venv
}
$VPy = Join-Path $Venv "Scripts\python.exe"
$VPyw = Join-Path $Venv "Scripts\pythonw.exe"
& $VPy -m pip install --upgrade pip --quiet
& $VPy -m pip install -r (Join-Path $InstallDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { Write-Error "Paketler kurulamadı." }

# --- 3. Yapılandırma ve parola ---------------------------------------------------------
Step "Yapılandırma: $ConfigDir"
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
# Klasöre yalnızca SYSTEM, Yöneticiler ve bu kullanıcı erişebilsin
icacls $ConfigDir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${UserId}:(OI)(CI)M" | Out-Null

Push-Location $InstallDir
try {
    & $VPy -m remote_agent --config-dir $ConfigDir --port $Port --name $Name --set-password
    if ($LASTEXITCODE -ne 0) { Write-Error "Parola belirlenemedi." }
} finally { Pop-Location }

# --- 4. Güvenlik duvarı ----------------------------------------------------------------
Step "Güvenlik duvarı kuralı"
Get-NetFirewallRule -DisplayName "RemoteAgent*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
$remote = @("100.64.0.0/10")
if ($AllowLan) { $remote += "LocalSubnet" }
New-NetFirewallRule -DisplayName "RemoteAgent (TCP $Port)" -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $Port -RemoteAddress $remote -Profile Any | Out-Null
Write-Host "Port $Port şu adreslere açık: $($remote -join ', ')"

# --- 5. Otomatik başlatma (Zamanlanmış Görev) ----------------------------------------
Step "Oturum açılışında otomatik başlatma"
$action = New-ScheduledTaskAction -Execute $VPyw `
    -Argument "-m remote_agent --config-dir `"$ConfigDir`"" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
# "Highest": yönetici olarak açılmış pencerelere de tıklayabilmek için
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $taskPrincipal -Description "Uzak Masaüstü Ajanı" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

# --- 5b. Bekçi: her 5 dakikada Tailscale'i ve ajanı denetler, bozulanı onarır ------------
Step "Bekçi görevi (5 dakikada bir denetim)"
$wdAction = New-ScheduledTaskAction -Execute $VPyw `
    -Argument "-m remote_agent.watchdog --config-dir `"$ConfigDir`"" -WorkingDirectory $InstallDir
$wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$wdSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "${TaskName}Watchdog" -Action $wdAction -Trigger $wdTrigger `
    -Settings $wdSettings -Principal $taskPrincipal -Description "Uzak Masaüstü Ajanı bekçisi" -Force | Out-Null

# --- 6. Güç ayarları ----------------------------------------------------------------------
if (-not $KeepPowerSettings) {
    Step "Prizdeyken uyku/hazırda bekletme kapatılıyor"
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    # "Güç tasarrufu için bilgisayarın bu aygıtı kapatmasına izin ver" kapatılır;
    # aksi halde ağ kartı uyuyup dışarıdan erişim kesilebilir
    Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            Set-NetAdapterPowerManagement -Name $_.Name -AllowComputerToTurnOffDevice Disabled -ErrorAction Stop
            Write-Host "Ağ kartı güç tasarrufu kapatıldı: $($_.Name)"
        } catch { }
    }
}

# --- 7. İsteğe bağlı: Windows Uzak Masaüstü (RDP) ----------------------------------------
if ($EnableRdp) {
    Step "Windows Uzak Masaüstü (RDP) açılıyor"
    $edition = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").EditionID
    if ($edition -match "Core|Home") {
        Write-Warning "Bu bilgisayar Windows $edition sürümü; RDP sunucusu yok. Yalnızca ajan kullanılabilir."
    } else {
        Set-ItemProperty "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 0
        # Ağ Düzeyinde Kimlik Doğrulama (NLA) zorunlu
        Set-ItemProperty "HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" -Name UserAuthentication -Value 1
        Get-NetFirewallRule -DisplayName "RemoteAgent RDP*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName "RemoteAgent RDP (Tailscale)" -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort 3389 -RemoteAddress $remote -Profile Any | Out-Null
        Write-Host "RDP açık (yalnızca $($remote -join ', ') adreslerinden)."
    }
}

# --- Özet --------------------------------------------------------------------------------
Start-Sleep -Seconds 2
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts -and (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) { $ts = Get-Item "$env:ProgramFiles\Tailscale\tailscale.exe" }
$tsIp = $null
if ($ts) { try { $tsIp = (& $ts.Source ip -4 2>$null | Select-Object -First 1) } catch { } }

Write-Host "`nKurulum tamamlandı." -ForegroundColor Green
Write-Host "Bu bilgisayarda deneyin : http://localhost:$Port"
if ($tsIp) {
    Write-Host "Surface'ten bağlanın     : http://${tsIp}:$Port   veya   http://$($env:COMPUTERNAME.ToLower()):$Port"
} else {
    Write-Warning "Tailscale bulunamadı. Dışarıdan erişim için https://tailscale.com/download adresinden kurup aynı hesapla giriş yapın."
}
Write-Host "Günlük dosyaları        : $ConfigDir\agent.log, $ConfigDir\watchdog.log"

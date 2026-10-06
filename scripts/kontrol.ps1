<#
.SYNOPSIS
    Uzak masaüstü için yapılan tüm ayarları denetler. Yalnızca okur, hiçbir şeyi değiştirmez.

.DESCRIPTION
    Windows güncellemesi, güvenlik sıkılaştırması ya da başka bir program ayarları
    değiştirdiyse bunu bulmak için. Her madde için [ OK ], [DİKKAT] veya [SORUN] yazar.
    Denetlenenler: ajan ve bekçi görevleri, Tailscale, güvenlik duvarı, güç ve kilit
    ayarları, otomatik oturum açma, UAC, "sormadan" açılan programlar ve klasör
    izinleri, Netcad, Windows Güvenliği (Defender).

.EXAMPLE
    # Yönetici PowerShell'de:
    cd C:\uzak-masaustu
    powershell -ExecutionPolicy Bypass -File .\scripts\kontrol.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$InstallDir = "$env:ProgramFiles\RemoteAgent",
    [string]$ConfigDir = "$env:ProgramData\RemoteAgent"
)
$ErrorActionPreference = "SilentlyContinue"

$script:counts = @{ OK = 0; DIKKAT = 0; SORUN = 0 }

function Report([string]$Level, [string]$Title, [string]$Detail = "") {
    $color = @{ OK = "Green"; DIKKAT = "Yellow"; SORUN = "Red"; BILGI = "Gray" }[$Level]
    $tag = @{ OK = "[ OK ]  "; DIKKAT = "[DİKKAT]"; SORUN = "[SORUN] "; BILGI = "[BİLGİ] " }[$Level]
    Write-Host "$tag $Title" -ForegroundColor $color
    if ($Detail) { Write-Host "          $Detail" }
    if ($script:counts.ContainsKey($Level)) { $script:counts[$Level]++ }
}

function Section([string]$Title) { Write-Host "`n== $Title ==" -ForegroundColor Cyan }

function ConvertFrom-PowerCfg([string[]]$Lines) {
    # Çıktı Windows diline göre değişir ("Current AC Power Setting Index" /
    # "Geçerli AC Güç Ayarı Dizini"); ortak olan "AC" kelimesi ve 0x değeri
    foreach ($line in $Lines) {
        if ($line -match '\bAC\b.*:\s*0x([0-9a-fA-F]+)') { return [Convert]::ToInt64($Matches[1], 16) }
    }
    return $null
}

function Get-PowerAC([string]$Sub, [string]$Setting) {
    return ConvertFrom-PowerCfg (powercfg /q SCHEME_CURRENT $Sub $Setting 2>$null)
}

function Get-RegValue([string]$Path, [string]$Name) {
    $item = Get-ItemProperty -LiteralPath $Path -Name $Name
    if ($item) { return $item.$Name }
    return $null
}

# Yönetici olmayan bir programın yazabilmesi "sormadan" açılan programlar için risktir
$me = [Security.Principal.WindowsIdentity]::GetCurrent()
$riskySids = @("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-4", $me.User.Value)
# WriteData, AppendData, DeleteSubdirectoriesAndFiles, Delete, WriteDAC, WriteOwner, GENERIC_ALL, GENERIC_WRITE
$writeMask = 0x2 -bor 0x4 -bor 0x40 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000 -bor 0x40000000

function Get-WritableBy([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl) { return @() }
    $who = @()
    foreach ($ace in $acl.Access) {
        if ($ace.AccessControlType -ne "Allow") { continue }
        if ($ace.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        try { $sid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } catch { continue }
        if ($riskySids -notcontains $sid) { continue }
        if (([int64]$ace.FileSystemRights -band $writeMask) -ne 0) { $who += $ace.IdentityReference.Value }
    }
    try {
        $ownerSid = (New-Object Security.Principal.NTAccount($acl.Owner)).Translate([Security.Principal.SecurityIdentifier]).Value
        if ($riskySids -contains $ownerSid) { $who += "$($acl.Owner) (sahibi)" }
    } catch { }
    return @($who | Select-Object -Unique)
}

function Test-Protected([string]$Exe, [string]$Label) {
    $problems = @()
    foreach ($p in @($Exe, (Split-Path $Exe))) {
        $w = Get-WritableBy $p
        if ($w.Count) { $problems += "$p -> $($w -join ', ')" }
    }
    if ($problems.Count) {
        Report SORUN "$Label`: yönetici olmayan programlar dosyayı değiştirebilir" ($problems -join " | ")
    } else {
        Report OK "$Label`: klasör korumalı"
    }
}

$isAdmin = (New-Object Security.Principal.WindowsPrincipal($me)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "Uzak masaüstü ayar denetimi  ($(Get-Date -Format 'dd.MM.yyyy HH:mm'), $env:COMPUTERNAME)" -ForegroundColor Cyan
if (-not $isAdmin) {
    Report DIKKAT "PowerShell yönetici olarak açılmamış" "Bazı denetimler eksik kalır. 'Yönetici olarak çalıştır' ile açıp tekrar deneyin."
}

# ---------------------------------------------------------------------------------------
Section "Uzak masaüstü programı"

$task = Get-ScheduledTask -TaskName "RemoteAgent"
if (-not $task) {
    Report SORUN "Otomatik başlatma görevi (RemoteAgent) yok" "install.ps1'i yeniden çalıştırın."
} else {
    if ($task.State -eq "Running") { Report OK "Program çalışıyor" }
    else { Report SORUN "Program çalışmıyor (görev durumu: $($task.State))" "Başlatmak için: Start-ScheduledTask RemoteAgent" }
    if ($task.Principal.RunLevel -ne "Highest") {
        Report DIKKAT "Program en yüksek ayrıcalıkla çalışmıyor" "Yönetici olarak açılmış pencerelere tıklanamaz. install.ps1'i yeniden çalıştırın."
    }
    $logonTrigger = $task.Triggers | Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskLogonTrigger" }
    if (-not $logonTrigger) { Report DIKKAT "Görev oturum açılışında başlamıyor" "install.ps1'i yeniden çalıştırın." }
}

$cfg = $null
try { $cfg = Get-Content -LiteralPath (Join-Path $ConfigDir "config.json") -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
if (-not $cfg) { Report SORUN "Ayar dosyası okunamadı" (Join-Path $ConfigDir "config.json") }
elseif (-not $cfg.password_hash) { Report SORUN "Parola belirlenmemiş" "install.ps1'i yeniden çalıştırın." }
if ($cfg -and $cfg.port) { $Port = [int]$cfg.port }

if ($cfg -and $cfg.tls) {
    Report BILGI "HTTPS açık; yerel yanıt denetimi atlandı"
} else {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/session" -TimeoutSec 8
        if ($r.StatusCode -eq 200) { Report OK "Program yanıt veriyor (port $Port)" }
        else { Report SORUN "Program beklenmedik yanıt verdi: $($r.StatusCode)" }
    } catch {
        Report SORUN "Program yanıt vermiyor (http://127.0.0.1:$Port)" "Günlük: $ConfigDir\agent.log"
    }
}

$wd = Get-ScheduledTask -TaskName "RemoteAgentWatchdog"
if (-not $wd) {
    Report SORUN "Bekçi görevi (RemoteAgentWatchdog) yok" "install.ps1'i yeniden çalıştırın."
} else {
    $last = Get-Content -LiteralPath (Join-Path $ConfigDir "watchdog.log") -Tail 1 -Encoding UTF8
    $when = $null
    if ($last -and $last.Length -ge 19) {
        try { $when = [datetime]::ParseExact($last.Substring(0, 19), "yyyy-MM-dd HH:mm:ss", $null) } catch { }
    }
    if (-not $when) { Report DIKKAT "Bekçi henüz kayıt yazmamış" "Kurulumdan 5 dakika sonra tekrar bakın." }
    elseif (((Get-Date) - $when).TotalMinutes -gt 15) {
        Report DIKKAT "Bekçi son 15 dakikada çalışmamış (son: $($when.ToString('dd.MM HH:mm')))" "Görev Zamanlayıcı'da RemoteAgentWatchdog görevine bakın."
    } elseif ($last -match "UYARI|ONARILDI") { Report DIKKAT "Bekçinin son kaydı" ($last -replace '^\S+ \S+ \S+ ', '') }
    else { Report OK "Bekçi düzenli çalışıyor (son: $($when.ToString('HH:mm')))" }
}

$pyw = Join-Path $InstallDir ".venv\Scripts\pythonw.exe"
if (Test-Path -LiteralPath $pyw) { Test-Protected $pyw "Program klasörü ($InstallDir)" }
else { Report SORUN "Program dosyaları bulunamadı" $InstallDir }

# Sanal ortam, kurulu Python'u kullanır; program yönetici olarak çalıştığı için o Python
# da korumalı bir klasörde olmalı (kullanıcı klasörüne kurulmuş Python değiştirilebilir)
$venvCfg = Get-Content -LiteralPath (Join-Path $InstallDir ".venv\pyvenv.cfg") -Encoding UTF8
$pyHome = ($venvCfg | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1) -replace '^\s*home\s*=\s*', ''
if ($pyHome -and (Test-Path -LiteralPath (Join-Path $pyHome "python.exe"))) {
    $w = @(Get-WritableBy $pyHome) + @(Get-WritableBy (Join-Path $pyHome "python.exe")) + @(Get-WritableBy (Join-Path $pyHome "Lib"))
    if ($w.Count) {
        Report SORUN "Programın kullandığı Python kullanıcı klasöründe ($pyHome)" "Yönetici olmayan programlar değiştirip yönetici yetkisi alabilir. Çözüm: Python'u 'tüm kullanıcılar için' kurup install.ps1'i yeniden çalıştırmak."
    } else {
        Report OK "Programın kullandığı Python korumalı klasörde ($pyHome)"
    }
}

# ---------------------------------------------------------------------------------------
Section "Tailscale"

$svc = Get-Service -Name "Tailscale"
if (-not $svc) { Report SORUN "Tailscale kurulu değil" "https://tailscale.com/download/windows" }
elseif ($svc.Status -ne "Running") { Report SORUN "Tailscale hizmeti çalışmıyor" "Start-Service Tailscale" }
else { Report OK "Tailscale hizmeti çalışıyor" }

$tsExe = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
if (-not (Test-Path -LiteralPath $tsExe)) { $tsExe = "tailscale" }
$st = $null
try { $st = (& $tsExe status --json 2>$null | Out-String) | ConvertFrom-Json } catch { }
if (-not $st) {
    Report DIKKAT "Tailscale durumu okunamadı"
} else {
    if ($st.BackendState -eq "Running") {
        $ip = @($st.Self.TailscaleIPs | Where-Object { $_ -match '^\d+\.' })[0]
        Report OK "Tailscale bağlı ($ip)" "Surface'ten: http://$($ip):$Port"
    } elseif ($st.BackendState -eq "NeedsLogin") {
        Report SORUN "Tailscale yeniden giriş istiyor" "Saatin yanındaki Tailscale simgesinden giriş yapın."
    } else {
        Report SORUN "Tailscale bağlı değil (durum: $($st.BackendState))"
    }
    $exp = $st.Self.KeyExpiry
    if ($exp -and -not ($exp -like "0001-*")) {
        Report DIKKAT "Tailscale anahtarının süresi dolacak: $exp" "login.tailscale.com/admin/machines -> bu bilgisayar -> ⋯ -> Disable key expiry"
    } elseif ($st.BackendState -eq "Running") {
        Report OK "Tailscale anahtarı süresiz"
    }
}
$prefs = $null
try { $prefs = (& $tsExe debug prefs 2>$null | Out-String) | ConvertFrom-Json } catch { }
if ($prefs -and ($prefs.PSObject.Properties.Name -contains "ForceDaemon")) {
    if ($prefs.ForceDaemon) { Report OK "Tailscale 'Run unattended' açık" }
    else { Report DIKKAT "Tailscale 'Run unattended' kapalı" "Tailscale simgesi -> Preferences -> Run unattended" }
}

# ---------------------------------------------------------------------------------------
Section "Güvenlik duvarı"

foreach ($prof in Get-NetFirewallProfile -PolicyStore ActiveStore) {
    if ($prof.Enabled -and "$($prof.AllowInboundRules)" -eq "False") {
        Report SORUN "'$($prof.Name)' profilinde 'Gelen tüm bağlantıları engelle' açık" "İzin kuralları yok sayılıyor; Surface bağlanamaz. Windows Güvenliği -> Güvenlik duvarı -> ilgili ağ -> bu kutuyu kaldırın."
    }
}

$rule = Get-NetFirewallRule -DisplayName "RemoteAgent (TCP $Port)"
if (-not $rule) {
    Report SORUN "Güvenlik duvarı kuralı yok" "install.ps1'i yeniden çalıştırın."
} else {
    $addr = ($rule | Get-NetFirewallAddressFilter).RemoteAddress -join ", "
    $ports = ($rule | Get-NetFirewallPortFilter).LocalPort -join ", "
    if ("$($rule.Enabled)" -ne "True" -or "$($rule.Action)" -ne "Allow") {
        Report SORUN "Güvenlik duvarı kuralı kapalı veya engelliyor" "install.ps1'i yeniden çalıştırın."
    } elseif ($ports -ne "$Port") {
        Report SORUN "Güvenlik duvarı kuralı yanlış porta açık ($ports)"
    } elseif ($addr -match "Any|^\*$") {
        Report DIKKAT "Port $Port tüm ağlara açık" "Yalnızca Tailscale (100.64.0.0/10) olmalı. install.ps1'i yeniden çalıştırın."
    } else {
        Report OK "Port $Port yalnızca şu adreslere açık: $addr"
    }
}

$blocks = @(Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True)
$pyBlocks = @($blocks | Get-NetFirewallApplicationFilter | Where-Object { $_.Program -match 'python|RemoteAgent' })
$portBlocks = @($blocks | Get-NetFirewallPortFilter | Where-Object { @($_.LocalPort) -contains "$Port" })
if ($pyBlocks.Count -or $portBlocks.Count) {
    $names = @($pyBlocks + $portBlocks | ForEach-Object { ($_ | Get-NetFirewallRule).DisplayName }) | Select-Object -Unique
    Report SORUN "Programı engelleyen güvenlik duvarı kuralı var (engelleme izinden önce gelir)" ("Kurallar: " + ($names -join "; ") + ". Windows Defender Güvenlik Duvarı -> Gelişmiş ayarlar -> Gelen kuralları'ndan silin veya devre dışı bırakın.")
} else {
    Report OK "Programı engelleyen güvenlik duvarı kuralı yok"
}

# ---------------------------------------------------------------------------------------
Section "Güç ve kilit ayarları"

$standby = Get-PowerAC "SUB_SLEEP" "STANDBYIDLE"
if ($standby -eq 0) { Report OK "Prizdeyken uyku kapalı" }
elseif ($null -ne $standby) { Report SORUN "Prizdeyken $([int]($standby / 60)) dakika sonra uyuyor" "powercfg /change standby-timeout-ac 0" }

$hib = Get-PowerAC "SUB_SLEEP" "HIBERNATEIDLE"
if ($hib -eq 0) { Report OK "Prizdeyken hazırda bekletme kapalı" }
elseif ($null -ne $hib) { Report SORUN "Prizdeyken $([int]($hib / 60)) dakika sonra hazırda bekletiyor" "powercfg /change hibernate-timeout-ac 0" }

$lid = Get-PowerAC "SUB_BUTTONS" "LIDACTION"
if ($lid -eq 0) { Report OK "Prizdeyken kapak kapanınca bir şey yapmıyor" }
elseif ($null -ne $lid) { Report SORUN "Prizdeyken kapak kapanınca uyuyor/kapanıyor" "powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0; powercfg /setactive SCHEME_CURRENT" }

$wake = Get-PowerAC "SUB_NONE" "CONSOLELOCK"
if ($wake -eq 0) { Report OK "Ekran uyanınca parola sormuyor" }
elseif ($null -ne $wake) { Report SORUN "Ekran uyanınca parola soruyor (bilgisayar kilitlenir)" "powercfg /setacvalueindex SCHEME_CURRENT SUB_NONE CONSOLELOCK 0; powercfg /setactive SCHEME_CURRENT" }

$sysPol = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
$inactivity = Get-RegValue $sysPol "InactivityTimeoutSecs"
if ($inactivity -gt 0) {
    Report SORUN "$inactivity saniye işlem yapılmazsa bilgisayar kendini kilitliyor ('Makine etkinlik dışı sınırı')" "Güvenlik sıkılaştırmasıyla eklenmiş olabilir. Kaldırmak için (yönetici): Remove-ItemProperty '$sysPol' -Name InactivityTimeoutSecs"
} else {
    Report OK "İşlem yapılmayınca otomatik kilitlenme yok"
}

$goodbye = Get-RegValue "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" "EnableGoodbye"
if ($goodbye -eq 1) { Report SORUN "Dinamik kilit açık (telefon uzaklaşınca kilitlenir)" "Ayarlar -> Hesaplar -> Oturum açma seçenekleri -> Dinamik kilit" }
else { Report OK "Dinamik kilit kapalı" }

$ssLocked = $false
foreach ($path in "HKCU:\Software\Policies\Microsoft\Windows\Control Panel\Desktop", "HKCU:\Control Panel\Desktop") {
    if ((Get-RegValue $path "ScreenSaveActive") -eq "1" -and (Get-RegValue $path "ScreenSaverIsSecure") -eq "1") { $ssLocked = $true }
}
if ($ssLocked) { Report SORUN "Ekran koruyucu açılınca bilgisayar kilitleniyor" "Ayarlar -> Kişiselleştirme -> Kilit ekranı -> Ekran koruyucu -> 'Sürdürüldüğünde oturum açma ekranını görüntüle' kutusunu kaldırın." }
else { Report OK "Ekran koruyucu kilitlemiyor" }

$wl = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
if ((Get-RegValue $wl "AutoAdminLogon") -eq "1") {
    Report OK "Otomatik oturum açma açık ($(Get-RegValue $wl 'DefaultUserName'))"
    $count = Get-RegValue $wl "AutoLogonCount"
    if ($null -ne $count) { Report DIKKAT "Otomatik oturum açma yalnızca $count kez daha çalışacak" "Autologon64.exe ile yeniden Enable yapın." }
} else {
    Report SORUN "Otomatik oturum açma kapalı" "Yeniden başlatmadan sonra program çalışmaz. Autologon64.exe -> Enable (KURULUM-NOTLARI.md, adım 5)."
}
if ((Get-RegValue "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device" "DevicePasswordLessBuildVersion") -eq 2) {
    Report DIKKAT "'Yalnızca Windows Hello ile oturum aç' açık" "Otomatik oturum açmayı engelleyebilir."
}

# ---------------------------------------------------------------------------------------
Section "Kullanıcı Hesabı Denetimi (UAC)"

$lua = Get-RegValue $sysPol "EnableLUA"
$consent = Get-RegValue $sysPol "ConsentPromptBehaviorAdmin"
if ($lua -eq 0) {
    Report DIKKAT "UAC tamamen kapalı" "Her program sormadan yönetici yetkisi alır. Güvenlik açısından önerilmez."
} elseif ($consent -eq 0) {
    Report DIKKAT "UAC 'Asla bildirme' konumunda" "Her program sormadan yönetici yetkisi alır."
} else {
    $desc = "varsayılan"
    if ($null -ne $consent -and $consent -ne 5) {
        $desc = @{ 1 = "parola sorar"; 2 = "her zaman güvenli masaüstünde sorar"; 3 = "parola sorar"; 4 = "sorar" }[[int]$consent]
    }
    Report OK "UAC açık ($desc)" "Yönetici izni isteyen programlar uzaktayken 'sormadan' kısayoluyla açılmalı."
}

# ---------------------------------------------------------------------------------------
Section "Sormadan açılan programlar"

$noPrompt = @(Get-ScheduledTask -TaskName "Sormadan - *")
if (-not $noPrompt.Count) { Report BILGI "Sormadan açılan program kısayolu yok" }
foreach ($t in $noPrompt) {
    $exe = $t.Actions[0].Execute
    $label = $t.TaskName.Substring("Sormadan - ".Length)
    if (-not (Test-Path -LiteralPath $exe)) {
        Report SORUN "$label`: program bulunamadı" "$exe (program kaldırılmış veya taşınmış olabilir)"
        continue
    }
    Test-Protected $exe $label
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "$label (sormadan).lnk"
    if (-not (Test-Path -LiteralPath $lnk)) { Report DIKKAT "$label`: masaüstü kısayolu yok" "yonetici-kisayol.ps1 ile yeniden oluşturun." }
}

$compat = @()
foreach ($root in "HKCU:", "HKLM:") {
    $key = Get-Item "$root\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    if (-not $key) { continue }
    foreach ($name in $key.GetValueNames()) {
        if ($name -like "*\nc32.exe" -and $key.GetValue($name) -match "RUNASADMIN") { $compat += $name }
    }
}
if ($compat.Count) { Report SORUN "Netcad yine 'yönetici olarak çalıştır' işaretli; Evet/Hayır soracak" ($compat -join "; ") }
else { Report OK "Netcad yönetici izni istemiyor" }

# ---------------------------------------------------------------------------------------
Section "Windows Güvenliği (Defender)"

$mp = Get-MpComputerStatus
$pref = Get-MpPreference
if (-not $mp -or -not $pref) {
    Report BILGI "Defender durumu okunamadı (başka bir antivirüs kullanılıyor olabilir)"
} else {
    if ($mp.RealTimeProtectionEnabled) { Report OK "Gerçek zamanlı koruma açık" }
    else { Report DIKKAT "Gerçek zamanlı koruma kapalı" }

    if ($pref.EnableControlledFolderAccess -eq 1) {
        Report DIKKAT "Denetimli klasör erişimi (fidye yazılımı koruması) açık" "Netcad/SHARE/CHC'nin Belgeler ve Masaüstü'ne kaydetmesi engellenebilir. Engellenirse: Windows Güvenliği -> Virüs ve tehdit koruması -> Fidye yazılımı koruması -> İzin verilen uygulamalar."
    } else {
        Report OK "Denetimli klasör erişimi kapalı"
    }

    $asrBlock = 0
    for ($i = 0; $i -lt @($pref.AttackSurfaceReductionRules_Ids).Count; $i++) {
        if (@($pref.AttackSurfaceReductionRules_Actions)[$i] -eq 1) { $asrBlock++ }
    }
    if ($asrBlock) {
        Report DIKKAT "$asrBlock saldırı yüzeyi azaltma (ASR) kuralı engelleme modunda" "Bir program açılmazsa Windows Güvenliği -> Koruma geçmişi'ne bakın."
    }
}

# ---------------------------------------------------------------------------------------
Write-Host ""
Write-Host ("Sonuç: {0} tamam, {1} dikkat, {2} sorun" -f $script:counts.OK, $script:counts.DIKKAT, $script:counts.SORUN) -ForegroundColor Cyan
if ($script:counts.SORUN) { Write-Host "[SORUN] satırları uzaktan erişimi bozabilir; altlarındaki talimatı izleyin." -ForegroundColor Red }

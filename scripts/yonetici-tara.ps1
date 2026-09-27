<#
.SYNOPSIS
    Açılırken yönetici izni ("Evet/Hayır" UAC penceresi) isteyecek programları listeler.

.DESCRIPTION
    UAC penceresi güvenli masaüstünde açılır ve uzaktan tıklanamaz. Bu betik,
    uzaktayken sürprizle karşılaşmamak için şunları tarar:
      - Masaüstü, Başlat menüsü, görev çubuğu ve Başlangıç klasöründeki kısayollar
      - Windows ile otomatik başlayan programlar (Run kayıt anahtarları)
      - "Bu programı yönetici olarak çalıştır" uyumluluk ayarı verilmiş programlar
    Bir program şu durumlardan biri varsa listeye girer:
      - Kısayolun "Gelişmiş > Yönetici olarak çalıştır" kutusu işaretli
      - Uyumluluk sekmesinde "yönetici olarak çalıştır" işaretli
      - Programın kendisi yönetici izni istiyor (manifest: requireAdministrator /
        highestAvailable)
    Yalnızca okur, hiçbir şeyi değiştirmez. Yönetici olmadan da çalışır.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\yonetici-tara.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "SilentlyContinue"

function Get-ManifestLevel([string]$Exe) {
    # Manifest, exe içinde düz metin (UTF-8) olarak durur
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $null }
    $hit = Select-String -LiteralPath $Exe -List `
        -Pattern 'level\s*=\s*["''](requireAdministrator|highestAvailable)["'']'
    if ($hit) { return $hit.Matches[0].Groups[1].Value }
    return $null
}

function Test-LnkRunAsAdmin([string]$Lnk) {
    # .lnk başlığında LinkFlags (0x14. bayt) içindeki RunAsUser (0x2000) biti
    $b = [IO.File]::ReadAllBytes($Lnk)
    if ($b.Length -lt 0x18) { return $false }
    return ([BitConverter]::ToUInt32($b, 0x14) -band 0x2000) -ne 0
}

function Get-ExeFromCommand([string]$Cmd) {
    $Cmd = [Environment]::ExpandEnvironmentVariables($Cmd.Trim())
    if ($Cmd -match '^"([^"]+)"') { return $Matches[1] }
    if ($Cmd -match '^(.+?\.exe)\b') { return $Matches[1] }
    return $Cmd
}

$found = @{}
function Add-Hit([string]$Exe, [string]$Reason, [string]$Where) {
    if (-not $Exe) { return }
    $key = $Exe.ToLowerInvariant()
    if (-not $found.ContainsKey($key)) {
        $found[$key] = [pscustomobject]@{
            Program = [IO.Path]::GetFileNameWithoutExtension($Exe)
            Neden   = $Reason
            Nerede  = $Where
            Yol     = $Exe
        }
    }
}

$compatLayers = @{}
foreach ($root in "HKCU:", "HKLM:") {
    $key = Get-Item "$root\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    if (-not $key) { continue }
    foreach ($name in $key.GetValueNames()) {
        if ($key.GetValue($name) -match "RUNASADMIN") { $compatLayers[$name.ToLowerInvariant()] = $true }
    }
}

function Test-Exe([string]$Exe, [string]$Where, [bool]$LnkRunAs = $false) {
    if (-not $Exe -or $Exe -notmatch '\.exe$') { return }
    if ($LnkRunAs) { Add-Hit $Exe "Kısayolda 'Yönetici olarak çalıştır' işaretli" $Where; return }
    if ($compatLayers.ContainsKey($Exe.ToLowerInvariant())) {
        Add-Hit $Exe "Uyumluluk ayarında 'yönetici olarak çalıştır' işaretli" $Where; return
    }
    $level = Get-ManifestLevel $Exe
    if ($level) { Add-Hit $Exe "Program kendisi yönetici izni istiyor ($level)" $Where }
}

Write-Host "Taranıyor, bir iki dakika sürebilir..." -ForegroundColor Cyan

$runKeys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
)
foreach ($k in $runKeys) {
    $key = Get-Item $k
    if (-not $key) { continue }
    foreach ($name in $key.GetValueNames()) {
        Test-Exe (Get-ExeFromCommand ([string]$key.GetValue($name))) "Açılışta"
    }
}
$shell = New-Object -ComObject WScript.Shell
# Açılışta çalışanlar önce: aynı program birden çok yerdeyse "Açılışta" görünsün
$places = [ordered]@{
    "Açılışta"      = @([Environment]::GetFolderPath("Startup"), [Environment]::GetFolderPath("CommonStartup"))
    "Masaüstü"      = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("CommonDesktopDirectory"))
    "Başlat menüsü" = @([Environment]::GetFolderPath("StartMenu"), [Environment]::GetFolderPath("CommonStartMenu"))
    "Görev çubuğu"  = @("$env:APPDATA\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar")
}
foreach ($where in $places.Keys) {
    foreach ($dir in $places[$where]) {
        if (-not $dir -or -not (Test-Path $dir)) { continue }
        Get-ChildItem -LiteralPath $dir -Recurse -Filter *.lnk | ForEach-Object {
            $target = $shell.CreateShortcut($_.FullName).TargetPath
            Test-Exe $target $where (Test-LnkRunAsAdmin $_.FullName)
        }
    }
}

foreach ($exe in $compatLayers.Keys) { Test-Exe $exe "Uyumluluk ayarı" }

$list = $found.Values | Sort-Object Nerede, Program
Write-Host ""
if (-not $list) {
    Write-Host "Yönetici izni isteyen program bulunamadı." -ForegroundColor Green
} else {
    Write-Host "Açılırken 'Evet/Hayır' soracak programlar ($(@($list).Count) adet):" -ForegroundColor Yellow
    $list | Format-Table Program, Nerede, Neden -AutoSize -Wrap | Out-String -Width 200 | Write-Host
    Write-Host "Tam yollar:"
    $list | ForEach-Object { Write-Host "  $($_.Program): $($_.Yol)" }
    if ($list | Where-Object Nerede -eq "Açılışta") {
        Write-Host ""
        Write-Host "DİKKAT: 'Açılışta' olanlar bilgisayar yeniden başlayınca Evet/Hayır penceresi açar." -ForegroundColor Yellow
        Write-Host "Bu pencere açıkken uzaktan kontrol çalışmaz."
    }
    Write-Host ""
    Write-Host "Uzaktan açmanız gerekenler için sormadan açan kısayol:"
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\scripts\yonetici-kisayol.ps1 -Exe "<tam yol>"'
}
Write-Host ""
Write-Host "Not: Kurulum/kaldırma programları ve yönetici olarak açılan PowerShell / Komut İstemi de her zaman sorar."

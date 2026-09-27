<#
.SYNOPSIS
    Uzak Masaüstü Ajanı'nı kaldırır (görev, güvenlik duvarı kuralları, program dosyaları).
    Yapılandırma klasörü (parola özeti, günlükler) -KeepConfig verilmezse silinir.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:ProgramFiles\RemoteAgent",
    [string]$ConfigDir = "$env:ProgramData\RemoteAgent",
    [switch]$KeepConfig,
    # Kurulumda -EnableRdp kullandıysanız RDP'yi de kapat
    [switch]$DisableRdp
)
$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName "RemoteAgent" -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName "RemoteAgent" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "RemoteAgent" -Confirm:$false
    Write-Host "Zamanlanmış görev kaldırıldı."
}
if (Get-ScheduledTask -TaskName "RemoteAgentWatchdog" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "RemoteAgentWatchdog" -Confirm:$false
    Write-Host "Bekçi görevi kaldırıldı."
}
Get-NetFirewallRule -DisplayName "RemoteAgent*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "Güvenlik duvarı kuralları kaldırıldı."

if ($DisableRdp) {
    Set-ItemProperty "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 1
    Write-Host "Windows Uzak Masaüstü kapatıldı."
}

Start-Sleep -Seconds 1
if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir; Write-Host "Silindi: $InstallDir" }
if (-not $KeepConfig -and (Test-Path $ConfigDir)) { Remove-Item -Recurse -Force $ConfigDir; Write-Host "Silindi: $ConfigDir" }
Write-Host "Kaldırma tamamlandı." -ForegroundColor Green

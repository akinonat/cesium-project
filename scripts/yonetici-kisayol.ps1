<#
.SYNOPSIS
    Bir programı "Evet/Hayır" (UAC) sormadan yönetici olarak açan masaüstü kısayolu oluşturur.

.DESCRIPTION
    UAC penceresi uzaktan tıklanamadığı için, uzaktayken açmanız gereken ve yönetici
    izni isteyen programlar için kullanın. Görev Zamanlayıcı'ya "en yüksek
    ayrıcalıklarla" çalışan bir görev ekler ve masaüstüne o görevi başlatan bir
    kısayol koyar. İzin yalnızca bu programa verilir; diğer programlar yine sorar.

    Not: Bu kısayol programa dosya adı iletmez. Dosyaları program açıldıktan sonra
    Dosya > Aç ile açın (bir dosyaya çift tıklamak yine Evet/Hayır sorar).

.EXAMPLE
    # Yönetici PowerShell'de:
    powershell -ExecutionPolicy Bypass -File .\scripts\yonetici-kisayol.ps1 -Exe "C:\Program Files\Netcad\netcad.exe"

.EXAMPLE
    # Uzaktayken yönetici PowerShell açabilmek için:
    powershell -ExecutionPolicy Bypass -File .\scripts\yonetici-kisayol.ps1 -Exe "$env:windir\System32\WindowsPowerShell\v1.0\powershell.exe" -Name "PowerShell (yonetici)"

.EXAMPLE
    # Oluşturulan görevi ve kısayolu kaldırmak için:
    powershell -ExecutionPolicy Bypass -File .\scripts\yonetici-kisayol.ps1 -Name "Netcad" -Remove
#>
[CmdletBinding()]
param(
    [string]$Exe,
    [string]$Name,
    [string]$Arguments,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Bu betiği 'Yönetici olarak çalıştır' ile açılmış PowerShell'de çalıştırın."
}

if ($Exe) { $Exe = $Exe.Trim().Trim('"') }
if (-not $Name) {
    if (-not $Exe) { Write-Error "-Exe (programın tam yolu) gerekli." }
    $Name = [IO.Path]::GetFileNameWithoutExtension($Exe)
}
$TaskName = "Sormadan - $Name"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$Name (sormadan).lnk"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Shortcut -ErrorAction SilentlyContinue
    Write-Host "Kaldırıldı: $TaskName" -ForegroundColor Green
    return
}

if (-not $Exe) { Write-Error "-Exe (programın tam yolu) gerekli." }
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { Write-Error "Program bulunamadı: $Exe" }

# Kullanıcının yazabildiği bir klasördeki programa bu izni vermek risklidir:
# başka bir program o dosyayı değiştirip yönetici yetkisi kazanabilir.
$safeRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:windir) | Where-Object { $_ }
$isSafe = $safeRoots | Where-Object { $Exe.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }
if (-not $isSafe) {
    Write-Warning "Program 'Program Files' veya 'Windows' klasöründe değil. Bu klasöre başka programlar da yazabiliyorsa güvenlik riski oluşur."
}

$actionArgs = @{ Execute = $Exe; WorkingDirectory = (Split-Path $Exe) }
if ($Arguments) { $actionArgs.Argument = $Arguments }
$action = New-ScheduledTaskAction @actionArgs
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances Parallel
Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $taskPrincipal `
    -Settings $settings -Description "$Exe programını UAC sormadan açar" -Force | Out-Null

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($Shortcut)
$lnk.TargetPath = "$env:windir\System32\schtasks.exe"
$lnk.Arguments = "/run /tn `"$TaskName`""
$lnk.IconLocation = "$Exe,0"
$lnk.WindowStyle = 7  # küçültülmüş: siyah pencere belirip kaybolur
$lnk.Save()

Write-Host "Hazır: masaüstünde '$Name (sormadan)' kısayolu oluşturuldu." -ForegroundColor Green

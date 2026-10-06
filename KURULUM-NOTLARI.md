# Kurulum Notları — Ev Bilgisayarı (ASUS ROG Strix)

Bu bilgisayara uzak masaüstünün nasıl kurulduğunun kaydı. Windows yeniden
kurulursa, bilgisayar değişirse ya da bir şey bozulursa bu listeyi baştan sona
izleyin. Genel kullanım ve sorun giderme için `README.md` dosyasına bakın.

> Parolalar bu dosyada **yazmaz**. Uzak masaüstü parolasını ve Windows parolasını
> kendi parola yöneticinizde saklayın.

## Özet

| | |
|---|---|
| Bilgisayar | ASUS ROG Strix dizüstü, Windows 11 Home Single Language |
| Windows kullanıcısı | `MAPSURVEY` (yerel hesap, yönetici) |
| Bilgisayar adı | `DESKTOP-O22ECE0` |
| Ekranlar | Dizüstü ekranı 2560×1440 + harici monitör 1920×1080 |
| Tailscale hesabı | akinonat@gmail.com (Google ile giriş) |
| Tailscale adresi | `100.103.108.113` |
| **Bağlanma adresi** | **http://100.103.108.113:8765** (Surface ve iPhone'dan; bilgisayar adıyla açılmıyor, IP kullanın) |
| Program | `C:\Program Files\RemoteAgent` |
| Ayarlar ve günlükler | `C:\ProgramData\RemoteAgent` (`agent.log`, `watchdog.log`) |
| Kurulum dosyaları | `C:\Users\MapSurvey\Desktop\Claude\uzak-masaustu` |
| Yedek | Google Drive'daki `uzak-masaustu.zip` (ikinci kopya: GitHub `akinonat/cesium-project` deposu, `claude/windows-remote-desktop-control-5e94s7` dalı) |

## Sıfırdan kurulum

### 1. Kurulum dosyalarını indirin

1. Google Drive'daki **uzak-masaustu.zip** dosyasını indirin.
2. PowerShell'de (yönetici olması gerekmez) ZIP'i yerine çıkarın:
   ```powershell
   New-Item -ItemType Directory -Force "C:\Users\MapSurvey\Desktop\Claude" | Out-Null
   Expand-Archive "C:\Users\MapSurvey\Downloads\uzak-masaustu.zip" -DestinationPath "C:\Users\MapSurvey\Desktop\Claude" -Force
   ```
   Klasör `C:\Users\MapSurvey\Desktop\Claude\uzak-masaustu` olarak çıkar. İndirilen dosyanın adı farklıysa
   (ör. `uzak-masaustu (1).zip`) komutta düzeltin.

   Drive'daki ZIP'e ulaşamazsanız ikinci kopya (GitHub'a giriş yapmış olmalısınız):
   https://github.com/akinonat/cesium-project/archive/refs/heads/claude/windows-remote-desktop-control-5e94s7.zip
   — bu ZIP'ten çıkan klasörün adını `uzak-masaustu` yapın.

### 2. Tailscale

1. https://tailscale.com/download/windows → kurun → **akinonat@gmail.com** Google
   hesabıyla girin.
2. Saatin yanındaki Tailscale simgesi → **Preferences → Run unattended** işaretleyin.
3. https://login.tailscale.com/admin/machines → bu bilgisayar → **⋯ → Disable key expiry**.
4. Simgenin menüsünde **This device** satırındaki `100.x.x.x` adresine bakın.
   Bilgisayar Tailscale'den silinip yeniden eklendiyse adres değişmiş olabilir;
   Surface'teki sık kullanılanı güncelleyin.

### 3. Programı kurun

Yönetici PowerShell'de:

```powershell
cd "C:\Users\MapSurvey\Desktop\Claude\uzak-masaustu"
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

- Parola sorarken yazılanlar ekranda görünmez (normal). En az 10 karakter.
- Betik şunları kendisi yapar: Python, program dosyaları, güvenlik duvarı (yalnızca
  Tailscale), oturum açılışında otomatik başlatma, 5 dakikalık bekçi görevi,
  prizdeyken uyku kapalı, **kapak kapanınca uyumama**, **uyanınca parola sormama**.
- Kontrol: tarayıcıda http://localhost:8765 açılıp giriş yapılabilmeli.

### 4. Kilit ayarları

**Ayarlar → Hesaplar → Oturum açma seçenekleri**:

- **Dinamik kilit** kapalı (açıksa iPhone uzaklaşınca bilgisayar kilitlenir).
- "Ne kadar süre uzak kaldığınızda Windows yeniden oturum açmanızı istesin?" →
  **Hiçbir zaman** (kurulum betiği ayarlar, kontrol edin).
- "Bir güncelleştirmeden sonra … oturum açma bilgilerimi kullan" → **Kapalı**
  (açıkken güncelleme sonrası ekranı kilitli bırakır).

### 5. Otomatik oturum açma (Autologon)

Bilgisayar yeniden başlayınca parola sormadan masaüstü gelsin, program çalışsın diye.

1. https://learn.microsoft.com/sysinternals/downloads/autologon → indirin, ayıklayın.
2. `Autologon64.exe` → **Agree**.
3. Username: `MAPSURVEY`, Domain: `DESKTOP-O22ECE0`, Password: Windows parolası
   (PIN değil) → **Enable**.
4. Bilgisayarı yeniden başlatıp PIN sormadan masaüstünün geldiğini kontrol edin.

### 6. "Evet/Hayır" (UAC) soran programlar

UAC penceresi uzaktan tıklanamaz. Önce tarayın:

```powershell
cd "C:\Users\MapSurvey\Desktop\Claude\uzak-masaustu"
powershell -ExecutionPolicy Bypass -File .\scripts\yonetici-tara.ps1
```

27.09.2026 taramasında **açılışta** soran program yoktu. Uzaktan kullanılan
programlar için yapılanlar:

**Netcad** — gereksiz "yönetici olarak çalıştır" işareti kaldırıldı; izinsiz sorunsuz
çalışıyor (USB lisans dahil). Netcad yeniden kurulursa ya da tekrar sorarsa yönetici
PowerShell'de:

```powershell
foreach ($root in "HKCU:", "HKLM:") {
    $path = "$root\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    $key = Get-Item $path -ErrorAction SilentlyContinue
    if (-not $key) { continue }
    foreach ($name in $key.GetValueNames()) {
        if ($name -like "*\nc32.exe") {
            $new = (($key.GetValue($name) -replace '\bRUNASADMIN\b', '') -replace '\s+', ' ').Trim()
            if ($new -in "", "~") { Remove-ItemProperty -Path $path -Name $name } else { Set-ItemProperty -Path $path -Name $name -Value $new }
            Write-Host "Temizlendi: $name"
        }
    }
}
```

**SHARE PointClouds Studio** — program yönetici iznini kendisi istiyor.

1. Kurulum `Program Files`'a izin vermiyor; önerdiği `C:\Share PointClouds\` klasörüne
   kurun (26.8 GB).
2. Klasörü yalnızca yöneticilerin değiştirebileceği hale getirin (yönetici PowerShell):
   ```powershell
   icacls "C:\Share PointClouds" /inheritance:d
   icacls "C:\Share PointClouds" /remove:g "*S-1-5-11"
   icacls "C:\Share PointClouds" /grant:r "*S-1-5-32-545:(OI)(CI)RX"
   ```
   Kontrol (normal PowerShell): `New-Item "C:\Share PointClouds\SHARE Product\deneme.txt"`
   → **Erişim reddedildi** vermeli.
3. Sormadan açan kısayol (yönetici PowerShell; sarı uyarı beklenen bir durum):
   ```powershell
   cd "C:\Users\MapSurvey\Desktop\Claude\uzak-masaustu"
   powershell -ExecutionPolicy Bypass -File .\scripts\yonetici-kisayol.ps1 -Exe "C:\Share PointClouds\SHARE Product\SHARE PointClouds Studio\SHARE PointClouds Studio.exe" -Name "SHARE PointClouds Studio"
   ```
   Uzaktan her zaman masaüstündeki **"SHARE PointClouds Studio (sormadan)"**
   kısayolunu kullanın.

**Global Mapper** sormuyor. Listede görünen `Package Cache\…\GlobalMapper.exe`
kurulum/kaldırma dosyasıdır.

**CHC Geomatics Office 2** ve araçları soruyor ve `AppData` altında kurulu. Uzaktan
gerekirse SHARE'deki yöntemi uygulayın (tercihen korumalı bir klasöre yeniden kurarak).

### 7. Surface (ve iPhone)

1. Tailscale'i kurun, **aynı Google hesabıyla** girin.
2. Edge'de **http://100.103.108.113:8765** → parola → sık kullanılanlara ekleyin.

### 8. Son kontrol

Kurulumdan 5 dakika sonra yönetici PowerShell'de:

```powershell
cd "C:\Users\MapSurvey\Desktop\Claude\uzak-masaustu"
powershell -ExecutionPolicy Bypass -File .\scripts\kontrol.ps1
```

Tüm ayarları (program, bekçi, Tailscale, güvenlik duvarı, güç/kilit, otomatik oturum
açma, UAC, sormadan açılan programlar, Netcad, Windows Güvenliği) denetler; hiçbir
şeyi değiştirmez. `[SORUN]` satırı olmamalı. Windows güncellemesinden ya da güvenlik
ayarı değişikliğinden sonra da çalıştırın. Ardından Surface'i iPhone erişim
noktasına bağlayıp (gerçek "dışarıdan" deneme) bağlanın.

## Günlük kullanım hatırlatmaları

- Şarj aleti takılı kalsın. Kapak kapatılabilir, bilgisayar uyumaz.
- **Win+L ile kilitlemeyin**; kilitli ekran uzaktan açılamaz (Windows Home'da RDP yok).
- Uzaktayken **program kurmayın/güncellemeyin**; kurulumlar "Evet/Hayır" sorar.
- Büyük dosyalar için SendGB vb. siteleri ev bilgisayarının tarayıcısında kullanın
  (dosya ev internetine iner, mobil veri harcanmaz).
- Surface'te ekranın üstünde **sarı uyarı şeridi** çıkarsa talimatını izleyin
  (çoğunlukla Tailscale anahtarı).
- Elektrik uzun süre kesilir de pil biterse bilgisayar kendiliğinden açılmaz;
  birinin güç düğmesine basması gerekir.

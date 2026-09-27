# Uzak Masaüstü Ajanı

Ofisteki Windows bilgisayarınızı, dışarıdayken **Surface**'inizden (veya herhangi
bir cihazın tarayıcısından) görüp kontrol etmenizi sağlayan küçük, kendi kendinize
barındırdığınız bir uzak masaüstü yazılımı.

- Ofis bilgisayarında arka planda çalışan bir **ajan** (Python) ekranı yayınlar,
  fare ve klavye komutlarını uygular.
- Surface'e **hiçbir şey kurmanız gerekmez**: Edge'de adresi açıp parolayla girersiniz.
- İnternet üzerinden erişim için **Tailscale** kullanılır: modemde port açmak
  gerekmez, trafik uçtan uca şifrelenir ve bilgisayar internete hiç açılmaz.

```
 Surface (Edge)                    İnternet                     Ofis PC
┌──────────────┐   Tailscale (WireGuard, şifreli tünel)   ┌──────────────────┐
│ tarayıcı     │ ◀──── ekran görüntüsü (JPEG döşemeler) ── │ remote_agent     │
│ arayüzü      │ ───── fare / klavye / pano ─────────────▶ │  (Windows)       │
└──────────────┘                                           └──────────────────┘
```

## Özellikler

- Canlı ekran; yalnızca **değişen bölgeler** gönderilir (düşük bant genişliği)
- Kalite seçimi: Düşük (mobil veri) / Orta / Yüksek
- Birden fazla monitör desteği (tek tek ya da hepsi birden)
- Fare: tık, sağ tık, orta tık, sürükleme, tekerlek
- **Dokunmatik** (Surface ekranı): dokun = tık, basılı tut = sağ tık,
  tek parmakla sürükle = sürükle-bırak, iki parmak = kaydırma
- Klavye: Türkçe karakterler dahil tüm metin (klavye düzeninden bağımsız),
  Ctrl+C / Ctrl+V gibi kısayollar, dokunmatik klavye düğmesi
- Tek tıkla: Başlat (Win), Alt+Tab, Win+D, Görev Yöneticisi
- **Pano**: uzak panodaki metni al, kendi metninizi uzak panoya gönder veya yazdır
- Ofis PC'nin uykuya geçmesini engeller
- Bağlantı koparsa parola sormadan otomatik yeniden bağlanır; bekçi görevi
  Tailscale'i ve ajanı 5 dakikada bir denetleyip onarır
- Güvenlik: PBKDF2 ile saklanan parola, kaba kuvvet denemelerine karşı artan
  kilitleme, HttpOnly/SameSite oturum çerezi, WebSocket kaynak (Origin) denetimi,
  sıkı içerik güvenlik politikası, bağlantı koparsa basılı kalan tuşların bırakılması

---

## Kurulum

### 1. Tailscale (her iki cihaza da, bir kez)

1. <https://tailscale.com/download> adresinden **ofis bilgisayarına** ve
   **Surface'e** Tailscale'i kurun.
2. İkisinde de **aynı hesapla** giriş yapın (Google/Microsoft hesabı olabilir).
3. Ofis bilgisayarında Tailscale'in Windows ile başladığından emin olun
   (varsayılan olarak başlar).
4. Önerilir: Tailscale yönetim panelinde (<https://login.tailscale.com/admin/machines>)
   ofis bilgisayarı için **"Disable key expiry"** seçin; aksi halde birkaç ayda bir
   yeniden giriş istenir ve dışarıdan erişim kesilir.

> Tailscale kişisel kullanımda ücretsizdir. Kurduktan sonra cihazlar birbirini
> `100.x.y.z` adresleriyle ya da bilgisayar adıyla görür.

### 2. Ajanı ofis bilgisayarına kurun

1. Bu depoyu ofis bilgisayarına indirin (GitHub'da **Code → Download ZIP**, sonra
   ZIP'i bir klasöre çıkarın).
2. **Başlat** menüsüne `PowerShell` yazın → **Yönetici olarak çalıştır**.
3. Proje klasörüne gidip kurulum betiğini çalıştırın:

   ```powershell
   cd "C:\Users\<kullanici>\Downloads\cesium-project"
   powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
   ```

4. Sizden bir **parola** istenecek (en az 10 karakter). Surface'ten bağlanırken bu
   parolayı kullanacaksınız — güçlü ve başka yerde kullanmadığınız bir parola seçin.

Betik şunları yapar: gerekiyorsa Python'u kurar, ajanı
`C:\Program Files\RemoteAgent` klasörüne yerleştirir, Windows oturumu açıldığında
ajanı otomatik başlatır (çökerse 1 dakika içinde yeniden başlatır), güvenlik
duvarında 8765 numaralı portu **yalnızca Tailscale ağına** açar ve bilgisayar
prizdeyken uyku modunu kapatır.

Kullanılabilir seçenekler:

| Seçenek | Açıklama |
|---|---|
| `-Port 9000` | Farklı bir port kullan (varsayılan 8765) |
| `-Name "Ofis"` | Giriş ekranında görünecek ad |
| `-AllowLan` | Ofis içi yerel ağdan da (Tailscale olmadan) erişime izin ver |
| `-EnableRdp` | Windows Uzak Masaüstü'nü de aç (bkz. [Kilit ekranı](#kilit-ekranı-önemli)) |
| `-KeepPowerSettings` | Güç/uyku ayarlarına dokunma |

Kurulum bitince ofis bilgisayarında tarayıcıda <http://localhost:8765> açarak
deneyebilirsiniz.

### 3. Surface'ten bağlanın

1. Surface'te Tailscale'in **bağlı** olduğundan emin olun (görev çubuğundaki simge).
2. Edge'de şu adreslerden birini açın:
   - `http://<ofis-bilgisayarinin-adi>:8765` (ör. `http://ofis-pc:8765`), veya
   - `http://100.x.y.z:8765` (kurulumun sonunda yazdırılan Tailscale adresi).
3. Parolanızı girin. Adresi **Sık Kullanılanlar**'a ekleyin.

---

## Kullanım

| Araç çubuğu | İşlev |
|---|---|
| Ekran seçimi | Birden fazla monitör varsa hangisinin gösterileceği |
| Kalite | **Düşük**: mobil veri / zayıf bağlantı · **Orta**: varsayılan · **Yüksek**: tam çözünürlük |
| ⌨ Klavye | Surface'in dokunmatik klavyesini açar (Type Cover takılıyken gerekmez) |
| ⊞ Win, Alt+Tab, Win+D | Surface'in kendisinin yakaladığı tuş kombinasyonlarını uzak bilgisayara gönderir |
| Görev Yön. | Ctrl+Shift+Esc (Görev Yöneticisi) |
| 📋 Pano | Uzak panoyu alma / uzak panoya metin gönderme / metni yazdırma |
| ⛶ | Tam ekran |
| ▲ | Araç çubuğunu gizler (üstteki ▼ ile geri gelir) |
| Çıkış | Oturumu kapatır |

**Dokunmatik hareketler:** dokun = sol tık · basılı tut (0,6 sn) = sağ tık ·
tek parmakla sürükle = sürükle-bırak · iki parmakla kaydır = fare tekerleği.
Kalem ve touchpad fare gibi davranır.

**Klavye:** Type Cover ile doğrudan yazabilirsiniz. Ctrl+C, Ctrl+V, Ctrl+Z, Shift+ok
tuşları vb. uzak bilgisayara iletilir. Tarayıcının/Windows'un kendine ayırdığı bazı
kısayollar (Ctrl+W, Ctrl+T, Win tuşu, Alt+Tab, Ctrl+Alt+Del) iletilemez; bunlar için
araç çubuğundaki düğmeleri kullanın.

**Pano:** Güvenlik nedeniyle tarayıcılar `http://` sayfalarında panoya doğrudan
erişime izin vermez. Bu yüzden **📋 Pano** penceresi kullanılır:
*Uzak panoyu al* → metin kutuya gelir, Ctrl+C ile kopyalarsınız.
Kendi metninizi kutuya yapıştırıp *Uzak panoya gönder* veya *Metni yazdır*.

### İki (veya daha fazla) bilgisayar

Kontrol etmek istediğiniz **her** Windows bilgisayara ajanı aynı şekilde kurun
(her birine Tailscale + `install.ps1`). Surface'te her biri için ayrı bir sık
kullanılan ekleyin, ör. `http://ofis-pc:8765` ve `http://ev-pc:8765`. Aynı anda
iki sekmede iki bilgisayarı birden kontrol edebilirsiniz.

---

## Kilit ekranı (önemli)

Ajan, Windows'ta **oturum açmış kullanıcı** olarak çalışır. Bu yüzden:

- Ofis bilgisayarı **kilitliyken (Win+L, ekran koruyucu kilidi)** veya bir **UAC "Evet/Hayır" penceresi**
  açıkken ekran uzaktan kontrol edilemez. Bu durumda Surface'te
  *"Uzak bilgisayar kilitli…"* uyarısı görünür.
- Bilgisayar **yeniden başlarsa** (ör. Windows Update), ajan ancak Windows'ta
  **oturum açıldığında** başlar.

Çözüm seçenekleri:

1. **Windows Pro/Enterprise ise (önerilir):** kurulumda `-EnableRdp` ekleyin.
   Böylece Windows'un kendi Uzak Masaüstü'nü de Tailscale üzerinden kullanabilirsiniz:
   Surface'te **Uzak Masaüstü Bağlantısı** (`mstsc`) veya **Windows App**'i açıp
   `ofis-pc` adresine Windows kullanıcı adı/parolanızla bağlanın. RDP kilit
   ekranında ve yeniden başlatmadan sonra da çalışır. Bu ajan ise RDP'nin
   olmadığı Home sürümlerinde ve ekrandaki **mevcut** oturumu olduğu gibi görmek
   istediğinizde işe yarar.
2. Ofisten çıkarken bilgisayarı kilitlemek yerine **yalnızca monitörü kapatın**
   (ofis fiziksel olarak güvenliyse). Ajan açıkken bilgisayar uykuya geçmez; ancak
   ekran koruyucu veya "uzaktayken oturum aç" ayarı kilitleyebilir — 3. maddeye bakın.
3. Ayarlar → Hesaplar → Oturum açma seçenekleri → *"Uzakta olduğunuzda Windows'un
   yeniden oturum açmanızı ne zaman gerektirmesi gerekir"* → **Hiçbir zaman**; ve
   ekran koruyucuda *"Sürdürüldüğünde oturum açma ekranını görüntüle"* kapalı olsun.
4. İsteğe bağlı: yönetici gerektiren işlemler için UAC penceresinin normal masaüstünde
   çıkmasını sağlayabilirsiniz (`secpol.msc` → Yerel İlkeler → Güvenlik Seçenekleri →
   *"Kullanıcı Hesabı Denetimi: Yükseltme istenirken güvenli masaüstüne geç"* →
   Devre dışı). Bu, güvenliği bir miktar azaltır.

### Ofis bilgisayarı için kontrol listesi

- [ ] Tailscale kurulu, oturum açık, *key expiry* kapalı
- [ ] Ajan kurulu; <http://localhost:8765> açılıyor
- [ ] Uyku kapalı (betik yapar); dizüstü ise kapak kapatıldığında "Hiçbir şey yapma"
- [ ] BIOS'ta **"Restore on AC Power Loss → Power On"** (elektrik kesintisinden sonra kendiliğinden açılsın)
- [ ] Windows Update için **Etkin saatler**'i çalışma saatlerinize göre ayarlayın
- [ ] Mümkünse Wi-Fi yerine **kablolu** internet
- [ ] Tailscale menüsünde **Preferences → Run unattended** açık (oturum kapansa bile Tailscale bağlı kalır)

---

## Bağlantı kesintileri

**Bağlantı giderse:** Surface'te *"Bağlantı koptu, … sn içinde yeniden denenecek"*
yazar ve program kendiliğinden yeniden bağlanmayı dener (1 sn'den başlayıp en fazla
15 sn arayla, süresiz). İnternet geri gelince veya uygulamaya geri dönünce hemen
dener; beklemek istemezseniz uyarıya dokunun. **Parolayı tekrar girmeniz gerekmez.**
Wi-Fi'dan mobil veriye geçerken "sessizce ölen" bağlantılar da en geç ~20 sn'de
fark edilir. Bağlantı koptuğu anda basılı olan tuşlar ve fare düğmeleri ofis
bilgisayarında otomatik bırakılır (takılı Ctrl kalmaz). Kesinti sırasında
yazdıklarınız karşıya ulaşmaz; bağlanınca son yazdığınızı kontrol edin.

**Ofis bilgisayarı açık ama bağlanılamıyorsa:** kurulum, her 5 dakikada bir
çalışan bir **bekçi** görevi ekler (`RemoteAgentWatchdog`). Bekçi:

- Tailscale hizmeti durmuşsa başlatır, Tailscale kapatılmışsa yeniden açar,
- Ajan çökmüş ya da donmuşsa yeniden başlatır,
- Kendi çözemediği sorunları — Tailscale'in yeniden giriş istemesi veya anahtar
  süresinin **14 günden az** kalması — kaydeder; Surface'ten bağlandığınızda ekranın
  üstünde **sarı uyarı şeridi** olarak görürsünüz. Böylece erişim kesilmeden önce
  haberiniz olur.

Tüm onarımlar `C:\ProgramData\RemoteAgent\watchdog.log` dosyasına yazılır.
Dışarıdayken hangi tarafta sorun olduğunu anlamak için Surface'teki Tailscale
uygulamasına bakın: ofis bilgisayarı orada **çevrimiçi** görünüyor ama sayfa
açılmıyorsa sorun ajandadır ve bekçi en geç 5 dakikada onu yeniden başlatır.
**Çevrimdışı** görünüyorsa sorun ofisin internetinde veya bilgisayarın gücündedir.

## Bilgisayarı uzaktan açma ve otomatik oturum açma

Bilgisayar kapalıysa (elektrik kesintisi, biri kapattı) uzaktan açmak için:

- **En kolayı:** BIOS'ta *Restore on AC Power Loss → Power On* ayarı + **akıllı
  priz**. Prizi uygulamadan kapatıp açınca bilgisayar kendiliğinden açılır. Bunu
  yalnızca bilgisayar zaten kapalıyken veya tamamen donmuşken yapın; açıkken elektriği
  kesmek kaydedilmemiş işleri kaybettirir.
- **Mekanik düğme basıcı:** güç düğmesine basan uzaktan kumandalı bir düzenek
  (hazır ürün olarak SwitchBot Bot gibi) de işe yarar.

Açıldıktan sonra ajanın çalışması için Windows'ta **oturum açılmış** olması gerekir.
Parola ekranını atlayıp doğrudan masaüstüne gelmek için Microsoft'un ücretsiz
**Sysinternals Autologon** aracını kullanın (parolayı şifreli saklar; kayıt defterine
düz metin yazmaktan daha güvenlidir):

1. <https://learn.microsoft.com/sysinternals/downloads/autologon> adresinden indirin.
2. Microsoft hesabıyla ve Windows Hello (PIN) ile giriş yapıyorsanız önce
   Ayarlar → Hesaplar → Oturum açma seçenekleri → *"Gelişmiş güvenlik için bu cihazda
   Microsoft hesapları için yalnızca Windows Hello oturum açmaya izin ver"* seçeneğini
   **kapatın**.
3. `Autologon64.exe`'yi çalıştırın, kullanıcı adı ve Windows parolanızı (PIN değil)
   girip **Enable**'a basın.

⚠ Otomatik oturum açmada ofiste bilgisayarın başına geçen herkes masaüstünüze erişir.
Ofis fiziksel olarak güvenli değilse bunu yapmayın. Ofis bilgisayarı **Windows Pro**
ise daha iyi bir yol var: kurulumda `-EnableRdp` ekleyin. Windows Uzak Masaüstü,
bilgisayar açılıp **oturum açılmadan** da bağlanmanıza izin verir; otomatik oturum
açmaya gerek kalmaz.

---

## Güvenlik

- Port varsayılan olarak **yalnızca Tailscale ağına** (`100.64.0.0/10`) açılır;
  bilgisayar doğrudan internete açılmaz. Tailscale trafiği WireGuard ile şifrelenir.
- Parola düz metin olarak saklanmaz (PBKDF2-SHA256, 600.000 tur);
  `C:\ProgramData\RemoteAgent\config.json` yalnızca sizin ve yöneticilerin
  erişebildiği bir klasördedir.
- 5 hatalı denemeden sonra o adres 30 sn kilitlenir, süre her hatada iki katına
  çıkar (en fazla 1 saat).
- Oturumlar 12 saat sonra düşer (`config.json` → `session_hours`).
- Tüm giriş denemeleri ve bağlantılar `C:\ProgramData\RemoteAgent\agent.log`
  dosyasına yazılır.
- Modemde port yönlendirme yaparak Tailscale **olmadan** kullanmak zorundaysanız,
  mutlaka `--tls` ile HTTPS'i açın (`pip install cryptography` gerekir; kendinden
  imzalı sertifika uyarısını ilk bağlantıda onaylarsınız). Tailscale her zaman
  daha güvenli seçenektir.
- İsteğe bağlı gerçek HTTPS: Tailscale panelinde *HTTPS Certificates* açıksa ofis
  PC'de `tailscale serve --bg http://127.0.0.1:8765` ile
  `https://ofis-pc.<tailnet>.ts.net` adresinden geçerli sertifikayla bağlanabilirsiniz.

Parolayı değiştirmek için (yönetici PowerShell):

```powershell
cd "C:\Program Files\RemoteAgent"
.\.venv\Scripts\python.exe -m remote_agent --config-dir C:\ProgramData\RemoteAgent --set-password
Stop-ScheduledTask RemoteAgent; Start-ScheduledTask RemoteAgent
```

## Sorun giderme

| Belirti | Ne yapmalı |
|---|---|
| Surface'ten sayfa açılmıyor | Her iki cihazda Tailscale bağlı mı? Ofis PC'de <http://localhost:8765> açılıyor mu? `Get-ScheduledTask RemoteAgent` durumu *Running* mi? Ayrıca bkz. [Bağlantı kesintileri](#bağlantı-kesintileri) |
| Sarı uyarı şeridi çıkıyor | Bekçinin çözemediği bir sorun var (çoğunlukla Tailscale anahtarı); şeritteki talimatı izleyin |
| Siyah ekran / "kilitli" uyarısı | Ofis PC kilitli ya da UAC penceresi açık — bkz. [Kilit ekranı](#kilit-ekranı-önemli) |
| Yönetici olarak açılmış bir pencereye tıklanamıyor | Görev "en yüksek ayrıcalıklarla" çalışmalı; `install.ps1`'i yönetici olarak yeniden çalıştırın |
| Görüntü yavaş | Kaliteyi **Düşük** yapın; mobil veride Tailscale doğrudan bağlantı kuramazsa (DERP röle) hız düşebilir |
| Ayrıntılı günlük görmek istiyorum | Görevi durdurup `scripts\run-console.bat` ile konsolda çalıştırın |

Kaldırmak için (yönetici PowerShell, proje klasöründe):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1        # -DisableRdp ile RDP'yi de kapatır
```

---

## Geliştirme

```bash
pip install -r requirements-dev.txt
python -m pytest                       # birim + uçtan uca sunucu testleri
python -m remote_agent --set-password  # yerel deneme için
python -m remote_agent --demo          # gerçek ekran yerine test görüntüsü, gerçek girdi göndermez
```

Proje yapısı:

```
remote_agent/
  main.py        komut satırı, TLS, günlük
  server.py      HTTP/WebSocket sunucusu, giriş, oturumlar, yayın döngüsü
  capture.py     ekran yakalama (mss) ve değişen döşemeleri JPEG olarak kodlama
  input_win.py   fare/klavye (Windows SendInput)
  winutil.py     DPI, uyku engelleme, pano, kilit algılama
  watchdog.py    bekçi: Tailscale ve ajanı denetler, onarır, uyarı yazar
  static/        tarayıcı arayüzü (HTML/CSS/JS, harici bağımlılık yok)
scripts/
  install.ps1    Windows kurulum (görev, güvenlik duvarı, güç, isteğe bağlı RDP)
  uninstall.ps1  kaldırma
  run-console.bat  sorun giderme için konsolda çalıştırma
```

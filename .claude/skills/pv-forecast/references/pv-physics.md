# PV fizik zinciri

## Mevcut zincir (uages) ve pvlib karşılıkları
| Adım | uages | pvlib karşılığı | Not |
|---|---|---|---|
| Güneş konumu | `solar.solar_position` (NOAA) | `pvlib.solarposition.get_solarposition(method="nrel_numpy")` | NOAA ±0,01° düzeyinde yeterli; aralık ortasında hesaplanır |
| Dünya dışı ışınım | `e0n = 1367·(1+0,033·cos(2π·doy/365))` | `pvlib.irradiance.get_extra_radiation` | kt = GHI / G0h, G0h > 50 W/m² iken |
| Transpozisyon | Hay-Davies (`poa_hay_davies`) | `get_total_irradiance(model="haydavies")` | Perez daha isabetli olabilir; GHI→DNI/DHI ayrıştırması kaynaktan geliyor |
| IAM | ASHRAE b0=0,05, yalnız direkt bileşene | `pvlib.iam.ashrae(b=0.05)` | Difüz IAM ihmal (≈%1–2 iyimserlik) |
| Hücre sıcaklığı | Faiman u0=25, u1=6,84 | `pvlib.temperature.faiman` | 10 m rüzgâr kullanılıyor; modül yüksekliğinde rüzgâr daha düşük |
| DC | `mwp·POA_eff/1000·(1+γ(Tc−25))·(1−0,10)` | `pvlib.pvsystem.pvwatts_dc` | γ=−0,0035/°C; kayıplar tek kalem %10 |
| AC | η=0,98, kırpma = MWp/1,2 | `pvlib.inverter.pvwatts` (sabit verimle sadeleştirilmiş) | Kırpma bölge toplamında; gerçekte santral bazında ve daha erken başlar |

Formüller yalnızca Python'dadır; dashboard yeniden hesaplamaz.

## Bilinen fiziksel eksikler (öncelik sırasıyla)
1. **Montaj karışımı.** Tüm filo 30°/güney sabit kabul ediliyor. Ukrayna'da tek eksenli izleyici ve
   farklı eğimler var. Kalibrasyondaki `shape` (0,8–1,25 arası kırpılmış) bu farkı emiyor. Doğru yol: PVGIS
   `seriescalc` ile sabit / tek eksen (`trackingtype=1`) / doğu-batı profillerini üretip GPEE'nin
   açık gün profiline en küçük kareler ile **karışım oranı** fit etmek (oranlar ≥0, toplamı 1).
   Sonra `region_overrides` ya da çoklu dizi desteğiyle modele taşımak.
2. **Modül üstü kar.** Şu an kar yalnızca albedo'yu 0,2→0,6 yapıyor. Kar örtüsü üretimi tamamen
   kesebilir. `pvlib.snow.coverage_nrel` (Marion) ve `pvlib.snow.loss_townsend` yaklaşımları,
   snowfall + sıcaklık + POA ile kar kaybı ve kayarak temizlenmeyi modelliyor. Kış k'sının düşüklüğünü
   ayrıştırmak için önce bu eklenmeli, sonra k yeniden fit edilmeli.
3. **Kirlenme/temizlenme.** Yağışla sıfırlanan, kurak dönemde birikerek artan kayıp
   (`pvlib.soiling.hsu` ya da basit günlük %0,1–0,3 birikme + yağış ≥5 mm'de sıfırlama).
4. **Ayrıştırma.** NWP'den gelen DNI/DHI modelin kendi ayrıştırmasıdır. Yalnız GHI güvenilir olan
   kaynaklarda (uydu, bazı modeller) Erbs/DIRINT/Engerer ile yeniden ayrıştırmayı düşün.
5. **Uzamsal ortalama.** Bölge merkezindeki tek nokta, parçalı bulutlu günlerde bölge ortalamasını
   temsil etmez. Doğrusal olmayan zincirde (kırpma, sıcaklık) "ortalama havanın üretimi" ≠
   "üretimlerin ortalaması". Önce noktaları çoğalt (santral/ızgara), üretimi nokta bazında hesapla, sonra topla.
6. **Arazi ufku.** Karpatlar (bölge 4) için PVGIS `usehorizon=1` ufuk gölgelemesi verir;
   Open-Meteo vermez.

## Parametre değiştirirken
- Fiziksel parametreyi (γ, kayıplar, DC/AC) GPEE'ye uydurmak için değiştirme: k ve kalibrasyon katmanları
  bunu zaten yapıyor ve fiziksel parametreyi oynatmak uzun vadeyi bozar. Fiziksel parametre ancak santral
  verisine (datasheet, montaj) dayanarak değişir.
- Değişiklikten sonra açık günlerde günlük PR_model (`gecmis_gunluk.csv`) 0,75–0,85 aralığında kalmalı;
  dışına çıkıyorsa zincirde birim/ölçek hatası ara.

# Zaman kuralları

Bu projede hatanın en sık kaynağı zaman hizalamasıdır. 1 saatlik kayma hem nMAE'yi şişirir hem de
kalibrasyonun saat şekli katmanı tarafından sessizce emilir (sabah düşük, akşam yüksek katsayı çıkar).
Bu yüzden şekil katsayıları sabah ve akşam saatlerinde simetrik değilse önce kaymadan şüphelen.

## Ortak iç format
- İndeks: `time_utc`, tz-naive, **UTC**, **aralık başı**. Değer, [t, t+1h) aralığının ortalaması.
- Güneş konumu aralık ortasında (t+30 dk) hesaplanır: `solar.interval_solar_position`.
- Yerel saat (`time_local`) yalnızca gruplama (saat şekli, gün toplamı) ve çıktı için türetilir:
  `idx.tz_localize("UTC").tz_convert("Europe/Kyiv").tz_localize(None)`.
- DST: Kyiv yazın UTC+3, kışın UTC+2. 2026'da geçişler 29 Mart ve 25 Ekim. Yerel gün 23 ya da 25
  saattir; yerel saati asla `date_range(freq="h")` ile üretme, UTC'den türet (`gpee.local_hours` örneği).

## Kaynak bazında dönüşüm
| Kaynak | Ham konvansiyon | Dönüşüm (bir kez, kaynak modülünde) |
|---|---|---|
| Open-Meteo saatlik ışınım (`shortwave_radiation` vb.) | Önceki saatin ortalaması, etiket = aralık sonu | −1 saat (`openmeteo._to_frame`) |
| Open-Meteo anlık değişkenler (`temperature_2m`, `wind_speed_10m`, `cloud_cover`) | Etiket anındaki değer | Aynı −1 saat kayması uygulanıyor → sıcaklık aralığın **sonundaki** değerdir. Saatlik PV için ihmal edilebilir; ML özelliği yaparken bil |
| Open-Meteo `*_instant` ışınım | Anlık | Kullanılırsa kaydırma yapılmaz; aralık ortalaması değildir |
| GPEE `loadCharts` | Yerel periyot k=1..n → (k−1):00–k:00 yerel | Aralık başı yerel → UTC (`gpee.fetch_day`) |
| GPEE xlsx v2 | `Datetime_UTC` sütunu zaten aralık başı UTC | Doğrudan |
| PVGIS seriescalc/TMY | `YYYYMMDD:HHMM`, dakika ≈ 10 (SARAH örnekleme zamanı), UTC | `floor("h")` ve aralık başı kabul. Saatlik değil aylık kullanımda güvenli; saatlik kalibrasyonda kullanılacaksa ±30 dk etkisini `best_lag` ile test et |
| ERA5 (Open-Meteo üzerinden) | Open-Meteo konvansiyonu | Open-Meteo ile aynı |
| CAMS Radiation (SoDa) | Aralık ortalaması, zaman damgası seçilebilir (başı/sonu); 15 dk/1 saat | İstekte UTC + aralık başı/sonu belirt, gerekiyorsa kaydır |

## Doğrulama
- Her yeni kaynak ya da birleştirmeden sonra:
  `calibrate.best_lag(actual, model)` → {−2..2: korelasyon}. En yüksek değer 0'da olmalı. 0 ile ±1 farkı
  çok küçükse (<0,002) açık günlerle yeniden bak; bulutlu saatler korelasyonu düzleştirir.
- Gün içi şekil kontrolü: açık günlerde gerçekleşen ve model tepe saatinin aynı yerel saatte olması
  beklenir. Güneş öğlesi Kyiv'de yazın ~12:45–13:10, kışın ~11:45–12:10 yerel saattir.
- DST günlerinde (Mart/Ekim) satır sayısını kontrol et: yerel gün 23/25 saat, UTC'de kopya yok.

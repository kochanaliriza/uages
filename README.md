# UA GES Tahmin — Ukrayna GES üretim analizi ve tahmin altyapısı

GPEE (Garantili Alıcı) saatlik GES gerçekleşen serisini hava verisiyle modelleyip:
1. **Geçmiş performans**: spesifik üretim (kWh/kWp), PR, hava sınıfı ve sıcaklığa göre performans, tahmin doğruluğu
2. **7 günlük saatlik tahmin**: 4 hava modeli + karma + ECMWF ensemble bandı (P10–P90), bölge bazlı hava durumu
3. **Uzun vade (12 ay)**: ERA5 2016–2025 + PVGIS SARAH3 2014–2023 + PVGIS TMY karması, P50/P90
4. **Dashboard** (`outputs/dashboard.html`) ve Excel (TR) uyumlu CSV'ler üretir.

## Hızlı başlangıç
**`CALISTIR.bat`'a çift tıklayın.** Veriler otomatik çekilir (GPEE gerçekleşen, Open-Meteo hava tahmini, ERA5 ve PVGIS),
hesaplar pencerede görünür, bitince panel (`outputs\dashboard.html`) tarayıcıda açılır. CSV'ler `outputs` klasöründedir.
İlk çalıştırmada geçmiş veriler indirildiği için 3–5 dakika sürer, sonraki çalıştırmalar ~1 dakika. İnternet bağlantısı gerekir.

| Dosya | Ne zaman |
|---|---|
| `CALISTIR.bat` | Elle çalıştırma: ilerlemeyi gösterir, paneli açar |
| `hizli_tahmin.bat` | Sadece 7 günlük tahmini yeniler (~10 sn), paneli açar |
| `guncelle.bat` | Sessiz tam güncelleme; zamanlanmış görev için (çıktı `logs\guncelle.log`) |

## Kurulum (bir kez)
```
pip install -r requirements.txt
```
Girdi dosyaları `data/input/` altında (GPEE v2, 8 bölge, kapasite listesi). Yeni sürüm geldiğinde aynı adla değiştirin,
sonra `data/store/gpee_hourly.csv` dosyasını silin (xlsx'ten yeniden kurulur).

## Kullanım
| Komut | Ne yapar | Süre |
|---|---|---|
| `guncelle.bat` / `python -m uages all` | GPEE güncelle + geçmiş analiz + kalibrasyon + 7 gün + 12 ay + dashboard | ~30 sn (önbellekle) |
| `hizli_tahmin.bat` / `python -m uages forecast` | Sadece 7 günlük tahmin + dashboard, sonra paneli açar | ~10 sn |
| `python -m uages history` | GPEE + geçmiş performans + kalibrasyon | |
| `python -m uages longterm` | 12 aylık beklenti | |
| `python -m uages range 2027-01-01 2027-03-31` | İstenen dönem için saatlik tipik beklenti CSV'si | |
| `python -m uages dashboard` | Sadece paneli CSV'lerden yeniden üretir | |
| `python tools/backfill_gpee.py fetch` / `check` / `merge` | GPEE geçmişini (2020-07 → 2025) çeker, kontrol eder, depoya ekler (yedek alarak). Analiz dönemi yine `history.start` | ~90 dk (bir kez) |
| `python tools/fetch_optim_data.py` | Optimizasyon verisi: Open-Meteo Previous Runs (D+1…D+7 arşiv tahmin, 2024→) + uydu SARAH3 (2020→). Ücretsiz limite uyar, kaldığı yerden devam eder | ~2 saat (bir kez) |
| `python -m uages optimize` | Ufka göre kalibrasyon optimizasyonu, önce/sonra raporu (`optimizasyon_raporu.csv`, `kalibrasyon_aday.json`). Hiçbir şeyi devreye almaz | ~1 dk |
| `python tools/check_vector_calib.py` | Optimizasyon çekirdeğinin mevcut kalibrasyonla birebir aynı sonucu verdiğini test eder | ~1,5 dk |

**Otomatik güncelleme (bir kez, kendiniz kurun):** PowerShell'de şu komut `guncelle.bat`'ı 06:10'dan başlayarak 3 saatte bir çalıştırır:
```
schtasks /Create /SC HOURLY /MO 3 /ST 06:10 /TN UA_GES_Tahmin /TR "\"C:\Users\ekrem\Documents\UA_GES_Tahmin\guncelle.bat\"" /F
```
Kaldırmak için: `schtasks /Delete /TN UA_GES_Tahmin /F`. Günlük: `logs/guncelle.log`, hata: `logs/son_hata.txt`.

## Modüller (`uages/`)
| Modül | Görev | Değiştirilebilir |
|---|---|---|
| `config.json` | Tüm parametreler: PV, kaynak ağırlıkları, kalibrasyon pencereleri, CSV biçimi | ✔ |
| `sources/openmeteo.py` | ERA5 arşivi, arşiv best-match, geçmiş tahmin, 16 gün tahmin, ensemble, SEAS5 | yeni model eklemek için `forecast.model_weights` |
| `sources/pvgis.py` | PVGIS TMY ve SARAH3 saatlik seriler (düzlem içi bileşenler) | |
| `gpee.py` | GPEE `loadCharts` ucu, DST'ye dayanıklı saatlik depo güncelleme | |
| `weather.py` | Kaynakları bölge bazında toplar, eksik saatte ağırlığı yeniden normalize eden karma | |
| `solar.py`, `pvmodel.py` | NOAA güneş konumu → Hay-Davies POA → IAM → Faiman → DC → AC | bölgeye özel eğim/azimut: `region_overrides` |
| `calibrate.py` | k + saat şekli + berraklık düzeltmesi, yürüyen pencere doğrulaması | |
| `dataset.py`, `optimize.py` | Ufuk × model eğitim tablosu; vektörel kalibrasyon, ufka göre kalibrasyon, optimizasyon raporu, günlük yenileme | `optimize.GRID`, `TEST_START` |
| `analysis.py` | Geçmiş performans tabloları | |
| `forecast.py` | 7 gün saatlik tahmin + bant + bölge hava | |
| `longterm.py` | Aylık P50/P90 ve saatlik tipik profil | |
| `dashboard.py` + `dashboard_template.html` | Veriyi gömülü tek dosya panel | |

Örnek: bölge 1 tek eksenli izleyiciyse bile yaklaşık etki için eğimi düşürebilirsiniz:
```json
"region_overrides": { "1": { "tilt_deg": 20 } }
```

## Zaman kuralı (kritik)
- Tüm seriler **UTC aralık başı** etiketlidir; değer [t, t+1h) ortalamasıdır.
- Open-Meteo saatlik ışınımı "önceki saat ortalaması"dır → 1 saat geri kaydırılır. Rüzgâr `m/s` istenir (varsayılan km/h).
- GPEE periyot k = Kyiv yerel (k-1):00–k:00; DST günleri 23/25 saat.
- Hizalama her çalışmada korelasyon testiyle kontrol edilir (`model_durumu.json` → `zaman_kaymasi_korelasyon`, en yüksek değer 0'da olmalı).

## Kalibrasyon mantığı
Model santral listesindeki tüm MWp'yi (5.269 MWp) kullanır; GPEE serisi yalnızca yeşil tarife grubunu kapsar.
`k = gerçekleşen / model`. Tahminde: `P = model × k(son 21 gün) × saat_şekli[saat] × kt_faktörü[berraklık sınıfı]`.

İki mod (`config.json` → `calibration.mode`):
- `"mevcut"` (varsayılan): katsayılar Open-Meteo geçmiş tahmini (best_match) ile fit edilir, D+1…D+7'ye aynı katsayı uygulanır.
- `"ufuk"`: her ufuk günü kendi k / saat şekli / kt katsayısını kullanır; katsayılar aynı hava karmasının o ufuktaki
  arşiv tahminlerinden (Previous Runs) fit edilir. Her `history` çalışmasında son 75 günle yenilenir
  (`kalibrasyon_ufuk.json`); dosya yoksa ya da 10 günden eskiyse tahmin otomatik olarak `"mevcut"`a döner.
  Test (2026-05…10): D+1 nMAE %10,5 → %9,3, bias +%6,1 → +%0,6; Haziran'da daha kötü (%7,2 → %8,9).
- `calibration.season_correction` (yalnız ufuk modunda): k'yı kalibrasyon penceresi ile tahmin günü arasındaki
  mevsimsel değişimle ölçekler (k her yıl Ekim→Aralık ~%45 düşer). Eğri `mevsim_k.json`'da; `python -m uages optimize`
  ile ayda bir yenilenir. Örneklem dışı kış testi (2025/26 Kas–Mar): D+1 nMAE %34,0 → %30,9; Nisan–Ekim nötr.
- Panelde "Son 7 gün isabeti" tablosu yöntemleri ve GPEE'yi yan yana gösterir (`son7gun_isabet.csv`).
Uzun vadede aylık k (2026 gözlenen; Eki–Ara için Mar/Şub/Oca simetrisi) ve sabit k_ref iki perspektif olarak verilir.

## Çıktılar (`outputs/`)
`tahmin_7gun_saatlik.csv`, `tahmin_7gun_bolge_saatlik.csv`, `tahmin_7gun_gunluk.csv`, `gecmis_saatlik.csv`, `gecmis_gunluk.csv`,
`gecmis_aylik.csv`, `hava_sinifi_performans.csv`, `sicaklik_performans.csv`, `tahmin_dogrulama.csv`, `kalibrasyon_aylik_k.csv`,
`bolge_aylik_model.csv`, `santral_aylik_model.csv`, `uzun_vade_*.csv`, `model_durumu.json`, `dashboard.html`.

## Bilinen sınırlar
- D+1'de GPEE'nin kendi tahmini daha isabetli (nMAE ~%8 vs ~%11). Model D+2…D+7, şeffaf hava girdisi ve uzun vade içindir.
- Kısıt (curtailment) tahmin edilmez. Kış k'sı düşük ve nedeni (kar / düşük güneş / şebeke) ayrıştırılamıyor.
- 426 yer tutucu faz oblast merkezinde; bölge ağırlıkları kaba. Santral bazlı gerçekleşen üretim kamuya açık değil.
- SEAS5 mevsimsel tahmini ham haliyle yanlı olduğu için kapalı (`longterm.use_seasonal`).

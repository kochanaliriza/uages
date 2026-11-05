# UA GES Tahmin — ülke bazlı GES üretim analizi ve tahmin altyapısı (ilk ülke: Ukrayna)

> **2026-11-05 — ülke adaptörü sürümü.** Kod ülkeden bağımsız hale getirildi; Ukrayna'nın verisi, ayarları ve çıktıları artık
> `countries\UA\` altında, hava önbelleği kökteki `cache\` altında. Sonuçlar değişmedi (altın test: eski kodla 25 çıktı dosyası
> birebir aynı). Eski klasör yapısından geçiş için bir kez `TASIMA.bat` çalıştırın — bkz. **Yükseltme**.

GPEE (Garantili Alıcı) saatlik GES gerçekleşen serisini hava verisiyle modelleyip:
1. **Geçmiş performans**: spesifik üretim (kWh/kWp), PR, hava sınıfı ve sıcaklığa göre performans, tahmin doğruluğu
2. **7 günlük saatlik tahmin**: 4 hava modeli + karma + ECMWF ensemble bandı (P10–P90), bölge bazlı hava durumu
3. **Uzun vade (12 ay)**: ERA5 2016–2025 + PVGIS SARAH3 2014–2023 + PVGIS TMY karması, P50/P90
4. **Dashboard** (`countries/UA/outputs/dashboard.html`) ve Excel (TR) uyumlu CSV'ler üretir.

## Hızlı başlangıç
**`CALISTIR.bat`'a çift tıklayın.** Veriler otomatik çekilir (GPEE gerçekleşen, Open-Meteo hava tahmini, ERA5 ve PVGIS),
hesaplar pencerede görünür, bitince panel (`countries\UA\outputs\dashboard.html`) tarayıcıda açılır. CSV'ler `countries\UA\outputs` klasöründedir.
İlk çalıştırmada geçmiş veriler indirildiği için 3–5 dakika sürer, sonraki çalıştırmalar ~1 dakika. İnternet bağlantısı gerekir.

| Dosya | Ne zaman |
|---|---|
| `CALISTIR.bat` | Elle çalıştırma: ilerlemeyi gösterir, paneli açar |
| `hizli_tahmin.bat` | Sadece 7 günlük tahmini yeniler (~10 sn), paneli açar |
| `guncelle.bat` | Sessiz tam güncelleme; zamanlanmış görev için (çıktı `countries\UA\logs\guncelle.log`) |
| `TASIMA.bat` | Bir kez: eski yapıdan (`data\`, `outputs\`, `logs\`) yeni yapıya geçiş |

## Kurulum (bir kez)
```
pip install -r requirements.txt
```
Girdi dosyaları `countries/UA/data/input/` altında (GPEE v2, 8 bölge, kapasite listesi). Yeni sürüm geldiğinde aynı adla değiştirin,
sonra `countries/UA/data/store/gpee_hourly.csv` dosyasını silin (xlsx'ten yeniden kurulur).

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
| `python tests/golden/run_golden.py` | **Altın test:** kodu, dondurulmuş eski kodla (1 Kasım 2026 girdileri, sabit saat, ağ kapalı) karşılaştırır. Her kod değişikliğinden sonra çalıştırın; `ÖZDEŞ` görmelisiniz | ~2–3 dk |
| `... --ulke XX` / `set UAGES_ULKE=XX` | Başka ülke (adaptörü eklendiğinde). Varsayılan `UA` | |

**Otomatik güncelleme (bir kez, kendiniz kurun):** PowerShell'de şu komut `guncelle.bat`'ı 06:10'dan başlayarak 3 saatte bir çalıştırır:
```
schtasks /Create /SC HOURLY /MO 3 /ST 06:10 /TN UA_GES_Tahmin /TR "\"C:\Users\ekrem\Documents\UA_GES_Tahmin\guncelle.bat\"" /F
```
Kaldırmak için: `schtasks /Delete /TN UA_GES_Tahmin /F`. Günlük: `countries/UA/logs/guncelle.log`, hata: `countries/UA/logs/son_hata.txt`.
Zamanlanmış görev `guncelle.bat`'ı çağırdığı için yükseltmede değiştirilmesi gerekmez.

## Klasör yapısı
```
uages/                     ortak kod (ülke bilmez)
  countries/base.py        ülke adaptörü arayüzü
  countries/ua.py          Ukrayna adaptörü: bölge/santral yükleyicileri, Eki–Ara k aynası, harita sınırı
  countries/ua_gpee.py     GPEE istemcisi ve saatlik depo
countries/UA/
  config.json              Ukrayna ayarları (eski kökteki config.json)
  data/input/  data/store/  data/cache/   girdi xlsx, GPEE deposu, eğitim tablosu + harita sınırı
  outputs/  logs/
cache/openmeteo/  cache/pvgis/            ortak hava önbelleği (tüm ülkeler)
tests/golden/              altın test (dondurulmuş eski kod + 1 Kasım 2026 girdileri)
```

## Yeni ülke eklemek (özet)
1. `uages/countries/<kod>.py`: `CountryAdapter`'dan türeyen sınıf — `load_target` (sözleşme: `time_utc, time_local, actual_mw,
   forecast_mw, flag_curtail_day, flag_curtail_hour, use_for_training`), `update_store`, `init_store`, `load_regions`, `load_plants`;
   isteğe bağlı `monthly_k_mirror`, `map_outline`, `benchmark_label`.
2. `uages/countries/__init__.py` → `REGISTRY`'ye bir satır.
3. `countries/<KOD>/config.json` (`country.adapter`, `local_tz`, `inputs`, `optimize.*` dahil) ve `countries/<KOD>/data/input/`.
4. `python -m uages all --ulke <KOD>`. Sonra `python tests/golden/run_golden.py` — Ukrayna sonuçları değişmemeli.

## Yükseltme (2026-11-05, eski yapıdan)
1. Zamanlanmış görev çalışmıyorken ZIP içeriğini mevcut proje klasörünün (`D:\EnergyPortal\UA_GES_Tahmin`) üzerine açın.
2. `TASIMA.bat`'a çift tıklayın: ne taşınacağını listeler, onay ister, `data\` `outputs\` `logs\` klasörlerini yeni yerlerine taşır
   (aynı disk içinde yeniden adlandırma, kopyalama yok), eski `config.json` ve kod kalıntılarını `_tasima_yedek\` altına alır.
   Geri almak için: `python tools\migrate_to_countries.py --geri-al`.
3. Doğrulama: `python tests\golden\run_golden.py` → `SONUC: OZDES`. Sonra `CALISTIR.bat`.
4. `outputs\dashboard.html` için bir kısayolunuz varsa `countries\UA\outputs\dashboard.html` olarak güncelleyin.

## Modüller (`uages/`)
| Modül | Görev | Değiştirilebilir |
|---|---|---|
| `countries/UA/config.json` | Tüm parametreler: PV, kaynak ağırlıkları, kalibrasyon pencereleri, CSV biçimi, `optimize.*` (test başlangıcı, gecikme, veri başlangıçları) | ✔ |
| `config.py` | Aktif ülke ve yollar (`activate`, `load_config(ulke=)`), `csv_kw`, `rnd` | |
| `countries/` | Ülke adaptörleri (yukarıda) | yeni ülke |
| `sources/openmeteo.py` | ERA5 arşivi, arşiv best-match, geçmiş tahmin, 16 gün tahmin, ensemble, SEAS5 | yeni model eklemek için `forecast.model_weights` |
| `sources/pvgis.py` | PVGIS TMY ve SARAH3 saatlik seriler (düzlem içi bileşenler) | |
| `countries/ua_gpee.py` | GPEE `loadCharts` ucu, DST'ye dayanıklı saatlik depo güncelleme (yalnız UA) | |
| `weather.py` | Kaynakları bölge bazında toplar, eksik saatte ağırlığı yeniden normalize eden karma | |
| `solar.py`, `pvmodel.py` | NOAA güneş konumu → Hay-Davies POA → IAM → Faiman → DC → AC | bölgeye özel eğim/azimut: `region_overrides` |
| `calibrate.py` | k + saat şekli + berraklık düzeltmesi, yürüyen pencere doğrulaması | |
| `dataset.py`, `optimize.py` | Ufuk × model eğitim tablosu; vektörel kalibrasyon, ufka göre kalibrasyon, optimizasyon raporu, günlük yenileme | `optimize.GRID`, config `optimize.test_start` |
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
- `"mevcut"`: katsayılar Open-Meteo geçmiş tahmini (best_match) ile fit edilir, D+1…D+7'ye aynı katsayı uygulanır.
- `"ufuk"`: her ufuk günü kendi k / saat şekli / kt katsayısını kullanır; katsayılar aynı hava karmasının o ufuktaki
  arşiv tahminlerinden (Previous Runs) fit edilir. Her `history` çalışmasında son 75 günle yenilenir
  (`kalibrasyon_ufuk.json`, canlıda bu mod açık); dosya yoksa ya da 10 günden eskiyse tahmin otomatik olarak `"mevcut"`a döner.
  Test (2026-05…10): D+1 nMAE %10,5 → %9,3, bias +%6,1 → +%0,6; Haziran'da daha kötü (%7,2 → %8,9).
- `calibration.season_correction` (yalnız ufuk modunda): k'yı kalibrasyon penceresi ile tahmin günü arasındaki
  mevsimsel değişimle ölçekler (k her yıl Ekim→Aralık ~%45 düşer). Eğri `mevsim_k.json`'da; `python -m uages optimize`
  ile ayda bir yenilenir. Örneklem dışı kış testi (2025/26 Kas–Mar): D+1 nMAE %34,0 → %30,9; Nisan–Ekim nötr.
- Panelde "Son 7 gün isabeti" tablosu yöntemleri ve GPEE'yi yan yana gösterir (`son7gun_isabet.csv`).
Uzun vadede aylık k (2026 gözlenen; Eki–Ara için Mar/Şub/Oca simetrisi) ve sabit k_ref iki perspektif olarak verilir.

## Çıktılar (`countries/UA/outputs/`)
`tahmin_7gun_saatlik.csv`, `tahmin_7gun_bolge_saatlik.csv`, `tahmin_7gun_gunluk.csv`, `gecmis_saatlik.csv`, `gecmis_gunluk.csv`,
`gecmis_aylik.csv`, `hava_sinifi_performans.csv`, `sicaklik_performans.csv`, `tahmin_dogrulama.csv`, `kalibrasyon_aylik_k.csv`,
`bolge_aylik_model.csv`, `santral_aylik_model.csv`, `uzun_vade_*.csv`, `model_durumu.json`, `dashboard.html`.

## Bilinen sınırlar
- D+1'de GPEE'nin kendi tahmini daha isabetli (nMAE ~%8 vs ~%11). Model D+2…D+7, şeffaf hava girdisi ve uzun vade içindir.
- Kısıt (curtailment) tahmin edilmez. Kış k'sı düşük ve nedeni (kar / düşük güneş / şebeke) ayrıştırılamıyor.
- 426 yer tutucu faz oblast merkezinde; bölge ağırlıkları kaba. Santral bazlı gerçekleşen üretim kamuya açık değil.
- SEAS5 mevsimsel tahmini ham haliyle yanlı olduğu için kapalı (`longterm.use_seasonal`).

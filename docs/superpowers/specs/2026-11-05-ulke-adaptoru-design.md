# Ülke adaptörü (Adım 0) — tasarım

Tarih: 2026-11-05 · Durum: onaylandı ve uygulandı (altın test: ÖZDEŞ, 25 çıktı dosyası)

## Amaç
UA_GES_Tahmin kodunu ülkeden bağımsız hale getirmek: ortak hesap çekirdeği + ülke başına adaptör ve klasör.
Bu adım **Ukrayna sonuçlarını değiştirmez**. Başarı ölçütü: altın test (aşağıda) 18 çıktı dosyasında ve
optimizasyon raporunun 360 satırında fark ≤ 1e-9 verir. Macaristan bu adımın kapsamında değildir (Adım 1).

## Kararlar
| Konu | Karar | Gerekçe |
|---|---|---|
| Klasör yapısı | Ortak kod + `countries/<KOD>/` (kullanıcı seçimi, seçenek 1) | Tek kod tabanı, tutarlı yapı |
| Paket adı | `uages` kalır | Yeniden adlandırma kozmetik; BAT ve alışkanlıkları bozar. Sonra ayrıca karar verilir |
| Varsayılan ülke | `UA` | `python -m uages all` ve üç BAT dosyası aynen çalışır |
| Config | Ülke başına tam `config.json` (ortak varsayılan dosyası yok) | YAGNI; ortak varsayılanlar ikinci ülke gelince çıkarılır |
| Hava önbelleği | Kökte ortak `cache/` (openmeteo, pvgis) | Anahtar = URL + parametre (enlem/boylam dahil); ülkeler arası paylaşılabilir |
| Matematik | Dokunulmaz (fizik, kalibrasyon, tahmin, uzun vade, optimizasyon) | Bu adımın tek amacı yapı |

## Hedef klasör yapısı
```
UA_GES_Tahmin/
  CALISTIR.bat  guncelle.bat  hizli_tahmin.bat     (aynen; varsayılan ülke UA)
  uages/                     ortak kod
    countries/__init__.py    adaptör kayıt defteri: get_adapter(kod)
    countries/base.py        CountryAdapter arayüzü
    countries/ua.py          Ukrayna adaptörü (eski gpee.py + inputs.py içeriği)
  countries/UA/
    config.json              eski kök config.json + yeni anahtarlar
    data/input/  data/store/  data/cache/   (egitim_ufuk.pkl, ukraine_outline_v2.json)
    outputs/  logs/
  cache/openmeteo/  cache/pvgis/            ortak hava önbelleği
  tools/                     ülke parametresi alır (varsayılan UA)
  tests/golden/              altın test
  docs/superpowers/specs/    bu belge
```

## Ülke adaptörü arayüzü
```python
class CountryAdapter:
    code: str                 # "UA"
    benchmark_label: str      # "GPEE resmi (D+1)"  (rapor/son7 tablosundaki yöntem adı — aynen kalmalı)
    def load_regions(cfg) -> DataFrame       # region, lat, lon, mw, mwp, weight (+ ülkeye özel ek sütunlar)
    def load_plants(cfg) -> DataFrame
    def init_store(cfg, overwrite=False) -> DataFrame
    def update_store(cfg, verbose=False) -> DataFrame
    def load_target(cfg) -> DataFrame        # time_utc, time_local, actual_mw, forecast_mw,
                                             # flag_curtail_day, flag_curtail_hour, use_for_training
    def monthly_k_mirror() -> dict[int, int] # UA: {10: 3, 11: 2, 12: 1}
    def map_outline() -> dict | None         # dashboard harita sınırı
```
Saat dilimi `config.local_tz`'de kalır. Hedef sütun adları (`actual_mw`, `forecast_mw` …) ortak sözleşmedir;
UA'da `forecast_mw` = GPEE D+1, ileride TSO D+1.

## Config'e taşınan sabitler (UA değerleri = bugünkü değerler)
| Sabit | Şimdiki yer | Yeni anahtar |
|---|---|---|
| `TEST_START = 2026-05-01` | optimize.py | `optimize.test_start` |
| `LAG = 2` | optimize.py | `optimize.lag_days` |
| `PR_START = 2024-01-01` | dataset.py | `optimize.prev_runs_start` |
| `SAT_START = 2020-07-01` | dataset.py | `optimize.satellite_start` |
| CSV `;` `,` utf-8-sig (sabit) | optimize.py | mevcut `csv` bloğu kullanılır |
| — | — | `country.code = "UA"`, `country.adapter = "ua"` |

## Yollar
`config.PATHS` bugün import anında sabitleniyor ve modüller (`OUT_JSON`, `GPEE_STORE`, `CACHE`, `TABLE` …) bunu
modül düzeyinde kullanıyor. Yeni: `config.activate(ulke)` aktif ülkenin yollarını kurar; modül sabitleri
fonksiyona (ör. `out_path("kalibrasyon_ufuk.json")`) dönüşür. `load_config(ulke)` önce `activate` çağırır.

## CLI
`python -m uages <komut> [--ulke UA]`. `UAGES_ULKE` ortam değişkeni de okunur; ikisi yoksa `UA`.
Komutlar ve çıktı adları değişmez.

## Altın test (güvenlik ağı)
- `tests/golden/onbellek/`: altın çalıştırmanın okuduğu önbellek dosyalarının anlık kopyası (çalıştırma sırasında
  okunan dosyalar kaydedilerek seçilir) + `gpee_hourly.csv`, `mevsim_k.json`, `kalibrasyon_ufuk.json` girdileri.
  Gerekçe: canlı önbellekteki 7 günlük tahmin dosyaları tarihsiz anahtarlı ve her çalışmada üzerine yazılıyor.
- `tests/golden/beklenen/`: 1 Kasım 2026 çalışmasının 18 CSV'si + `optimizasyon_raporu.csv` (orijinal paket).
- `python tests/golden/run_golden.py`: geçici klasöre kopyalar, saati `2026-11-01 15:22 UTC`'ye sabitler,
  çevrimdışı `history` → `forecast` → `longterm` → `optimize` çalıştırır, eğitim tablosunu önbellekten
  `end = 2026-10-31` ile yeniden kurar, her dosyayı karşılaştırır (sayısal ≤ 1e-9, metin birebir), özet basar.
- Refactor öncesi koda karşı geçmesi ön koşuldur (2026-11-05'te elle doğrulandı: maks fark 3e-14).

## Ek temizlik (yalnızca altın test 0 fark verirse)
- Tekrarlı hata metriği (`analysis.metrics`, `optimize.metrics`) ve kısıt bayrağı (`calibrate.flag_curtailment`,
  `optimize.curtail_flag`): ortak modüle; sonuç değişirse birleştirilmez, not düşülür.
- `.round()` uyarıları: yuvarlama yalnızca sayısal sütunlara uygulanır (çıktı aynı).
- BAT dosyaları: `PY` yolu korunur; çalışma klasörü `D:\EnergyPortal\UA_GES_Tahmin` olduğu için yol denemesi aynı kalır.

## Kapsam dışı
Macaristan/ENTSO-E adaptörü, paket adı değişikliği, ortak config varsayılanları, dashboard'un çok ülkeli hali,
herhangi bir model/kalibrasyon iyileştirmesi.

## Geçiş (kullanıcının makinesi)
Teslim: yeni yapıdaki proje ZIP'i (veri hariç) + `tools/migrate_to_countries.py` (mevcut `data/` ve `outputs/`
klasörlerini `countries/UA/` ve `cache/` altına taşır, önce yedek alır). Zamanlanmış görev BAT dosyasını
çağırdığı için değişmez; `outputs\dashboard.html` kısayolu varsa `countries\UA\outputs\` olarak güncellenmeli.

## Riskler
| Risk | Önlem |
|---|---|
| Altın önbellek anlık kopyası büyük olabilir | Yalnızca okunan dosyalar alınır; boyut raporlanır |
| pyarrow ile kaydedilmiş `egitim_ufuk.pkl` | Test tabloyu önbellekten yeniden kurar; canlı dosyaya dokunmaz |
| Kullanıcı makinesinde taşıma hatası | Taşıma aracı önce yedek alır, `--geri-al` seçeneği |

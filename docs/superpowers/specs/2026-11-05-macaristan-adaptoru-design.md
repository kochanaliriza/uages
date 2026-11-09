# Macaristan adaptörü (Adım 1b) — tasarım

Tarih: 2026-11-05 · Durum: onaylandı (kullanıcı: hedef = ENTSO-E sayaçlı gerçekleşen; 8 nokta ile başla, 15 ile sonra karşılaştır)

## Hedef ve kıyas
- Hedef: ENTSO-E A75/A16 B16 (Macaristan sayaçlı GES gerçekleşeni), 15 dk → saatlik ortalama MW, UTC aralık başı.
  Envanter (2026-11-05): 2019-09-22'den beri, eksik saat %0, pik 4,45 GW. Çatı (HMKE) sistemleri dahil değil
  (ENTSO-E A68 kurulu güç 2025'te 4,0 → 8,3 GW kırılması; üretim yalnız %20 arttı).
- Kıyas: ENTSO-E A69/A01 (MAVIR gün öncesi), etiket "MAVIR resmi (D+1)". 2026 nMAE %12,1 (tüm gündüz saatleri).
  Gün içi (A69/A40) %8,7 — D-1'de elde değil, yalnız referans.

## Kapasite ve hava noktaları
- Kaynak: GEM Global Solar Power Tracker (Şubat 2026), Macaristan çalışan ≥1 MW: 795 santral, 4.061 MW, %99 kesin koordinat.
  ENTSO-E 2024 kurulu gücü (4.029 MW, tanım değişikliğinden önce) ile örtüşüyor.
- MWp: MWp/dc olduğu gibi; MWac ve bilinmeyen × 1,2 (config pv.dc_ac_ratio).
- 8 bölge: kapasite ağırlıklı k-ortalama (koordinatlar km'ye ölçeklenmiş), hava noktası = bölgenin kapasite ağırlık merkezi.
  `tools/hu_girdi_hazirla.py` → `countries/HU/data/input/HU_PV_BOLGELER.csv`, `HU_PV_SANTRALLER.csv`.
- Sonra (ayrı deney): 15 noktalı ızgara ve A (OSM) / C (veriden öğrenilen ağırlık) ile karşılaştırma.

## Adaptör (`uages/countries/hu.py`)
- Depo: `countries/HU/data/store/hedef_saatlik.csv`, hedef sözleşmesi (actual_mw, forecast_mw = MAVIR D+1, bayraklar False).
  İlk kurulum 2019-09-01'den; güncelleme son gerçekleşenden 3 gün geri → yarın (MAVIR D+1 tahmini dahil).
- ENTSO-E istemcisi ortak koda: `uages/sources/entsoe.py` (envanter aracı da onu kullanır). Token `entsoe_token.txt`.
- `local_tz` Europe/Budapest, `optimize.lag_days` 1, `prev_runs_start` 2024-01-01, `satellite_start` 2024-01-01,
  `history.start` 2025-01-01 (tüm aylar gözlenir → k aynası gerekmez), Eki–Ara aynası yok.
- Harita: world-atlas id 348. Panel metinleri adaptörden (GPEE→MAVIR, Ukrayna→Macaristan, Kyiv→Budapeşte; Ukrayna'ya özgü notlar gizlenir).

## Ortak koda dokunuşlar (Ukrayna sonucu değişmemeli — altın test ÖZDEŞ)
- `analysis`: santral tablosunda ülkeye özgü sütunlar (Placeholder/Frontline) yalnız varsa.
- Harita sınırı çıkarımı adaptör tabanına (ortak yardımcı); UA önbellek dosyası aynı.

## Test
- Ukrayna: `tests/golden/run_golden.py` → ÖZDEŞ.
- Macaristan: sahte ENTSO-E + sahte Open-Meteo ile uçtan uca duman testi (`tests/hu_duman_testi.py`): history, forecast,
  longterm, optimize, dashboard çalışır; çıktı sütunları ve zaman kuralı (UTC aralık başı, DST) kontrol edilir.

## Kullanıcı adımları
1. `HU_ARSIV_INDIR.bat` (Open-Meteo Previous Runs + uydu, 8 nokta, ~1 gün limit) — bir kez.
2. `CALISTIR_HU.bat` (history + forecast + longterm + dashboard), sonra `python -m uages optimize --ulke HU` → MAVIR'e karşı rapor.

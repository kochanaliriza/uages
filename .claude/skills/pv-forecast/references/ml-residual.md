# ML artık model kuralları

## Hedef ve yapı
- Taban: fizik modeli + MOS-lite (ya da yalnız fizik × k). ML iki biçimden birini öğrenir:
  - Oran: `y = gerçekleşen / (k · model)`, gündüz ve model > eşik saatlerinde. Kapasite değişimine dayanıklıdır.
  - Artık: `y = gerçekleşen − taban`. Kapasiteyle ölçeklenen hatalarda zayıftır, kapasiteye normalize et.
- Tahmin: `taban × f̂` (ya da `taban + r̂`), sonra [0, AC kapasitesi] aralığına kırp; gece = gece tüketimi.
- Model: LightGBM (hızlı, eksik değer toleransı, monotonik kısıt desteği). Olasılıksal çıktı için
  `objective="quantile"` ile q = 0,1 / 0,5 / 0,9 ya da konformal kalibrasyon.

## Özellikler (önerilen başlangıç seti)
| Grup | Özellikler |
|---|---|
| Geometri | güneş yüksekliği, azimut, cos(AOI), yerel saat (sin/cos), yılın günü (sin/cos) |
| Işınım | kt (NWP), POA/G0, modeller arası GHI yayılımı (std/ortalama), ensemble P90−P10 genişliği |
| Bulut | `cloud_cover_low/mid/high`, toplam bulut |
| Sıcaklık/rüzgâr | T2m, Tcell, rüzgâr |
| Kar/kirlenme | kar derinliği, son 48 saatte kar yağışı, son yağıştan beri gün sayısı |
| Ufuk | lead (saat ya da gün) — **eğitim verisi de aynı ufkun tahminleri olmalı** (Previous Runs) |
| Takvim | hafta sonu/tatil (kısıt riski); piyasa fiyatı varsa gün öncesi fiyatı |

Sızıntı yapan özellikler: gerçekleşen hava, aynı günün gerçekleşen üretimi, gelecekte bilinen kısıt
bayrakları, tüm veri üzerinden hesaplanmış normalizasyon istatistikleri. Hepsi yasak.

## Eğitim ve doğrulama
- Zaman bazlı genişleyen pencere ya da aylık bloklar. `sklearn.model_selection.TimeSeriesSplit`
  aralarına en az 2 günlük boşluk (`gap`) koyarak.
- Hiperparametre: az ağaç ve sığ derinlik ile başla (`num_leaves` 15–31, `min_data_in_leaf` ≥ 50,
  `learning_rate` 0,03–0,05, erken durdurma). Veri birkaç bin gündüz saati düzeyindeyken karmaşık model
  ezber yapar.
- Monotonik kısıt: kt ve POA/G0 üzerinde artan (+1). Fiziksel olarak tutarsız tahminleri önler.
- Değerlendirme `calibration-validation.md` protokolüyle; ML'in MOS-lite'ı ufka göre ve hava sınıfına göre
  geçtiği gösterilmeden üretime alınmaz.
- Özellik önemi için SHAP ya da permutation importance. Geometri özellikleri baskınsa fizik modelinde
  sistematik bir eksik vardır (ör. montaj karışımı); önce onu düzelt.

## Üretime alma
- Model dosyası ve özellik listesi sürümlenir (`countries/<KOD>/data/models/<tarih>/`). Eğitim dönemi ve metrikler yanına yazılır.
- ML çıktısı yoksa ya da özellik eksikse tahmin MOS-lite'a düşer (fallback), bu durum loglanır.
- Uzun vadede (longterm) ML kullanılmaz: ML'in gördüğü dağılımın dışındadır.
- Yeni bağımlılık (lightgbm, scikit-learn) `requirements.txt`'e eklenir. Ortam Windows. `.bat` dosyaları Python 3.14
  yolunu deniyor, bu makinede ise PATH'teki `python` (3.12) çalışıyor. İkisinde de tekerlek (wheel) uyumluluğunu kontrol et.

---
name: pv-forecast
description: Ukrayna ülke geneli GES (güneş santrali) saatlik üretim tahmini projesinin (uages paketi) alan bilgisi ve mühendislik kuralları — zaman etiketleme, PV fizik zinciri, NWP/ışınım veri kaynakları (Open-Meteo, PVGIS, ERA5, CAMS), GPEE hedef serisi, kalibrasyon, tahmin doğrulama metrikleri ve ML artık model kuralları. Bu projede tahmin, kalibrasyon, hava/ışınım verisi çekme, model doğruluğu, nMAE/RMSE, P10/P90 bandı, kısıt (curtailment), kar, kapasite, ufka göre (D+1…D+7) hata, uzun vade P50/P90, PVGIS, Open-Meteo, LightGBM veya veri seti genişletme ile ilgili HER istekte kullan — kullanıcı "skill" demese bile; uages/ altındaki herhangi bir dosyaya dokunmadan önce de yükle. Also use for any solar PV power forecasting, irradiance data, or forecast verification work in this repo.
---

# PV tahmin (UA GES) — çalışma kuralları

Bu proje, GPEE'nin (Garantili Alıcı) yayımladığı Ukrayna yeşil tarife GES grubunun saatlik
gerçekleşen üretimini, fizik tabanlı PV modeli + istatistiksel kalibrasyonla tahmin eder.
Amaç sadece "kod çalışsın" değil; **tahmin hatası dürüstçe ölçülsün ve sızıntısız iyileşsin**.
Aşağıdaki kurallar geçmişte zaman kayması, veri sızıntısı ve yanıltıcı metrik hatalarından çıkmıştır.

## Önce oku (ihtiyaca göre)
| Konu | Dosya | Ne zaman |
|---|---|---|
| Zaman etiketleri, DST, kaydırmalar | `references/time-conventions.md` | Her yeni veri kaynağında, her birleştirmede (join) |
| PV fizik zinciri, parametreler, pvlib eşleşmesi | `references/pv-physics.md` | `solar.py`, `pvmodel.py`, montaj/kar/izleyici değişikliği |
| Veri kaynakları: uçlar, kapsam, limitler | `references/data-sources.md` | Yeni veri çekerken, veri setini genişletirken |
| Kalibrasyon ve doğrulama protokolü, metrikler | `references/calibration-validation.md` | Kalibrasyon, metrik raporlama, model kıyaslama |
| ML artık model (LightGBM/quantile) kuralları | `references/ml-residual.md` | Fizik modelinin üstüne ML eklerken |
| Ukrayna/GPEE bağlamı: kısıt, kapasite, savaş | `references/ukraine-context.md` | Hedef serisini yorumlarken, anomali ararken |

Doğrulama metriklerini elle yeniden yazma: `scripts/forecast_metrics.py` ufka göre nMAE/nRMSE/bias,
skill score ve pinball loss hesaplar (kullanım: dosyanın başındaki docstring).

## Mimari özet (kodu okumadan önce zihinsel harita)
```
GPEE saatlik (hedef)  ─┐
Hava (bölge noktası) ──┼→ solar.py (NOAA konum, Hay-Davies POA, IAM)
                       │   → pvmodel.py (Faiman Tcell → DC → AC kırpma)  = model_mw (liste MWp)
                       └→ calibrate.py: P = model × k × şekil[yerel saat] × kt_faktörü[kt sınıfı]
forecast.py: 4 NWP karması + ECMWF ensemble bandı   longterm.py: ERA5 + PVGIS SARAH3 + TMY
dataset.py: Previous Runs (D+1..7 × model) + uydu → eğitim tablosu   optimize.py: vektörel kalibrasyon (Prep),
  ufka göre kalibrasyon, optimizasyon raporu, günlük yenileme (refresh → kalibrasyon_ufuk.json, son7gun_isabet.csv)
```
`calibration.mode`: `"mevcut"` (varsayılan) | `"ufuk"`. Kalibrasyon matematiğini değiştirirsen `optimize.py` ile
`calibrate.py` aynı kalmalı: `python tools/check_vector_calib.py` maks fark 0 MW vermeli.
Ayarlar `config.json`'da; kodda sabit parametre ekleme, config'e koy. Dashboard (`dashboard.py` +
`dashboard_template.html`) hesap yapmaz, yalnızca `outputs/` CSV'lerini ve `model_durumu.json`'u gömüp gösterir;
paneldeki tüm saatler Kyiv saatidir (tarayıcı saat dilimi kullanılmaz).

## Değişmez kurallar ve nedenleri

1. **Tüm saatlik seriler UTC, aralık başı etiketli; değer [t, t+1h) ortalaması.** Kaynaklar farklı
   konvansiyon kullanır (Open-Meteo aralık sonu, GPEE yerel saat periyodu k = (k-1):00–k:00, PVGIS HH:10).
   Dönüşümü kaynak modülünde bir kez yap, başka yerde tekrar kaydırma. Her yeni kaynakta
   `calibrate.best_lag` ile korelasyon tepe noktasının lag=0'da olduğunu doğrula — 1 saatlik kayma
   nMAE'yi birkaç puan şişirir ve kalibrasyonun "saat şekli" katmanı bunu sessizce emerek gizler.

2. **Sızıntı yok.** Kalibrasyon ve ML eğitimi, tahmin anında gerçekten mevcut olan veriyle yapılır:
   GPEE gerçekleşeni ~D+1/D+2 yayımlandığı için `lag_days=2` gecikmesi korunur; geçmiş tahmin
   doğrulamasında gerçekleşen hava (ERA5) asla girdi olmaz. Rastgele train/test bölmesi yapma —
   saatler otokorelasyonludur; zaman bazlı yürüyen (walk-forward) ya da blok bölme kullan.

3. **Eğitim verisi ile kullanım verisi aynı türde olmalı.** Kalibrasyonu hangi NWP ürünü ve hangi
   ufukla fit ettiysen, tahminde aynısına uygula. Best_match geçmiş tahminle fit edilip 4-model karmasına
   D+7'ye kadar uygulanan katsayılar bilinen bir zayıflıktır; ufka bağlı kalibrasyon (Previous Runs API)
   bunun doğru çözümüdür.

4. **Metrikleri her zaman ufka göre, gündüz ve kısıtsız saatlerde, aynı normalizasyonla raporla.**
   nMAE paydası (ortalama gündüz gerçekleşen ya da kurulu güç) metin içinde açıkça yazılsın. Her yeni
   yöntem en az iki referansla kıyaslanır: GPEE'nin kendi D+1 tahmini ve mevcut MOS-lite. Kalibrasyondan
   sonra bias ≈ 0 olmalı; değilse önce onu açıkla.

5. **Kısıtlı (curtailment) saatler eğitimden çıkarılır ama tahminden çıkarılmaz.** Kısıt bayrakları
   (`flag_curtail_*`) eğitim maskesindedir; doğrulamayı hem kısıtsız hem tüm saatler için ayrı ayrı göster,
   çünkü kullanıcı gerçekte tüm saatleri tahmin etmek zorunda.

6. **Kapasite durağan değil.** k; kapsam (yeşil tarife grubu ⊂ liste), erişilebilirlik, savaş hasarı,
   kar, kirlenme ve liste hatalarının toplamıdır. Çok yıllı veriyle çalışırken sabit k yerine zamanla değişen
   etkin kapasite kullan; yıllar arası k farkını "model iyileşti/kötüleşti" diye yorumlama.

7. **Eksik veri sıfır değildir.** NaN ışınım NaN üretim kalmalı (kod bilinçli olarak böyle). Bir bölge
   eksikse filo toplamı NaN olur; sessizce `fillna(0)` yapma — o saat düşük üretim gibi görünür ve k'yı bozar.

8. **P10/P90 adlandırmasını açık yaz.** Kısa vadede `tahmin_p10` = düşük değer (aşılmama %10);
   uzun vadede `p90` = düşük değer (aşılma %90, enerji sektörü konvansiyonu). Yeni çıktıda hangisi
   olduğunu sütun adında ya da açıklamasında belirt.

9. **Fizik ile ML'i karıştırma, katmanla.** Fizik modeli taban kalır; ML yalnızca artığı (ya da oranı)
   öğrenir. Böylece ML çökse/yetersiz veriyle eğitilse bile tahmin fiziksel olarak makul kalır ve
   uzun vade (ML'in görmediği iklim) etkilenmez. Ayrıntı: `references/ml-residual.md`.

10. **Önbellek ve API nezaketi.** Arşiv yanıtları kalıcı önbelleklenir (`data/cache/`); yeni çekim
    yazarken `_get` yardımcılarını kullan, toplu çekimi tarih parçalarına böl, 429'da bekle.
    Open-Meteo ücretsiz katmanı ticari olmayan kullanım içindir ve günlük istek limiti vardır.

## Değişiklik yaparken iş akışı
1. İlgili referans dosyasını oku; değişecek modülün docstring'indeki zaman/birim kuralını kontrol et.
2. Değişikliği küçük tut; `config.json`'a yeni parametre ekliyorsan varsayılanı mevcut davranışı korusun.
3. `python -m uages history` (ya da ilgili komut) çalıştır; `outputs/model_durumu.json` içinde
   `zaman_kaymasi_korelasyon` tepe noktası 0'da mı, `tahmin_dogrulama.csv` önce/sonra nasıl — kıyasla.
4. Sonucu raporlarken: hangi dönem, kaç saat, hangi maske, hangi normalizasyon, hangi referansa göre.
   İyileşme küçükse (≲0,3 puan nMAE) gürültü olabileceğini söyle; mümkünse aylara göre tutarlılığa bak.
5. Çıktı CSV'sinde sütun adı değiştirirsen `dashboard_template.html`'de o sütunu okuyan yeri de güncelle
   (panel sütunları adla okur; eksik sütun sessizce boş grafik verir).

## Rapor biçimi (model kıyası)
```
Dönem: 2026-02-15 … 2026-09-26 (yürüyen, lag=2 gün) · maske: elev>0, kısıtsız · norm: ort. gündüz gerçekleşen
| Yöntem | Ufuk | n_saat | nMAE % | nRMSE % | Bias % | Skill vs GPEE |
```

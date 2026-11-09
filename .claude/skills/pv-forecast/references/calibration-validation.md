# Kalibrasyon ve doğrulama protokolü

## Mevcut kalibrasyon (MOS-lite, `calibrate.py`)
`P = model_mw × k × şekil[yerel saat] × kt_faktörü[kt sınıfı]`, gece (elev < −3°) = gece net tüketim medyanı.
- k: son 21 günün Σgerçekleşen / Σmodel oranı (2 gün gecikmeli).
- şekil: 45 gün, yerel saat bazında kalan oran, n/(n+20) ile 1'e büzülmüş, [0,8; 1,25] kırpılmış.
- kt_faktörü: 7 kt sınıfı (sınırlar 0 / 0,2 / 0,35 / 0,5 / 0,6 / 0,7 / 0,8), n/(n+30) ile büzülmüş, [0,6; 1,3] kırpılmış.
- Eğitim maskesi: model > 50 MW, gerçekleşen var, kısıt bayrakları yok, `use_for_training`.

Katman eklerken aynı deseni koru: sızıntısız pencere, n'e göre büzme, kırpma, `fit`/`apply` ayrımı.
Katsayılar `model_durumu.json` → `calib`'e yazılır; `cli.cmd_forecast` ve dashboard bu şemayı okur, bozma.

## Doğrulama protokolü
1. **Bölme:** Yürüyen pencere (her gün D için yalnız D − lag ve öncesiyle fit). ML'de genişleyen pencere
   ya da aylık bloklar. Hiperparametre seçimi, test dönemine dokunmadan iç doğrulamada yapılır.
2. **Maske:** Varsayılan raporda güneş yüksekliği > 0, kısıtsız saatler. Ek olarak tüm gündüz saatleri.
   Gece saatleri hiçbir zaman nMAE'ye girmez (sabit tüketim metriği yapay olarak iyileştirir).
3. **Normalizasyon:** nMAE = MAE / ortalama gündüz gerçekleşen (mevcut kod). Kurulu güce göre
   normalizasyon (sektörde yaygın) ayrıca verilebilir, ama hangisi olduğu her raporda yazılır.
4. **Ufuk:** D+1 … D+7 ayrı ayrı. Ufuk tanımı: yayın zamanı (Kyiv) ile hedef gün arasındaki gün farkı.
   GPEE'nin D+1 tahmini yalnız D+1'de kıyas noktasıdır.
5. **Kıyas noktaları:** (a) GPEE resmi tahmini, (b) mevcut MOS-lite, (c) basit referans (persistence ya da
   açık gök × klimatolojik kt). Skill score = 1 − RMSE_yöntem / RMSE_referans.
6. **Kırılımlar:** Ay, hava sınıfı (açık/parçalı/kapalı), saat. Ortalamada iyileşme olup kapalı günlerde
   kötüleşme varsa bunu raporla.
7. **Olasılıksal:** P10/P90 kapsama oranı (hedef ~%80 içeride), pinball loss (q = 0,1 / 0,5 / 0,9),
   mümkünse CRPS. Bandın genişliğini ve kapsamasını birlikte raporla: dar ama kapsaması düşük band kötüdür.
8. **Anlamlılık:** Günlük hata farkı serisine Diebold-Mariano testi ya da günlere göre blok bootstrap.
   ~0,3 puandan küçük nMAE farkını tek dönemle "iyileşme" diye sunma.

Hesap için: `scripts/forecast_metrics.py`.

## Bilinen sonuçlar (optimizasyon, 2026-11-01)
Test 2026-05-01…10-28, gündüz kısıtsız, ~2.200 saat/ufuk:
- Kazancın neredeyse tamamı **ufka göre kalibrasyondan** (her ufku kendi tahmin serisiyle fit etmek): D+1 %10,5→%9,3,
  bias +%6,1→+%0,6. Ağırlık optimizasyonu ve ayar araması (240 kombinasyon) testte ≤0,4 puan: gürültü.
- Zayıflıklar: Haziran'da −%5–6 bias (hipotez: Mayıs'ta bayraklanmamış kısıt k'yı düşürüyor); Eylül–Ekim'de
  +%4–7 (k mevsimsel düşerken gecikmeli k).
- **Mevsimsel k** (`season_correction`): k her yıl Haz–Ağu ~0,95 → Kas ~0,6 → Ara ~0,45 düşüyor (2024, 2025 aynı desen).
  Ortak (ufuklar havuzlanmış) harmonik eğri, örneklem dışı 2025/26 kışında D+1 nMAE %34,0→%30,9, D+7 %55,6→%49,8;
  Nis–Eki nötr. Ufuk başına ayrı eğri aynı kazanç, daha riskli (en kötü ay +6 puan); uydu kaynaklı eğri yarı kazanç.
  Haziran 2026 sorununu çözmüyor (o yıla özgü Nisan–Mayıs düşüşü). Kış hatası yine %30–55: kar modeli asıl kaldıraç.
- Aylık "hiçbir ay >0,3 kötüleşmesin" ölçütü pratikte her yöntemde ~%25–30 ay-ufukta ihlal ediliyor (aylık gürültü);
  mevsim ortalamaları (Kas–Mar / Nis–Eki) ve son 7 gün daha anlamlı karar ölçütü.
- Konformal bant (seçim döneminden) testte %88–95 kapsadı (hedef %80): mevsime göre ayrılmalı.
- Gerçekleşen hava: uydu SARAH3, ERA5/arşiv karmasından biraz iyi (korelasyon 0,942 / 0,936).

## Sık yapılan hatalar
- Eğitim ve test aynı günleri içeriyor (rastgele bölme) → metrik %20–40 iyimser çıkar.
- Gerçekleşen hava (ERA5) ile çalıştırılan modelin hatası "tahmin hatası" olarak raporlanıyor. Bu yalnız
  modelin fiziksel kalitesini gösterir (üst sınır), tahmin isabetini değil.
- Kısıtlı saatler maskeden çıkarılıp, bunun etkisi söylenmeden GPEE ile kıyaslanıyor.
- Kalibrasyon sonrası kalan bias'ı açıklamadan nMAE raporlamak.
- Farklı dönemlerdeki iki yöntemi kıyaslamak (kesişen saatlerde kıyasla).

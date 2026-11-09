# Ukrayna / GPEE bağlamı

## Hedef serisi ne ölçüyor
- GPEE (ДП «Гарантований покупець», Garantili Alıcı), yeşil tarifeden (feed-in) yararlanan üreticilerin
  enerjisini satın alır ve dengeleme grubunu yönetir. Seri bu grubun **net** GES üretimidir.
  Gece değeri negatiftir (öz tüketim, yaklaşık −9…−12 MW).
- Grup üyeliği zamanla değişir: tarifeden çıkan ve piyasaya geçen santraller, yeni katılımlar,
  savaş nedeniyle bağlantısı kesilen santraller. Bu yüzden sabit bir "kurulu güç" yoktur. k bunu temsil eder.
- Model evreni (`UA_PV_CAPACITY_CLEAN_2026_v2.xlsx`, 8 bölge, ~5.269 MWp) grubun kendisi değil,
  tahmin evrenidir. k ≈ 0,5–0,7 gibi değerler kapsam farkından gelir, model hatası değildir.

## Kısıt (curtailment)
- Ukrenergo, sistem dengesi için özellikle ilkbahar ve yaz öğlelerinde, düşük talepli hafta sonu ve
  tatillerde GES üretimini kısıtlayabilir. Savaş döneminde şebeke hasarı da yerel kısıtlar yaratır.
- İz: açık gün profilinde öğlen düzleşmesi ya da ani düşüş. GPEE'nin kendi tahmini de kısıtı bilmez.
- Kodda iki bayrak var: xlsx v2'den gelen elle işaretlenmiş bayraklar (`flag_curtail_day/hour`) ve
  modelden türetilen `flag_curtail_model`.
- Kısıt tahmini için öncü göstergeler: gün öncesi piyasa fiyatı (OREE), talep, tatil/hafta sonu,
  açık hava ile yüksek beklenen üretimin birlikte olması.

## Savaş etkisi
- Güney ve doğudaki kapasitenin bir kısmı işgal altında ya da cephe hattına yakın
  (bölge tablosunda `Frontline_MW`; bölge 1'de 545 MW). Bu santrallerin üretimi kesintili ya da sıfır olabilir.
- Şebekeye yönelik saldırılar (özellikle 2022–2025 kışları) ani ve geniş kesintilere yol açtı.
  Bu günler model hatası değildir; eğitimde dışla ve ayrı etiketle.
- Yer tutucu fazlar (`Placeholder_Flag`, ~426 faz) oblast merkezinde duruyor. Konumları gerçek değil,
  bu yüzden mekânsal analizde ağırlıklarını düşük tut.

## Mevsimsellik
- Kış: düşük güneş, kar, sis. k belirgin düşer ve nedeni ayrıştırılamıyor (kar, kapsam ya da şebeke).
  Gözlenmemiş (≥15 gün verisi olmayan) Ekim–Aralık ayları için kodda Mar/Şub/Oca aynası kullanılıyor
  (`calibrate.monthly_k`, geçici çözüm). Çok yıllı GPEE verisi gelince kaldırılmalı.
- İlkbahar: en yüksek kısıt riski (yüksek ışınım, düşük talep, ılık sıcaklık).
- Yaz: sıcaklık kaybı belirgin. Açık günlerde PR düşer.

## Yorumlama kuralları
- "Model bu ay kötü" demeden önce: kısıt saati sayısı, kar günleri, veri eksikliği ve k değişimine bak.
- GPEE tahmininden kötü olmak D+1'de beklenen bir durum (README: ~%8'e karşı ~%11). Modelin değeri D+2…D+7,
  şeffaf hava girdisi ve uzun vadededir.

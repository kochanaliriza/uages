# UA GES Tahmin — Sürüm ve Deney Geçmişi (tekerrür önleme kaydı)

Amaç: Denenmiş yöntemleri, sonuçlarını ve devreye alınma kararlarını tek yerde tutmak. Yeni bir iyileştirme
önermeden önce bu dosyaya bakılır; burada "denendi / etkisiz" yazan bir şey, **neyin farklı olacağı**
açıkça söylenmeden tekrar denenmez.

Kaynaklar: `docs/yapilan_gelistirmeler_2026-11-03.pdf` (31 Eki – 3 Kas 2026 çalışma raporu), `outputs/optimizasyon_raporu.csv`,
`logs/*.log`, `.claude/skills/pv-forecast/references/calibration-validation.md`. Son güncelleme: 2026-11-05.

## Ölçüm sözleşmesi (bütün rakamlar için)
- nMAE = saatlik MAE / ortalama gündüz gerçekleşen (elev > 0), **kısıtsız** saatler (aksi belirtilmedikçe).
- Seçim dönemi 2024-01-01 … 2026-04-30; test 2026-05-01 … 2026-10-28 (~2.200 gündüz saati / ufuk). Test, ayar
  seçiminde hiç kullanılmadı. Kalibrasyon gecikmesi LAG = 2 gün (GPEE gerçekleşeni geç yayımlıyor).
- Hedef: GPEE yeşil tarife grubunun net GES üretimi; model evreni 5.269 MWp (8 bölge). k = gerçekleşen / model.
- ~0,3 puandan küçük nMAE farkı gürültü kabul edilir.

## Sürümler

| Sürüm | Tarih | Kalibrasyon | Not |
|---|---|---|---|
| v1 "mevcut" | ≤ 2026-10-31 | Tek k + saat şekli + kt faktörü, Open-Meteo best_match geçmiş tahminiyle fit, D+1…D+7'ye aynı katsayı | Eğitim ürünü ≠ kullanım ürünü (4-model karması). Sistematik fazla tahmin |
| v2 "ufuk" | 2026-11-01 | Her ufuk (D+1…D+7) kendi Previous Runs serisiyle, son 75 gün, her tam çalışmada yenilenir | `config.calibration.mode="ufuk"` |
| v2.1 "ufuk+mevsim" | 2026-11-01 | v2 + mevsimsel k eğrisi (havuzlanmış, yıl sabitli 3 harmonik) | `season_correction=true`. Geri dönüş: önce season_correction=false, sonra mode="mevcut". Kalibrasyon dosyası yoksa/10 günden eskiyse otomatik v1'e düşer |
| v2.2 "ülke adaptörü" (canlı) | 2026-11-05 | v2.1 ile aynı (matematik değişmedi) | Yapısal: `countries/UA/`, `uages/countries/` adaptörleri, ortak `cache/`, `--ulke`. Altın test: eski kodla 22 çıktı dosyası (18 CSV + 4 kalibrasyon JSON) birebir aynı, test D+1…D+7 nMAE değişmedi |

## Deneyler ve sonuçlar

### ✅ Olumlu — canlıda
| Deney | Sonuç | Karar |
|---|---|---|
| Ufka göre kalibrasyon | D+1 nMAE %10,5→%9,3; bias +%6,1→+%0,6. D+1…D+7 hepsinde bias +%6–10 → +%0,6–2,1. D+1 günlük enerji hatası 1.687→1.312 MWh; sistematik fazla tahmin +1.133→+77 MWh/gün. Eyl–Eki'de günlerin %83'ünde daha iyi | Canlı. Kazancın neredeyse tamamı buradan |
| Mevsimsel k düzeltmesi | Örneklem dışı kış (2025/26 Kas–Mar, eğri yalnız 2024-01…2025-06 verisinden): D+1 %34,0→%30,9, D+3 %37,5→%33,8, D+5 %43,0→%39,0, D+7 %55,6→%49,8. Nis–Eki nötr (±0,1) | Canlı. k yıllık deseni: Haz–Ağu ~0,95 → Eyl 0,91–0,93 → Eki 0,85 → Kas 0,57–0,69 → Ara 0,44–0,49 → Oca 0,62–0,69 (2024 ve 2025 aynı) |
| GPEE geri doldurma | 2020-07'den itibaren 48.241 saat; depo 7.272 → 55.513 satır, 0 hatalı gün | Canlı (analiz dönemi hâlâ `history.start=2026-01-01`) |
| Panel saat dilimi | Tüm saatler Kyiv (önce tarayıcı saatiyle gösteriliyordu) | Canlı |
| Vektörel kalibrasyon çekirdeği | Eski döngüyle birebir (3.628 saatte fark 0 MW), `tools/check_vector_calib.py` | Canlı |

### ⚪ Nötr / etkisiz — devreye alınmadı (tekrar denemeden önce gerekçe gerekir)
| Deney | Sonuç | Neden alınmadı |
|---|---|---|
| Ufka göre model ağırlıkları (NNLS, eşit ağırlığa %20 büzülmüş) | Test farkı ≤0,4 puan; D+1 9,25→9,26 | Gürültü düzeyi. D+1 ağırlıkları zaten config'e yakın çıktı (ECMWF 0,48 / ICON 0,25 / GFS 0,12 / best_match 0,15) |
| Kalibrasyon ayar ızgarası (240 kombinasyon: k penceresi 7–45, şekil penceresi 30–90, büzme 10–40, yarı ömür yok/14/30/60) | En iyi: k=7 gün, şekil=45, büzme=10, yarı ömür=14. Test D+1 9,25→9,22, D+5 14,0→13,6 | ≤0,4 puan, gürültü |
| Ufuk başına ayrı mevsim eğrisi | Havuzlanmış eğriyle aynı kazanç | Havuzlanmış daha az riskli |
| Uydu (SARAH3) tabanlı mevsim eğrisi | Ek kazanç yok | Aynı |
| ECMWF ensemble P10–P90 bandı | Kapsama %88–95 (hedef %80) → fazla geniş, yaz özellikle | Sorun duruyor; bkz. açık işler |
| Konformal bant (ufuk × kt sınıfı, seçim dönemi oran yüzdelikleri) | Test kapsaması D+1…D+5 %88–90, D+6/7 %94–95 | Hâlâ geniş; devreye alınmadı |

### ❌ Olumsuz — kapatıldı
| Deney | Sonuç | Karar |
|---|---|---|
| SEAS5 mevsimsel tahmini (uzun vade) | Ham GHI ERA5'e göre sistematik yanlı (Ekim ~%27 yüksek) | `longterm.use_seasonal=false`. Kendi hindcast klimatolojisi olmadan anomali çıkarılamaz |

## Bilinen zayıflıklar (ölçülmüş)
- **D+1'de GPEE önde:** test %7,6 (GPEE) vs %9,3 (model); kısıtlı saatler dahil %12,4 vs %13,1. 2026 Ocak–Ekim
  history doğrulamasında %8,4 vs %11,2. Model değeri D+2…D+7'de ve GPEE'nin yayımlamadığı günlerde.
- **Haziran 2026:** ufuk modu %5–6 eksik tahmin (D+1 Haziran %8,9; v1 tesadüfen %7,2, GPEE %5,3). Hipotez:
  bayraklanmamış bahar kısıtı Mayıs k'sını düşürüyor; 2026 Nis–May k düşüşü önceki yıllarda yok.
- **Ekim 2026:** tüm yöntemler kötü (D+1 ~%18, GPEE %14,8). Mevsimsel k düşüşü dönemi.
- **Kış:** D+1 %30–34, D+7 %50–55. Kar şu an yalnız albedoyu etkiliyor; panel üstü kar (kapatma) modeli yok.
  En büyük kaldıraç olarak işaretlendi.
- **Son 7 gün (22–28 Eki 2026, ~70 gündüz saati/ufuk):** D+1 GPEE %9,8 / v1 %23,8 / ufuk %13,9 / ufuk+mevsim %12,9;
  D+7 %63,3 / %49,9 / %37,7.
- Kısıt **tahmin edilmiyor**; yalnız eğitimden dışlanıyor (xlsx bayrakları 840 gün-saat + 236 saat, artı model
  tabanlı bayrak: açık hava, gerçekleşen < 0,75 × beklenen ve < 0,75 × GPEE tahmini, beklenen > 300 MW).
- 426 yer tutucu faz oblast merkezinde; bölge ağırlıkları kaba; 8 nokta hava.

## Sıradaki işler (PDF'te listelenen, henüz yapılmadı)
1. Kar modeli (panel kapanması) — kış hatası.
2. Belirsizlik bandı — mevsime göre ayrı, kapsama %80'e çekilmeli.
3. Gerçek yayın isabeti — `outputs/arsiv/` her yayımlanan tahmini saklıyor; birkaç hafta sonra "Son 7 gün" geriye
   dönük hesap yerine gerçek arşivle beslenecek.
4. Sürüm kontrolü (git yok).
5. Haziran zayıflığı / bahar kısıtı — Mayıs 2027'den önce.

## Macaristan (HU) — kayıtlar
| Tarih | Konu | Sonuç |
|---|---|---|
| 2026-11-05 | ENTSO-E envanteri | Gerçekleşen 2019-09-22'den, %0 eksik, 15 dk. A68 kurulu güç 2025'te 4,0 → 8,3 GW kırılma (çatı eklendi), gerçekleşen yalnız sayaçlı. MAVIR D+1 nMAE 2026 %12,1 (tüm gündüz), Ara–Oca ~%41; gün içi %8,7 |
| 2026-11-05 | Kapasite kaynağı | GEM Şubat 2026: 795 santral 4.061 MW, %99 kesin konum; ENTSO-E 2024 kurulu gücü 4.029 MW ile örtüşüyor |
| 2026-11-05 | Hava noktası sayısı | 8 kapasite ağırlıklı nokta ile başlandı (1 günlük istek limiti). 15 nokta ve OSM / veriden öğrenilen ağırlık karşılaştırması bekliyor |

## Değişiklik kaydı
- 2026-11-05: Macaristan adaptörü (HU) eklendi; UA altın test ÖZDEŞ, HU sahte veriyle uçtan uca test TAMAM.
- 2026-11-05: v2.2 ülke adaptörü eklendi (sonuç değişmedi; altın test `tests/golden/run_golden.py`).
- 2026-11-05: Dosya oluşturuldu (refactor + çok ülke beyin fırtınası başlangıcı).

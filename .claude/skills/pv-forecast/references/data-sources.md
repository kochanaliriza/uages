# Veri kaynakları

Kapsam tarihleri ve limitler değişebilir. "Doğrula" işaretli satırları kullanmadan önce küçük bir
deneme isteğiyle (tek nokta, tek gün) kontrol et ve sonucu buraya işle.

## Hedef: GPEE
- Uç: `POST https://www.gpee.com.ua/main/loadCharts`, form `date=dd.mm.yyyy, zona=1, gen=1`.
- Yanıt: 50 elemanlı dizi, [0..24] gerçekleşen, [25..49] GPEE tahmini (25. eleman 25 saatlik DST günü için).
- Bulut/veri merkezi IP'lerinden 403 dönüyor, kullanıcının bilgisayarından çalışıyor.
- Yayımlanmamış gerçekleşen: hepsi 0 ya da boş gelir → NaN (sıfır üretim değil).
- Geçmiş derinliği (2026-10-31'de test edildi): **gerçekleşen Temmuz 2020'den beri** (2020-07-01 boş, 2020-07-15 dolu),
  GPEE tahmini 2019'dan beri, 2018 boş dizi. Sunucu ara sıra 30 sn'de zaman aşımına düşüyor: timeout 60 sn + yeniden deneme kullan.
  2022 Mart–Temmuz gibi dönemlerde gerçekleşen GPEE tahmininin çok altında (savaş/kısıt): eğitimde etiketle.
- Kapsam: yalnızca yeşil tarife dengeleme grubu; grubun MW'ı yayımlanmıyor (bkz. `ukraine-context.md`).

## Open-Meteo (anahtarsız, ücretsiz katman ticari olmayan kullanım için)
| Ürün | Uç | Kullanım | Not |
|---|---|---|---|
| Forecast | `api.open-meteo.com/v1/forecast` | 7–16 gün, çoklu model tek istekte (`models=a,b`) → sütun `<var>_<model>` | `wind_speed_unit=ms` ver |
| Previous Runs | `previous-runs-api.open-meteo.com/v1/forecast` | Ufka göre arşiv: `shortwave_radiation_previous_day1…7` | Ufka bağlı kalibrasyonun ana kaynağı. Başlangıç (test edildi): ICON ve GFS 2024-01-19, ECMWF IFS025 2024-03-06 (day5: +4 gün). **ICON seamless'ta `previous_day7` yok** (ufuk <7 gün) |
| Historical Forecast | `historical-forecast-api.open-meteo.com/v1/forecast` | Kısa ufuklu tahminlerin uç uca eklenmiş arşivi | D+0/D+1 kalitesini temsil eder, D+2+ değil. Model bazında başlangıç (test edildi): best_match 2021-01, GFS 2021-03-23, ICON 2022-11-16, ECMWF IFS025 2024-03-05; `ecmwf_ifs04` boş |
| Archive | `archive-api.open-meteo.com/v1/archive` | `models=era5` (1940→, ~5 gün gecikme), `era5_land`, ya da best-match | ERA5 bulut/GHI saatlik hatası yüksek; aylık toplamda iyi |
| Ensemble | `ensemble-api.open-meteo.com/v1/ensemble` | `ecmwf_ifs025` (51 üye, 15 gün), `gfs025`, `icon_seamless` | Üye sütunları `shortwave_radiation_memberNN` |
| Seasonal | `seasonal-api.open-meteo.com/v1/seasonal` | SEAS5 | Ham GHI yanlı; hindcast klimatolojisi olmadan anomali çıkarma |
| Satellite Radiation | `satellite-api.open-meteo.com/v1/archive` | Uydu tabanlı gerçekleşen ışınım (GHI, DNI, DHI) | Test edildi: `models=eumetsat_sarah3` ≤2019 → **dün** (~1–2 gün gecikme), Ukrayna dahil. `eumetsat_lsa_saf_msg` 2025'ten itibaren. Model belirtilmezse karışım gelir, değerler daha düşük: modeli açıkça ver. Zaman konvansiyonunu `best_lag` ile doğrula |
| Air Quality | `air-quality-api.open-meteo.com/v1/air-quality` | CAMS `aerosol_optical_depth`, `dust` | Açık gün GHI hatası, toz olayları |

Yararlı ek değişkenler: `cloud_cover_low/mid/high`, `global_tilted_irradiance` (`tilt`, `azimuth`
parametreleriyle; Open-Meteo azimut 0=güney), `direct_radiation`, `snowfall`, `precipitation`,
`relative_humidity_2m`, `wind_gusts_10m`.

Limitler: günlük ~10.000, saatlik ~5.000, dakikalık ~600 istek (ücretsiz). Çok değişkenli/uzun aralıklı
istekler birden fazla "istek" sayılır. Toplu geçmiş çekiminde yılları parçala, önbelleği kullan, 429'da bekle.
Ticari kullanım ya da yüksek hacim için API anahtarlı (`customer-` önekli uç ve `apikey=`) plan gerekir.

## PVGIS (JRC), `https://re.jrc.ec.europa.eu/api/v5_3`
| Uç | İçerik | Kullanım |
|---|---|---|
| `seriescalc` | Saatlik seri. `raddatabase=PVGIS-SARAH3` ve `PVGIS-ERA5`: ikisi de **2005–2023** (test edildi, 2024 → 400). Zaman damgası SARAH3'te HH:10, ERA5'te HH:30. `components=1` ile Gb(i)/Gd(i)/Gr(i) | Uzun vade, ERA5 yanlılık düzeltme referansı, 2020–2023 GPEE örtüşmesi |
| `seriescalc` `trackingtype` | 0 sabit, 1 tek eksen (yatay K-G), 2 iki eksen, 3 dikey eksen, 4 tek eksen (yatay D-B), 5 eğik tek eksen | Montaj karışımı fit'i. Bölge 3, 2020 (kWh/kWp): sabit 30° 1282, tip 1 1499, tip 4 1363, tip 5 1662, iki eksen 1712. Optimum sabit açı 36°/−4° |
| `tmy` | Tipik meteorolojik yıl | Uzun vade karması |
| `PVcalc` | Aylık/yıllık PV çıktısı, `optimalangles=1` | Hızlı çapraz kontrol |
| Ortak | `usehorizon=1` (varsayılan) arazi ufku; `aspect`: 0=güney, −90=doğu (bizim azimut −180) | |

Limit: saniyede ~30 istek/IP. Gerçek zamanlı değildir: tahmin ya da 2024+ kalibrasyon girdisi olamaz.

## CAMS Radiation Service (SoDa)
- Uydu tabanlı (MSG) GHI/BHI/DHI, 15 dk – 1 saat, 2004 → yakın zaman. Ücretsiz kayıt gerekir.
- Ukrayna MSG diskinin içinde ama kuzeydoğuya doğru görüş açısı kötüleşir; SARAH ile kıyasla.
- Kullanıcı hesabı gerektirdiği için kimlik bilgisini koda yazma; ortam değişkeni kullan.

## Piyasa ve sistem (kısıt ve bağlam)
- Piyasa Operatörü (OREE, oree.com.ua): gün öncesi ve gün içi fiyat/hacim. Düşük ya da sıfıra yakın fiyat saatleri kısıt göstergesi.
- Ukrenergo (ua.energy): üretim yapısı, dispeçer kısıtları, kesinti duyuruları.
- Kamuya açıklık ve uçlar değişkendir; scraping yapmadan önce sayfanın kullanım koşullarına bak.

## Kaynak seçimi (rol tablosu)
| İhtiyaç | Birinci tercih | Yedek |
|---|---|---|
| Tahmin girdisi | Open-Meteo Forecast (ECMWF, ICON, GFS) | best_match |
| Ufka göre kalibrasyon | Previous Runs | Historical Forecast (yalnız D+1) |
| Gerçekleşen ışınım 2020→dün | Open-Meteo Satellite `eumetsat_sarah3` (tek kaynak, tüm GPEE dönemi) | ERA5, ya da ≤2023 için PVGIS SARAH3 |
| Ufka göre tahmin 2024-03→ | Previous Runs (ECMWF, GFS; ICON ≤D+6) | — |
| Uzun vade | ERA5 + SARAH3 + TMY | — |

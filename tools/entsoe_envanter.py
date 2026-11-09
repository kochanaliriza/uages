r"""ENTSO-E gunes verisi envanteri (yeni ulke pilotu, Adim 1). Yalnizca okur ve rapor uretir; model kodu degismez.

  python tools/entsoe_envanter.py --ulke HU                      # 2019-01-01 -> dun
  python tools/entsoe_envanter.py --ulke HU --bas 2023-01-01
  python tools/entsoe_envanter.py --ulke PL                      # SK, RO, MD de tanimli

Token: ENTSOE_TOKEN ortam degiskeni ya da proje kokunde entsoe_token.txt (tek satir; git'e girmez). Ekrana yazilmaz.
Adres: varsayilan https://web-api.tp.entsoe.eu/api; platform degisirse --api ile ya da ENTSOE_API ortam degiskeniyle.
HTTPS dogrulamasi countries/UA/config.json -> ag.ssl_dogrulama ayarini izler (UAGES_SSL_DOGRULAMA de gecerli).

Cekilenler (psrType B16 = gunes):
  A75 / A16  gerceklesen uretim (tipe gore)            -> hedef serisi adayi
  A69 / A01  gun oncesi ruzgar+gunes tahmini (TSO)     -> kiyas noktasi (UA'daki GPEE D+1'in karsiligi)
  A69 / A40  gun ici tahmin (varsa)                    -> bilgi
  A68 / A33  kurulu guc (yillik)                       -> kapasite trendi
Ciktilar: countries/<KOD>/data/store/entsoe_<belge>.csv (UTC aralik basi, ozgun cozunurluk) ve
countries/<KOD>/envanter_raporu.md (kapsam, eksikler, cozunurluk, kurulu guc, TSO D+1 isabeti).
Zaman: ENTSO-E zamanlari UTC; deger [t, t+cozunurluk) ortalama MW. Saatlige cevirmede ortalama alinir.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd

from uages import net
from uages.config import ROOT
from uages.solar import solar_position
from uages.sources.entsoe import API, BELGELER, ULKELER, EntsoeHata, cek, saatlik, token  # noqa: F401


def md(df: pd.DataFrame) -> str:
    """Basit markdown tablo (tabulate gerektirmez)."""
    cols = [df.index.name or ""] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for i, row in df.iterrows():
        hucre = [f"{v:,.0f}" if isinstance(v, float) and float(v).is_integer() else f"{v:,.2f}" if isinstance(v, float) else str(v)
                 for v in row]
        lines.append("| " + " | ".join([str(i)] + hucre) + " |")
    return "\n".join(lines)


def yerel(idx: pd.DatetimeIndex, tz: str) -> pd.DatetimeIndex:
    """UTC (tz-naive) -> yerel saat (tz-naive); yil/ay gruplamalari yerel takvimle yapilir."""
    return pd.DatetimeIndex(idx).tz_localize("UTC").tz_convert(tz).tz_localize(None)


def nmae_tablo(act: pd.Series, fc: pd.Series, elev: pd.Series, by) -> pd.DataFrame:
    j = pd.DataFrame({"a": act, "f": fc, "elev": elev}).dropna()
    j = j[j["elev"] > 0]
    g = j.groupby(by(j.index))
    out = pd.DataFrame({
        "n_saat": g.size(),
        "ort_gunduz_MW": g["a"].mean(),
        "nMAE_%": g.apply(lambda x: (x["f"] - x["a"]).abs().mean() / x["a"].mean() * 100),
        "bias_%": g.apply(lambda x: (x["f"] - x["a"]).mean() / x["a"].mean() * 100),
    })
    return out.round(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ulke", default="HU", choices=sorted(ULKELER))
    ap.add_argument("--bas", default="2019-01-01")
    ap.add_argument("--bit", default=None, help="varsayilan: dun (UTC)")
    ap.add_argument("--api", default=os.environ.get("ENTSOE_API", API))
    a = ap.parse_args()
    u = ULKELER[a.ulke]
    ua_cfg = ROOT / "countries" / "UA" / "config.json"
    if ua_cfg.exists():
        import json
        net.ayarla(json.loads(ua_cfg.read_text(encoding="utf-8")))
    tok = token()
    bas = pd.Timestamp(a.bas)
    bit = pd.Timestamp(a.bit) if a.bit else pd.Timestamp.now("UTC").tz_localize(None).normalize()
    store = ROOT / "countries" / a.ulke / "data" / "store"
    store.mkdir(parents=True, exist_ok=True)
    print(f"{u['ad']} ({u['eic']})  {bas.date()} -> {bit.date()}  API {a.api}  SSL dogrulama: {'acik' if net.VERIFY else 'KAPALI'}")

    veri, hatalar = {}, {}
    for i, belge in enumerate(BELGELER, 1):
        print(f"[{i}/{len(BELGELER)}] {belge}", flush=True)
        try:
            df = cek(a.api, tok, u["eic"], belge, bas, bit)
        except EntsoeHata as e:
            hatalar[belge] = str(e)
            print(f"    HATA: {e}")
            if str(e).startswith(("401", "403", "404")):
                break
            continue
        veri[belge] = df
        df.to_csv(store / f"entsoe_{belge}.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
        print(f"    {len(df)} satir")

    rap = [f"# {u['ad']} — ENTSO-E güneş verisi envanteri", "",
           f"Oluşturma: {pd.Timestamp.now():%Y-%m-%d %H:%M} · alan {u['eic']} · istenen dönem {bas.date()} → {bit.date()} · "
           "zamanlar UTC, saatlik = çeyreklerin ortalaması", ""]
    if hatalar:
        rap += ["## Hatalar", ""] + [f"- **{k}**: {v}" for k, v in hatalar.items()] + [""]
    rap += ["## Kapsam", "", "| Belge | İlk | Son | Satır | Çözünürlük(ler) | Saatlik eksik % (gündüz dahil tüm saatler) |", "|---|---|---|---|---|---|"]
    saat = {}
    for k, df in veri.items():
        if df.empty:
            rap.append(f"| {k} | — | — | 0 | — | — |")
            continue
        if k == "kurulu_guc":
            rap.append(f"| {k} | {df.time_utc.min().date()} | {df.time_utc.max().date()} | {len(df)} | yıllık | — |")
            continue
        h = saatlik(df)
        saat[k] = h
        tam = pd.date_range(h.index.min(), h.index.max(), freq="h")
        eksik = 100 * (1 - h.reindex(tam).notna().mean())
        cz = ", ".join(f"{r} ({g.time_utc.min():%Y-%m}→)" for r, g in df.groupby("cozunurluk"))
        rap.append(f"| {k} | {df.time_utc.min():%Y-%m-%d %H:%M} | {df.time_utc.max():%Y-%m-%d %H:%M} | {len(df)} | {cz} | {eksik:.2f} |")
    rap.append("")

    if "kurulu_guc" in veri and not veri["kurulu_guc"].empty:
        kg = veri["kurulu_guc"]
        rap += ["## Kurulu güç (ENTSO-E A68, yıllık)", "", "| Yıl | MW |", "|---|---|"]
        rap += [f"| {t.year} | {v:,.0f} |" for t, v in zip(yerel(kg.time_utc, u["tz"]), kg.mw)] + [""]

    if "gerceklesen" in saat:
        g = saat["gerceklesen"]
        lat, lon = u["merkez"]
        elev = pd.Series(90 - solar_position(g.index + pd.Timedelta(minutes=30), lat, lon)["zenith"].to_numpy(), index=g.index)
        yl_ = yerel(g.index, u["tz"]).year
        yil = pd.DataFrame({"TWh": g.groupby(yl_).sum() / 1e6, "maks_MW": g.groupby(yl_).max(),
                            "eksik_saat": g.isna().groupby(yl_).sum()})
        gece = g[(elev < -6)]
        rap += ["## Gerçekleşen üretim (yıllık)", "", md(yil.round(2).rename_axis("yil")), "",
                f"Gece (güneş −6°'nin altında) ortalaması {gece.mean():.1f} MW, maks {gece.max():.1f} MW "
                "(sıfırdan belirgin farklıysa seri net/tahmini olabilir veya zaman kayması vardır).", ""]
        if "tso_gun_oncesi" in saat and "tso_gun_ici" in saat:
            d, i_ = saat["tso_gun_oncesi"], saat["tso_gun_ici"]
            jj = pd.DataFrame({"d": d, "i": i_}).dropna()
            ayni = float((np.abs(jj["d"] - jj["i"]) < 0.01).mean() * 100) if len(jj) else float("nan")
            ii = nmae_tablo(g, i_, elev, lambda i: yerel(i, u["tz"]).year)
            rap += ["## Gün içi tahmin (A69/A40)", "",
                    f"Gün öncesi ile aynı değerdeki saat oranı: %{ayni:.1f} "
                    "(~%100 ise ENTSO-E gün içi diye gün öncesini tekrar yayımlıyor demektir; ayrı bir bilgi taşımaz).", "",
                    md(ii.rename_axis("yil")), ""]
        if "tso_gun_oncesi" in saat:
            f = saat["tso_gun_oncesi"]
            yl = nmae_tablo(g, f, elev, lambda i: yerel(i, u["tz"]).year)
            ay = nmae_tablo(g, f, elev, lambda i: yerel(i, u["tz"]).to_period("M").astype(str))
            # zaman hizalama: korelasyon tepe noktasi 0'da olmali
            j = pd.DataFrame({"a": g, "f": f}).dropna()
            lags = {L: round(float(j["a"].corr(j["f"].shift(L))), 4) for L in range(-2, 3)}
            rap += ["## TSO gün öncesi tahmininin isabeti (kıyas noktası)", "",
                    "nMAE = saatlik MAE / ortalama gündüz gerçekleşen (güneş yüksekliği > 0, ülke merkezi), UA projesiyle aynı tanım. "
                    "Kısıt bayrağı yok: tüm gündüz saatleri.", "", "### Yıllara göre", "",
                    md(yl.rename_axis("yil")), "", "### Son 12 ay", "",
                    md(ay.tail(12).rename_axis("ay")), "",
                    f"Zaman hizalama (gerçekleşen vs tahmin korelasyonu, saat kaydırma): {lags} — tepe 0'da olmalı.", ""]
    rap += ["## Sonraki adım", "", "- Hedef seriyi seç (gerçekleşen A75) ve kıyası (TSO A69 gün öncesi) sabitle.",
            "- Kapasite dağılımı (il/NUTS-3) ve hava noktaları için ulusal kayıt (MAVIR/MEKH) araştırması.",
            "- Ülke adaptörü: `uages/countries/hu.py` + `countries/HU/config.json`."]
    out = ROOT / "countries" / a.ulke / "envanter_raporu.md"
    out.write_text("\n".join(rap) + "\n", encoding="utf-8")
    print(f"\nRapor: {out}")
    if hatalar:
        sys.exit(1)


if __name__ == "__main__":
    main()

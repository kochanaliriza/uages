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
import io
import os
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
import requests

from uages import net
from uages.config import ROOT
from uages.solar import solar_position

API = "https://web-api.tp.entsoe.eu/api"
# Resmi EIC listesi (transparencyplatform.zendesk.com, makale 15885757676308) - BZN ve CTA ayni kod.
# merkez: kapasite agirlik merkezi icin kaba ilk tahmin (yalnizca gunduz maskesi icin); ulke pilotunda gercek dagilimla degisecek
ULKELER = {
    "HU": {"eic": "10YHU-MAVIR----U", "ad": "Macaristan", "tz": "Europe/Budapest", "merkez": (47.2, 19.4)},
    "PL": {"eic": "10YPL-AREA-----S", "ad": "Polonya", "tz": "Europe/Warsaw", "merkez": (51.9, 19.1)},
    "SK": {"eic": "10YSK-SEPS-----K", "ad": "Slovakya", "tz": "Europe/Bratislava", "merkez": (48.4, 18.9)},
    "RO": {"eic": "10YRO-TEL------P", "ad": "Romanya", "tz": "Europe/Bucharest", "merkez": (45.0, 25.0)},
    "MD": {"eic": "10Y1001A1001A990", "ad": "Moldova", "tz": "Europe/Chisinau", "merkez": (47.0, 28.8)},
}
BELGELER = {
    "gerceklesen": {"documentType": "A75", "processType": "A16", "psrType": "B16"},
    "tso_gun_oncesi": {"documentType": "A69", "processType": "A01", "psrType": "B16"},
    "tso_gun_ici": {"documentType": "A69", "processType": "A40", "psrType": "B16"},
    "kurulu_guc": {"documentType": "A68", "processType": "A33", "psrType": "B16"},
}


class EntsoeHata(RuntimeError):
    pass


def _dosyadan_token() -> tuple[str | None, str]:
    """entsoe_token.txt'yi (ya da gizli uzanti hatasiyla entsoe_token.txt.txt'yi) okur. Not Defteri'nin BOM'lu UTF-8,
    UTF-16 ('Unicode') kayitlarini, tirnaklari, bosluklari ve 'securityToken=' onekini temizler."""
    for ad in ["entsoe_token.txt", "entsoe_token.txt.txt", "entsoe_token"]:
        fp = ROOT / ad
        if not fp.exists():
            continue
        b = fp.read_bytes()
        if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
            txt = b.decode("utf-16")
        else:
            txt = b.decode("utf-8-sig", errors="replace")
        satirlar = [x.strip().strip('"').strip("'").strip() for x in txt.replace("\ufeff", "").splitlines()]
        satirlar = [x.split("=", 1)[1].strip() if x.lower().startswith("securitytoken=") else x for x in satirlar if x]
        return (satirlar[0] if satirlar else None), ad
    return None, ""


def token() -> str:
    t = os.environ.get("ENTSOE_TOKEN", "").strip() or None
    kaynak = "ENTSOE_TOKEN ortam degiskeni"
    if not t:
        t, ad = _dosyadan_token()
        kaynak = ad
    if t:
        print(f"Token: {kaynak} ({len(t)} karakter; ENTSO-E token'lari genelde 36 karakterdir)")
    if not t:
        sys.exit("HATA: ENTSO-E token yok. ENTSOE_TOKEN ortam degiskenini ayarlayin ya da proje kokune entsoe_token.txt koyun.\n"
                 "Token: transparency.entsoe.eu -> hesap -> 'RESTful API access' (bkz. README).")
    return t


def iste(api: str, tok: str, params: dict, deneme: int = 5) -> bytes | None:
    """Ham yanit (XML ya da zip). Veri yoksa None. 429/5xx'te artan bekleme."""
    p = {"securityToken": tok, **params}
    son = None
    for i in range(deneme):
        try:
            r = requests.get(api, params=p, timeout=120, **net.kw())
        except requests.RequestException as e:
            son = f"ag hatasi: {type(e).__name__}: {str(e)[:200]}"
            time.sleep(5 * (i + 1))
            continue
        if r.status_code == 200:
            if r.content[:2] == b"PK":
                return r.content
            if b"Acknowledgement_MarketDocument" in r.content[:400]:
                txt = _ack(r.content)
                if "No matching data" in txt or "999" in txt:
                    return None
                raise EntsoeHata(f"ENTSO-E reddetti: {txt}")
            return r.content
        if r.status_code == 401:
            raise EntsoeHata("401: token gecersiz ya da API erisimi acilmamis (transparency@entsoe.eu, konu 'RESTful API access').")
        if r.status_code in (403, 404):
            raise EntsoeHata(f"{r.status_code}: API adresi degismis ya da platform bakimda olabilir (2026 gecis duyurusuna bakin; "
                             f"--api ile yeni adresi verin). Yanit: {r.text[:300]}")
        if r.status_code == 400:
            raise EntsoeHata(f"400: istek reddedildi: {_ack(r.content) or r.text[:300]}")
        son = f"HTTP {r.status_code}"
        time.sleep(min(60, 5 * 2 ** i))
    raise EntsoeHata(f"istek basarisiz ({son})")


def _ack(b: bytes) -> str:
    try:
        root = ET.fromstring(b)
        return " | ".join(e.text or "" for e in root.iter() if e.tag.endswith("text") or e.tag.endswith("code"))
    except ET.ParseError:
        return b[:300].decode("utf-8", "replace")


def _xmller(raw: bytes) -> list[bytes]:
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return [z.read(n) for n in z.namelist() if n.endswith(".xml")]
    return [raw]


RES = {"PT15M": "15min", "PT30M": "30min", "PT60M": "60min", "P1Y": None, "P1D": "1D"}


def ayristir(raw: bytes) -> pd.DataFrame:
    """GL_MarketDocument -> [time_utc, mw, cozunurluk]. Tuketim serileri (outBiddingZone) atlanir.
    curveType A03'te eksik pozisyon = bir onceki deger (yalnizca periyot icinde)."""
    rows = []
    for xml in _xmller(raw):
        root = ET.fromstring(xml)
        for ts in [e for e in root.iter() if e.tag.endswith("TimeSeries")]:
            tags = {c.tag.split("}")[-1]: c for c in ts}
            if "outBiddingZone_Domain.mRID" in tags:
                continue  # tuketim (pompaj vb.); gunes icin olmamali
            curve = next((e.text for e in ts.iter() if e.tag.endswith("curveType")), "A01")
            for per in [e for e in ts.iter() if e.tag.endswith("Period")]:
                start = next(e.text for e in per.iter() if e.tag.endswith("start"))
                end = next(e.text for e in per.iter() if e.tag.endswith("end"))
                res = next(e.text for e in per.iter() if e.tag.endswith("resolution"))
                t0, t1 = pd.Timestamp(start).tz_convert("UTC").tz_localize(None), pd.Timestamp(end).tz_convert("UTC").tz_localize(None)
                pts = {}
                for pt in [e for e in per if e.tag.endswith("Point")]:
                    pos = int(next(e.text for e in pt if e.tag.endswith("position")))
                    q = next(e.text for e in pt if e.tag.endswith("quantity"))
                    pts[pos] = float(q)
                if RES.get(res) is None:  # yillik kurulu guc
                    for pos, q in pts.items():
                        rows.append((t0, q, res))
                    continue
                step = pd.Timedelta(RES[res])
                n = int((t1 - t0) / step)
                last = np.nan
                for pos in range(1, n + 1):
                    if pos in pts:
                        last = pts[pos]
                        v = last
                    else:
                        v = last if curve == "A03" else np.nan
                    rows.append((t0 + (pos - 1) * step, v, res))
    df = pd.DataFrame(rows, columns=["time_utc", "mw", "cozunurluk"])
    return df.dropna(subset=["mw"]).drop_duplicates("time_utc", keep="last").sort_values("time_utc").reset_index(drop=True)


def cek(api, tok, eic, belge, bas: pd.Timestamp, bit: pd.Timestamp) -> pd.DataFrame:
    b = BELGELER[belge]
    params = {k: v for k, v in b.items()}
    params["in_Domain"] = eic
    if b["documentType"] == "A68":
        params["periodStart"], params["periodEnd"] = f"{bas.year}01010000", f"{bit.year + 1}01010000"
        raw = iste(api, tok, params)
        return ayristir(raw) if raw else pd.DataFrame(columns=["time_utc", "mw", "cozunurluk"])
    parts = []
    sinirlar = list(pd.date_range(bas, bit, freq="YS"))
    sinirlar = ([bas] if not sinirlar or sinirlar[0] > bas else []) + sinirlar + [bit]
    parcalar = [(a, c) for a, c in zip(sinirlar[:-1], sinirlar[1:]) if a < c]
    for i, (a, c) in enumerate(parcalar, 1):
        params["periodStart"], params["periodEnd"] = a.strftime("%Y%m%d%H%M"), c.strftime("%Y%m%d%H%M")
        print(f"    {belge}: {i}/{len(parcalar)} ({a.date()} -> {c.date()})", flush=True)
        raw = iste(api, tok, params)
        if raw:
            parts.append(ayristir(raw))
    if not parts:
        return pd.DataFrame(columns=["time_utc", "mw", "cozunurluk"])
    return pd.concat(parts).drop_duplicates("time_utc", keep="last").sort_values("time_utc").reset_index(drop=True)


def saatlik(df: pd.DataFrame) -> pd.Series:
    """Ozgun cozunurluk -> saatlik ortalama MW (UTC aralik basi). Saatte eksik ceyrek varsa saat NaN."""
    s = df.set_index("time_utc")["mw"]
    adet = s.resample("h").count()
    beklenen = df.set_index("time_utc")["cozunurluk"].map({"PT15M": 4, "PT30M": 2, "PT60M": 1}).resample("h").max()
    m = s.resample("h").mean()
    return m.where(adet >= beklenen.fillna(1))


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

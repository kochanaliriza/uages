"""uages: ulke bazli GES uretim analizi ve tahmini."""
from __future__ import annotations

import os


def _sistem_sertifikalari() -> str:
    """HTTPS dogrulamasinda Windows/macOS sertifika deposunu kullan (truststore).

    Kurumsal aglarda guvenlik duvari baglantilari kendi koku sertifikasiyla yeniden imzalar; bu sertifika Windows'ta
    guvenilir ama Python'un kendi listesinde (certifi) yoktur -> CERTIFICATE_VERIFY_FAILED. truststore, Python'un
    TLS dogrulamasini isletim sisteminin deposuna yonlendirir; dogrulama KAPANMAZ.
    Kapatmak icin: UAGES_SISTEM_SERTIFIKA=0. Ozel bir CA dosyasi icin requests'in kendi REQUESTS_CA_BUNDLE degiskeni
    de kullanilabilir.
    """
    if os.environ.get("UAGES_SISTEM_SERTIFIKA", "1") == "0":
        return "kapali"
    try:
        import truststore
    except ImportError:
        return "yok"
    try:
        truststore.inject_into_ssl()
        return "aktif"
    except Exception:  # noqa: BLE001
        return "hata"


SERTIFIKA_DURUMU = _sistem_sertifikalari()


def ssl_ipucu(err: object) -> str:
    """SSL dogrulama hatasinda kullaniciya yol gosteren ek metin; degilse bos."""
    if "CERTIFICATE_VERIFY_FAILED" not in str(err):
        return ""
    if SERTIFIKA_DURUMU == "yok":
        return ("\n  -> Kurumsal ag sertifikasi taniyamadi. Cozum: python -m pip install truststore "
                "(pip de ayni hatayi verirse: python -m pip install --use-feature=truststore truststore). "
                "Sonra yeniden calistirin; Python, Windows sertifika deposunu kullanir.")
    return (f"\n  -> Sertifika dogrulanamadi (sistem deposu: {SERTIFIKA_DURUMU}). Ag/IT biriminden kurumsal kok sertifikayi "
            "isteyip REQUESTS_CA_BUNDLE ortam degiskeniyle gosterin.")

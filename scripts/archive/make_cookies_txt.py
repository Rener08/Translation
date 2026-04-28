#!/usr/bin/env python3
"""
Convert raw cookie string to Netscape cookies.txt format for yt-dlp.
Usage: python make_cookies_txt.py
"""

import sys

RAW_COOKIES = "__Secure-BUCKET=CIUD; SEARCH_SAMESITE=CgQIkKAB; _ga=GA1.1.282409310.1770899556; _ga_W1N0E9HGM3=GS2.1.s1771935002$o1$g0$t1771935002$j60$l0$h0; _ga_MZZYPLKTCM=GS2.1.s1771935009$o2$g0$t1771935009$j60$l0$h0; _ga_X299EBKSJW=GS2.1.s1772545031$o1$g1$t1772545751$j60$l0$h0; _ga_85DWT1X3MN=GS2.1.s1772639231$o1$g0$t1772639231$j60$l0$h0; _ga_2DSMCCF0KL=GS2.1.s1772640722$o1$g0$t1772640756$j26$l0$h0; OSID=g.a0007wi9AtSDdlS0tjUKzh6gEN9XJEaEF1Yrl8rUBxzIjFaeWDYwbZxQlpPyORVpvMJNC1jPlQACgYKAUESARUSFQHGX2MiLFI1dYLTkMLzWXI-qKzgnBoVAUF8yKrxqdnFPuQNR_D23iAF9yzR0076; __Secure-OSID=g.a0007wi9AtSDdlS0tjUKzh6gEN9XJEaEF1Yrl8rUBxzIjFaeWDYw1F4zkXOQ8sZV7iwBg39EdwACgYKAWQSARUSFQHGX2MipWoLpBGC0fYNygZNclc23xoVAUF8yKoa5pBrBmau8CmcTKbizKYT0076; OTZ=8522727_24_24__24_; _ga_T1753RVHPT=GS2.1.s1773667758$o1$g1$t1773668570$j56$l0$h0; _ga_XD8E5Y7Z0X=GS2.1.s1774613098$o1$g0$t1774613098$j60$l0$h0; SID=g.a0008gi9Ap8rhWX759nEcEwjq6cK-Hkg3BU96u0iveKzFMVV2_1rdGBF11uViyIGWsOwx6iCsAACgYKAWoSARUSFQHGX2MitfM0H-BNmJqoVH1J6Of4ThoVAUF8yKrF-MubhUkZrpogTIYqC3YD0076; __Secure-1PSID=g.a0008gi9Ap8rhWX759nEcEwjq6cK-Hkg3BU96u0iveKzFMVV2_1rqp5V4IY-BLhTVx0-i96FOAACgYKAWUSARUSFQHGX2Miulpx1eoAMKm2IEUUwwNETBoVAUF8yKqJrbCqHsG2PpoYV0X6dg4v0076; __Secure-3PSID=g.a0008gi9Ap8rhWX759nEcEwjq6cK-Hkg3BU96u0iveKzFMVV2_1rot3p1KzfrVMzq7cUdBqMYwACgYKAdYSARUSFQHGX2MiKiGj7Ngw7cVniSLMjb-29xoVAUF8yKphdEy6aIrA1E9rEE5HSmYr0076; HSID=AQOgXLm4-cpd0ljKn; SSID=AY8mNIr2qNDnasVZ5; APISID=sqAr3565miiz2q0t/AqLqIRM8sJUBOo73y; SAPISID=GhkBA9PYfnFfrty2/AYSpkblZ08XeaWRHt; __Secure-1PAPISID=GhkBA9PYfnFfrty2/AYSpkblZ08XeaWRHt; __Secure-3PAPISID=GhkBA9PYfnFfrty2/AYSpkblZ08XeaWRHt; AEC=AaJma5uviVQpe9altQPdFJ0aVhetNKTchlaIKlBCA2tZ3Z7kB5faB2bYTg; NID=530=JugTdkumdp05PDJFXLA8KnxYrmZZFc1P8-FhrymrldHxFHl5wySW7_XISqRXZEYs5VBtAmYGARJgkSgn4JMxKE_4dmOMM-U9ut-NWLZEycheG61J6VegXvbO_6whzBVvp0YeH-RugBFSaiZZQyvGBakT2-LLsb7NqEfZKCkYsskO29KuZboG-pA4X9cAHFXppccyvcTc3ccL-Fmoiv4VM3TLuItLu07_ncyMk4MZ7tmIxeYzoxIVHNwU8gQIXtnwiI7JiC-q4iRy6Oxoq10LdALt6SXt-NZ3IKQsUkTTqvux1jqFsfE7maIdLswS4xe423hrTIQB6R6g92JGo4g6ETjbYCb_CGzKEz0xz_0qulzXwKcugXCzwNq_dBy5a3bPSA-ykGbjGMh_DZLxWzEGEQiTZPtnEA812iv14mZbShnrnebcPX2_ms0SUbu-UDkXpPpm-vKe3odrfO-lACPlSiHeu6o-AT8aBh7F9BaBka_TGPBTLYyFgJUg07pwSfIA_pzY4OFSW2Ix2Azhd8WADVyw9VL1RT_SdjzN2TE-KjKqexBErXnat_n-sRem0opz43xWTj78J09V_ArPsAH_vS9IYkFmA41fphNNhZXn468y8FkK6QEfUFRwzsDuxib0-JKoZ0aesi1SzvwzUosXrfne0eT0m_0WWXfB-AHTLYJDSV5d0NIoDzAfvJ-ySjsNX8b9IQTwz53cEoQKeyFBgKJh0QzTg-Y703rSIz2jhKbQG8dtPhHmfKvzj7Xh-fuQXn1UfF5LmECkSs4m8ZCeAC6qx_991We1XmHypxuClKutV7JhrAlSHK3LfZLfEk3Tm3xMeLE; __Secure-1PSIDTS=sidts-CjEBWhotCZNydztDzf_9Yt55cgFt8my-aqMeExPKZwakGL36CLlI2dYmAGp0NXyRZdIxEAA; __Secure-3PSIDTS=sidts-CjEBWhotCZNydztDzf_9Yt55cgFt8my-aqMeExPKZwakGL36CLlI2dYmAGp0NXyRZdIxEAA; _ga_ZXD1HG8W1F=GS2.1.s1775907061$o1$g1$t1775907585$j60$l0$h0; SIDCC=AKEyXzXWrACY-c4pxj5FDCW2FEuj19p7G8PHEXIkbzCwDWM04sbjjmpTB2TtppdglX7NdY69Bw; __Secure-1PSIDCC=AKEyXzXB9fPTcAIPBPd_itMPk4wbeJwNbc9hyy8hCkt5nAu4PiLmYBKA1wuY0DIDo0nXmyHa1RU; __Secure-3PSIDCC=AKEyXzVriZIc_E5Jn_o1tMOe0IcdgjBwY8AlLDKjRWlbX80l4SlinGSD53Dltl1rGz9Dn6dXPQ; _ga_KHZNC1Q6K0=GS2.1.s1775907061$o11$g0$t1775907595$j50$l0$h0"


def parse_cookie_string(cookie_string):
    cookies = {}
    for pair in cookie_string.split("; "):
        if "=" in pair:
            key, value = pair.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def build_cookies_txt(cookies, domain=".youtube.com", path="/"):
    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.h.se/rfc/cookie_spec.html",
        "",
    ]
    for name, value in cookies.items():
        secure_flag = (
            "TRUE"
            if name.startswith("__Secure-") or name.startswith("__Host-")
            else "FALSE"
        )
        http_only = "FALSE"
        expiration = "1776000000"
        lines.append(
            f"{domain}\tTRUE\t{path}\t{secure_flag}\t{expiration}\t{name}\t{value}"
        )
    return "\n".join(lines)


def main():
    cookies = parse_cookie_string(RAW_COOKIES)
    output = build_cookies_txt(cookies)
    output_path = "/Users/jack/Documents/coding/Translation/youtube-cookies.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Created: {output_path}")
    print(f"Total cookies written: {len(cookies)}")
    print(
        "\nImportant: This file only works AFTER you fix the base network connection to YouTube."
    )
    print(
        "Current issue: curl https://www.youtube.com times out. You need a proxy/VPN first."
    )


if __name__ == "__main__":
    main()

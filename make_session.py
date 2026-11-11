"""Buat file session instaloader dari cookie `sessionid` Instagram.

Cara pakai:
    python make_session.py            # lalu tempel cookie saat diminta

Cookie diambil dari browser yang sudah login Instagram:
    F12 > Application/Storage > Cookies > https://www.instagram.com > sessionid

File hasil: data/session  (perlakukan seperti password, jangan dibagikan)
"""

from __future__ import annotations

import getpass
import sys

import instaloader

import config


def main() -> int:
    username = input("Username akun Instagram yang login: ").strip()
    sessionid = getpass.getpass("Tempel nilai cookie sessionid (tidak akan tampil): ").strip()

    if not username or not sessionid:
        print("Username / sessionid kosong, dibatalkan.")
        return 1
    # Cookie kadang ter-copy dengan tanda kutip atau prefix "sessionid="
    sessionid = sessionid.strip("\"'")
    if sessionid.lower().startswith("sessionid="):
        sessionid = sessionid.split("=", 1)[1]

    L = instaloader.Instaloader(quiet=True)
    L.context._session.cookies.set("sessionid", sessionid, domain=".instagram.com")
    try:
        L.context.username = username
        if not L.test_login():
            print("Cookie tidak valid / sudah kedaluwarsa. Login ulang di browser lalu ambil ulang.")
            return 2
        L.save_session_to_file(config.SESSION_FILE)
    except Exception as exc:
        print(f"Gagal memakai session: {type(exc).__name__}: {exc}")
        return 2

    print(f"OK. Session tersimpan di {config.SESSION_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

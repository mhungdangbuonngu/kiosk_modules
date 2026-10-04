"""Kiem tra bo file mp3 giong doc cua phan huong dan.

Chay:  python kiosk_guide/check_audio.py

- Doi chieu id + loi thoai cac buoc trong tour-config.js voi guide-script.csv.
- Liet ke file mp3 con thieu trong audio/.
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOUR_CONFIG = os.path.join(HERE, "tour-config.js")
SCRIPT_CSV = os.path.join(HERE, "guide-script.csv")
AUDIO_DIR = os.path.join(HERE, "audio")


def tour_steps():
    """(id, say) cac buoc theo dung thu tu khai bao trong tour-config.js."""
    with open(TOUR_CONFIG, encoding="utf-8") as f:
        body = f.read()
    ids = re.findall(r"^\s*id:\s*'([^']+)'", body, re.MULTILINE)
    says = re.findall(r"^\s*say:\s*'([^']*)'", body, re.MULTILINE)
    return list(zip(ids, says)) if len(ids) == len(says) else [(i, None) for i in ids]


def csv_rows():
    with open(SCRIPT_CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    steps = tour_steps()
    ids = [i for i, _ in steps]
    rows = csv_rows()
    problems = 0

    csv_ids = [r["id"] for r in rows]
    if csv_ids != ids:
        problems += 1
        print("[LECH] guide-script.csv khong khop tour-config.js")
        for missing in [i for i in ids if i not in csv_ids]:
            print(f"        thieu trong CSV: {missing}")
        for extra in [i for i in csv_ids if i not in ids]:
            print(f"        thua trong CSV: {extra}")
    else:
        print(f"[OK] CSV khop tour-config.js ({len(ids)} buoc)")

    say_by_id = dict(steps)
    for r in rows:
        say = say_by_id.get(r["id"])
        if say is not None and say != r["text_to_speak"]:
            problems += 1
            print(f"[LECH] loi thoai '{r['id']}' trong CSV khac tour-config.js")

    files = [r["audio_file"] for r in rows]
    missing = [f for f in files if not os.path.isfile(os.path.join(AUDIO_DIR, f))]
    if missing:
        problems += 1
        print(f"[THIEU] con thieu {len(missing)}/{len(files)} file mp3 trong {AUDIO_DIR}")
        for f in missing:
            print(f"        {f}")
    else:
        print(f"[OK] du {len(files)} file mp3")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

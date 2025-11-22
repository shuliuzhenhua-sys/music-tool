import argparse
import json
import os
import re
import subprocess
import imghdr

def _parse_ts(s):
    m = re.match(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]", s)
    if not m:
        return None
    mm = int(m.group(1))
    ss = int(m.group(2))
    ms = m.group(3)
    frac = 0
    if ms is not None:
        if len(ms) == 1:
            frac = int(ms) * 100
        elif len(ms) == 2:
            frac = int(ms) * 10
        else:
            frac = int(ms[:3])
    return mm * 60_000 + ss * 1000 + frac

def _fmt_ts(ms, digits=2):
    if ms < 0:
        ms = 0
    mm = ms // 60_000
    ss = (ms % 60_000) // 1000
    frac = ms % 1000
    if digits == 3:
        return f"[{mm:02d}:{ss:02d}.{frac:03d}]"
    cs = (frac + 5) // 10
    if cs == 100:
        ss += 1
        cs = 0
        if ss == 60:
            mm += 1
            ss = 0
    return f"[{mm:02d}:{ss:02d}.{cs:02d}]"

def read_lrc(path):
    headers = {}
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if re.match(r"^\[[a-zA-Z]+:.*\]$", line):
                k = line[1:line.find(":")]
                v = line[line.find(":")+1:-1]
                headers[k] = v
                continue
            m = re.match(r"^(\[[0-9]{1,2}:[0-9]{2}(?:\.[0-9]{1,3})?\])(.+)$", line)
            if m:
                t = _parse_ts(m.group(1))
                entries.append({"t": t, "text": m.group(2)})
    return headers, entries

def write_lrc(path, headers, entries, digits=2):
    lines = []
    for k in ("ti","ar","al","by","offset","re","ve"):
        if k in headers:
            lines.append(f"[{k}:{headers[k]}]")
    for e in entries:
        lines.append(f"{_fmt_ts(e['t'], digits)}{e['text']}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def ffprobe_info(audio_path):
    try:
        p = subprocess.run(["ffprobe","-v","quiet","-print_format","json","-show_format","-show_streams",audio_path], capture_output=True, check=True)
        data = json.loads(p.stdout.decode())
        fmt = data.get("format",{})
        tags = fmt.get("tags",{})
        return {
            "title": tags.get("title") or tags.get("TITLE"),
            "artist": tags.get("artist") or tags.get("ARTIST"),
            "album": tags.get("album") or tags.get("ALBUM"),
            "duration": float(fmt.get("duration")) if fmt.get("duration") else None
        }
    except Exception:
        return {}

def cmd_info(args):
    h, e = read_lrc(args.lrc)
    ai = ffprobe_info(args.audio) if args.audio else {}
    out = {
        "lrc_headers": h,
        "lrc_lines": len(e),
        "lrc_time_span_ms": (e[-1]["t"]-e[0]["t"]) if e else 0,
        "audio_tags": ai
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

def cmd_set(args):
    h, e = read_lrc(args.lrc)
    if args.ti is not None:
        h["ti"] = args.ti
    if args.ar is not None:
        h["ar"] = args.ar
    if args.al is not None:
        h["al"] = args.al
    if args.by is not None:
        h["by"] = args.by
    write_lrc(args.lrc, h, e, digits=2)
    print(args.lrc)

def cmd_offset(args):
    h, e = read_lrc(args.lrc)
    off = int(args.ms)
    h["offset"] = str(off)
    e2 = []
    for x in e:
        e2.append({"t": x["t"] + off, "text": x["text"]})
    write_lrc(args.lrc, h, e2, digits=2)
    print(args.lrc)

def cmd_sync(args):
    h, e = read_lrc(args.lrc)
    ai = ffprobe_info(args.audio)
    if ai.get("title"):
        h["ti"] = ai["title"]
    if ai.get("artist"):
        h["ar"] = ai["artist"]
    if ai.get("album"):
        h["al"] = ai["album"]
    write_lrc(args.lrc, h, e, digits=2)
    print(args.lrc)

def cmd_export(args):
    h, e = read_lrc(args.lrc)
    obj = {"headers": h, "lines": [{"time_ms": x["t"], "text": x["text"]} for x in e]}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(args.out)

def set_cover(audio_path, cover_path):
    ext = os.path.splitext(cover_path)[1].lower()
    with open(cover_path, "rb") as f:
        data = f.read()
    kind = imghdr.what(None, data)
    mime = "image/jpeg" if kind in ("jpeg","jpg") else ("image/png" if kind == "png" else "image/jpeg")
    if audio_path.lower().endswith(".mp3"):
        from mutagen.id3 import ID3, APIC, error
        from mutagen.mp3 import MP3
        audio = MP3(audio_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass
        audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        audio.save()
        return True
    if audio_path.lower().endswith(".m4a") or audio_path.lower().endswith(".mp4"):
        from mutagen.mp4 import MP4, MP4Cover
        fmt = MP4Cover.FORMAT_JPEG if mime == "image/jpeg" else MP4Cover.FORMAT_PNG
        mp4 = MP4(audio_path)
        mp4["covr"] = [MP4Cover(data, fmt)]
        mp4.save()
        return True
    return False

def cmd_cover(args):
    ok = set_cover(args.audio, args.cover)
    print("OK" if ok else "UNSUPPORTED")

def set_audio_tags(audio_path, ti=None, ar=None, al=None):
    if audio_path.lower().endswith(".mp3"):
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, error
        from mutagen.mp3 import MP3
        audio = MP3(audio_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass
        if ti is not None:
            audio.tags.add(TIT2(encoding=3, text=ti))
        if ar is not None:
            audio.tags.add(TPE1(encoding=3, text=ar))
        if al is not None:
            audio.tags.add(TALB(encoding=3, text=al))
        audio.save()
        return True
    if audio_path.lower().endswith(".m4a") or audio_path.lower().endswith(".mp4"):
        from mutagen.mp4 import MP4
        mp4 = MP4(audio_path)
        if ti is not None:
            mp4["\xa9nam"] = [ti]
        if ar is not None:
            mp4["\xa9ART"] = [ar]
        if al is not None:
            mp4["\xa9alb"] = [al]
        mp4.save()
        return True
    return False

def cmd_atag(args):
    ok = set_audio_tags(args.audio, args.ti, args.ar, args.al)
    print("OK" if ok else "UNSUPPORTED")

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("info")
    sp.add_argument("lrc")
    sp.add_argument("audio", nargs="?")
    sp.set_defaults(func=cmd_info)
    sp = sub.add_parser("set")
    sp.add_argument("lrc")
    sp.add_argument("--ti")
    sp.add_argument("--ar")
    sp.add_argument("--al")
    sp.add_argument("--by")
    sp.set_defaults(func=cmd_set)
    sp = sub.add_parser("offset")
    sp.add_argument("lrc")
    sp.add_argument("ms")
    sp.set_defaults(func=cmd_offset)
    sp = sub.add_parser("sync")
    sp.add_argument("lrc")
    sp.add_argument("audio")
    sp.set_defaults(func=cmd_sync)
    sp = sub.add_parser("export")
    sp.add_argument("lrc")
    sp.add_argument("out")
    sp.set_defaults(func=cmd_export)
    sp = sub.add_parser("cover")
    sp.add_argument("audio")
    sp.add_argument("cover")
    sp.set_defaults(func=cmd_cover)
    sp = sub.add_parser("atag")
    sp.add_argument("audio")
    sp.add_argument("--ti")
    sp.add_argument("--ar")
    sp.add_argument("--al")
    sp.set_defaults(func=cmd_atag)
    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return
    args.func(args)

if __name__ == "__main__":
    main()
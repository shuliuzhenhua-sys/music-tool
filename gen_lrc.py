import os
import re
import sys
import unicodedata

def _is_cjk(ch):
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0x20000 <= o <= 0x2A6DF or 0x2A700 <= o <= 0x2B73F or 0x2B740 <= o <= 0x2B81F or 0x2B820 <= o <= 0x2CEAF

def _normalize(s):
    s = unicodedata.normalize("NFKC", s.lower())
    s = re.sub(r"[^\w一-龥]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(s):
    s = _normalize(s)
    out = []
    buf = []
    for ch in s:
        if _is_cjk(ch):
            if buf:
                out.append("".join(buf))
                buf = []
            out.append(ch)
        elif ch.isalnum() or ch == "_":
            buf.append(ch)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
    if buf:
        out.append("".join(buf))
    return out

def _clean_line(s):
    s = re.sub(r"\[[0-9]{1,2}:[0-9]{2}(?:\.[0-9]{1,3})?\]", "", s)
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"【[^】]+】", "", s)
    s = s.replace("——", "").replace("—", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _fmt_ts(t, ms_digits=3):
    total_ms = int(round(t * 1000))
    if total_ms < 0:
        total_ms = 0
    m = total_ms // 60_000
    s = (total_ms % 60_000) // 1000
    frac = total_ms % 1000
    if ms_digits == 3:
        return f"[{m:02d}:{s:02d}.{frac:03d}]"
    if ms_digits == 2:
        cs = (frac + 5) // 10
        if cs == 100:
            s += 1
            cs = 0
            if s == 60:
                m += 1
                s = 0
        return f"[{m:02d}:{s:02d}.{cs:02d}]"
    if frac >= 500:
        s += 1
        if s == 60:
            m += 1
            s = 0
    return f"[{m:02d}:{s:02d}]"

def _ratio(a, b):
    try:
        from rapidfuzz import fuzz
        return fuzz.ratio(a, b)
    except Exception:
        import difflib
        return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)

def align_tokens(ref, hyp):
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    bt = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
        bt[i][0] = (i - 1, 0)
    for j in range(1, m + 1):
        dp[0][j] = j
        bt[0][j] = (0, j - 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = 0 if ref[i - 1] == hyp[j - 1] else (0 if _ratio(ref[i - 1], hyp[j - 1]) >= 90 else 1)
            a = dp[i - 1][j] + 1
            b = dp[i][j - 1] + 1
            c = dp[i - 1][j - 1] + sub
            if c <= a and c <= b:
                dp[i][j] = c
                bt[i][j] = (i - 1, j - 1)
            elif a <= b:
                dp[i][j] = a
                bt[i][j] = (i - 1, j)
            else:
                dp[i][j] = b
                bt[i][j] = (i, j - 1)
    i, j = n, m
    pairs = []
    while i > 0 or j > 0:
        pi, pj = bt[i][j]
        if pi == i - 1 and pj == j - 1:
            pairs.append((i - 1, j - 1))
        i, j = pi, pj
    pairs.reverse()
    mapping = {}
    for ri, hj in pairs:
        if ri not in mapping:
            mapping[ri] = hj
    return mapping

def _get_words_whisperx(audio_path, device):
    import whisperx
    dev = device
    model = whisperx.load_model("medium", device=dev)
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio)
    lang = result.get("language", "en")
    amodel, meta = whisperx.load_align_model(language_code=lang, device=dev)
    aligned = whisperx.align(result["segments"], amodel, meta, audio, device=dev)
    words = []
    for seg in aligned.get("segments", []):
        for w in seg.get("words", []):
            if w.get("start") is not None and w.get("end") is not None:
                words.append({"text": _normalize(w.get("word", "")), "start": float(w["start"]), "end": float(w["end"])})
    return words

def _get_words_whisper(audio_path, device):
    import whisper
    model = whisper.load_model("medium", device=device)
    result = model.transcribe(audio_path, word_timestamps=True, fp16=False, verbose=False)
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            if w.get("start") is not None and w.get("end") is not None:
                txt = w.get("word") or w.get("text") or ""
                words.append({"text": _normalize(txt), "start": float(w["start"]), "end": float(w["end"])})
    return words

def _get_device():
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def _get_words(audio_path):
    device = _get_device()
    try:
        return _get_words_whisperx(audio_path, device)
    except Exception:
        return _get_words_whisper(audio_path, device)

def generate_lrc(audio_path, lyrics_path, out_path, ms_digits=3):
    words = _get_words(audio_path)
    hyp_tokens = [w["text"] for w in words]
    with open(lyrics_path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f.readlines()]
    clean_lines = []
    for ln in lines:
        cl = _clean_line(ln)
        if cl:
            # Split the cleaned line into sentences based on spaces
            sentences = cl.split(' ')
            for sentence in sentences:
                if sentence:
                    clean_lines.append(sentence)
    line_tokens = [tokenize(ln) for ln in clean_lines]
    ref_tokens = [t for ts in line_tokens for t in ts]
    mapping = align_tokens(ref_tokens, hyp_tokens)
    idx = 0
    line_ranges = []
    for ts in line_tokens:
        start = idx
        end = idx + len(ts) - 1
        line_ranges.append((start, end))
        idx = end + 1
    lrc = []
    for i, (a, b) in enumerate(line_ranges):
        hyp_idxs = [mapping[k] for k in range(a, b + 1) if k in mapping]
        if hyp_idxs:
            s = words[min(hyp_idxs)]["start"]
            lrc.append(f"{_fmt_ts(s, ms_digits)}{clean_lines[i]}")
        else:
            if i > 0 and i < len(line_ranges) - 1:
                prev_range = line_ranges[i - 1]
                next_range = line_ranges[i + 1]
                prev_idxs = [mapping[k] for k in range(prev_range[0], prev_range[1] + 1) if k in mapping]
                next_idxs = [mapping[k] for k in range(next_range[0], next_range[1] + 1) if k in mapping]
                ps = words[min(prev_idxs)]["end"] if prev_idxs else (words[0]["start"] if words else 0.0)
                ns = words[min(next_idxs)]["start"] if next_idxs else (words[-1]["end"] if words else ps)
                s = ps + (ns - ps) * 0.5
                lrc.append(f"{_fmt_ts(s, ms_digits)}{clean_lines[i]}")
            else:
                t = words[0]["start"] if words else 0.0
                lrc.append(f"{_fmt_ts(t, ms_digits)}{clean_lines[i]}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lrc))
    return out_path

def _self_test():
    lines = ["今 天 下 雨", "hello world", "副 歌"]
    lt = [tokenize(x) for x in lines]
    ref = [t for ts in lt for t in ts]
    hyp = ref[:]
    mapping = align_tokens(ref, hyp)
    ok = len(mapping) == len(ref)
    print("SELF_TEST_OK" if ok else "SELF_TEST_FAIL")

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        _self_test()
        sys.exit(0)
    audio_path = sys.argv[1]
    lyrics_path = sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(audio_path)[0] + ".lrc"
    ms_digits = 3
    if len(sys.argv) > 4:
        try:
            ms_digits = int(sys.argv[4])
        except Exception:
            ms_digits = 3
    p = generate_lrc(audio_path, lyrics_path, out_path, ms_digits)
    print(p)
from flask import Flask, request, redirect, send_file
import os
from lrc_app import read_lrc, write_lrc, ffprobe_info, set_cover, _fmt_ts
from werkzeug.utils import secure_filename
import urllib.parse

app = Flask(__name__)

def default_paths():
    base = "/Users/goudan/MyProject/Music2"
    return os.path.join(base, "m.lrc"), os.path.join(base, "m.mp3")

def render_index(lrc_path, audio_path, message=""):
    headers, entries = ({} , [])
    if os.path.exists(lrc_path):
        headers, entries = read_lrc(lrc_path)
    audio = ffprobe_info(audio_path) if os.path.exists(audio_path) else {}
    def hval(k):
        return headers.get(k, "")
    html = f"""
<html><head><meta charset='utf-8'><title>歌词与元信息管理</title>
<style>body{{font-family:sans-serif;max-width:820px;margin:24px auto;padding:0 12px}}label{{display:block;margin:8px 0 4px}}input,button{{font-size:16px}}.row{{margin:10px 0}}.msg{{color:#0a0}}</style></head><body>
<h2>歌词与元信息管理</h2>
<div class='msg'>{message}</div>
<form method='post' action='/save'>
<div class='row'><label>歌词路径</label><input type='text' name='lrc_path' value='{lrc_path}' style='width:100%'/></div>
<form method='post' action='/upload_lrc' enctype='multipart/form-data'><input type='file' name='lrc_file' accept='.lrc,.txt'/><button type='submit'>上传LRC</button></form>
<div class='row'><label>音频路径</label><input type='text' name='audio_path' value='{audio_path}' style='width:100%'/></div>
<form method='post' action='/upload_audio' enctype='multipart/form-data'><input type='file' name='audio_file' accept='audio/*'/><button type='submit'>上传音频</button></form>
<div class='row'><label>标题 ti</label><input type='text' name='ti' value='{hval("ti")}' style='width:100%'/></div>
<div class='row'><label>歌手 ar</label><input type='text' name='ar' value='{hval("ar")}' style='width:100%'/></div>
<div class='row'><label>专辑 al</label><input type='text' name='al' value='{hval("al")}' style='width:100%'/></div>
<div class='row'><label>署名 by</label><input type='text' name='by' value='{hval("by")}' style='width:100%'/></div>
<div class='row'><label>毫秒位数</label><input type='number' name='digits' value='2' min='2' max='3'/></div>
<div class='row'><label>统一偏移 offset(ms)</label><input type='number' name='offset' value='{headers.get("offset", "0")}'/><label><input type='checkbox' name='apply_offset'/>应用到时间轴</label></div>
<div class='row'><button type='submit'>保存</button><a href='/download?lrc_path={lrc_path}' style='margin-left:12px'>下载LRC</a></div>
<hr/>
<h3>音频标签</h3>
<div>title: {audio.get("title","")}</div>
<div>artist: {audio.get("artist","")}</div>
<div>album: {audio.get("album","")}</div>
<div>duration: {audio.get("duration","")}</div>
<form method='post' action='/sync'>
<input type='hidden' name='lrc_path' value='{lrc_path}'/>
<input type='hidden' name='audio_path' value='{audio_path}'/>
<button type='submit'>同步音频标签到LRC</button>
</form>
<form method='post' action='/atag' style='margin-top:12px'>
<input type='hidden' name='audio_path' value='{audio_path}'/>
<label>音频标题</label><input type='text' name='ti' value='{headers.get("ti","")}' style='width:100%'/>
<label>音频歌手</label><input type='text' name='ar' value='{headers.get("ar","")}' style='width:100%'/>
<label>音频专辑</label><input type='text' name='al' value='{headers.get("al","")}' style='width:100%'/>
<button type='submit'>写入到音频文件</button>
</form>
<hr/>
<h3>设置封面</h3>
<form method='post' action='/upload_cover' enctype='multipart/form-data'>
<input type='hidden' name='audio_path' value='{audio_path}'/>
<label>上传封面图片</label>
<input type='file' name='cover_file' accept='image/*'/>
<button type='submit'>上传并设置封面</button>
</form>
<hr/>
<h3>当前歌词预览</h3>
<pre style='white-space:pre-wrap;border:1px solid #ddd;padding:10px'>""" + "\n".join(["{}{}".format(_fmt_ts(x['t'], 2), x['text']) for x in entries]) + """</pre>
</body></html>
"""
    return html

@app.route("/")
def index():
    lrc_default, audio_default = default_paths()
    lrc_path = request.args.get("lrc_path", lrc_default)
    audio_path = request.args.get("audio_path", audio_default)
    return render_index(lrc_path, audio_path)

@app.route("/save", methods=["POST"])
def save():
    lrc_path = request.form.get("lrc_path")
    audio_path = request.form.get("audio_path")
    ti = request.form.get("ti")
    ar = request.form.get("ar")
    al = request.form.get("al")
    by = request.form.get("by")
    digits = int(request.form.get("digits") or 2)
    offset = int(request.form.get("offset") or 0)
    apply_offset = bool(request.form.get("apply_offset"))
    headers, entries = read_lrc(lrc_path) if os.path.exists(lrc_path) else ({}, [])
    if ti is not None:
        headers["ti"] = ti
    if ar is not None:
        headers["ar"] = ar
    if al is not None:
        headers["al"] = al
    if by is not None:
        headers["by"] = by
    headers["offset"] = str(offset)
    if apply_offset:
        entries = [{"t": x["t"] + offset, "text": x["text"]} for x in entries]
    write_lrc(lrc_path, headers, entries, digits=digits)
    return render_index(lrc_path, audio_path, "已保存")

@app.route("/sync", methods=["POST"])
def sync():
    lrc_path = request.form.get("lrc_path")
    audio_path = request.form.get("audio_path")
    headers, entries = read_lrc(lrc_path) if os.path.exists(lrc_path) else ({}, [])
    info = ffprobe_info(audio_path)
    if info.get("title"):
        headers["ti"] = info["title"]
    if info.get("artist"):
        headers["ar"] = info["artist"]
    if info.get("album"):
        headers["al"] = info["album"]
    write_lrc(lrc_path, headers, entries, digits=2)
    return render_index(lrc_path, audio_path, "已同步音频标签")

@app.route("/download")
def download():
    lrc_path = request.args.get("lrc_path")
    return send_file(lrc_path, as_attachment=True)

@app.route("/cover", methods=["POST"])
def cover():
    audio_path = request.form.get("audio_path")
    cover_path = request.form.get("cover_path")
    ok = False
    if audio_path and cover_path and os.path.exists(cover_path) and os.path.exists(audio_path):
        try:
            ok = set_cover(audio_path, cover_path)
        except Exception:
            ok = False
    lrc_default, audio_default = default_paths()
    lrc_path = request.args.get("lrc_path", lrc_default)
    msg = "封面已设置" if ok else "设置失败或格式不支持"
    return render_index(lrc_path, audio_path, msg)

@app.route("/upload_lrc", methods=["POST"])
def upload_lrc():
    file = request.files.get("lrc_file")
    lrc_path, audio_path = default_paths()
    if file and file.filename:
        fn = secure_filename(file.filename)
        ext = os.path.splitext(fn)[1].lower()
        save_path = lrc_path if ext in (".lrc", ".txt") else lrc_path
        file.save(save_path)
        qp_lrc = urllib.parse.quote(save_path)
        qp_audio = urllib.parse.quote(audio_path)
        return redirect(f"/?lrc_path={qp_lrc}&audio_path={qp_audio}")
    return redirect("/")

@app.route("/upload_audio", methods=["POST"])
def upload_audio():
    file = request.files.get("audio_file")
    lrc_path, audio_path = default_paths()
    if file and file.filename:
        fn = secure_filename(file.filename)
        ext = os.path.splitext(fn)[1].lower()
        save_path = audio_path
        if ext in (".m4a", ".mp4"):
            save_path = os.path.join(os.path.dirname(audio_path), "m.m4a")
        file.save(save_path)
        qp_lrc = urllib.parse.quote(lrc_path)
        qp_audio = urllib.parse.quote(save_path)
        return redirect(f"/?lrc_path={qp_lrc}&audio_path={qp_audio}")
    return redirect("/")

@app.route("/upload_cover", methods=["POST"])
def upload_cover():
    audio_path = request.form.get("audio_path")
    file = request.files.get("cover_file")
    lrc_path, audio_default = default_paths()
    ok = False
    if file and file.filename and audio_path and os.path.exists(audio_path):
        fn = secure_filename(file.filename)
        ext = os.path.splitext(fn)[1].lower()
        save_path = os.path.join(os.path.dirname(lrc_path), f"cover{ext or '.jpg'}")
        file.save(save_path)
        try:
            ok = set_cover(audio_path, save_path)
        except Exception:
            ok = False
        msg = "封面已设置" if ok else "设置失败或格式不支持"
        return render_index(lrc_path, audio_path, msg)
    return redirect("/")

@app.route("/atag", methods=["POST"])
def atag():
    audio_path = request.form.get("audio_path")
    ti = request.form.get("ti")
    ar = request.form.get("ar")
    al = request.form.get("al")
    ok = False
    if audio_path and os.path.exists(audio_path):
        try:
            from lrc_app import set_audio_tags
            ok = set_audio_tags(audio_path, ti, ar, al)
        except Exception:
            ok = False
    lrc_default, audio_default = default_paths()
    lrc_path = request.args.get("lrc_path", lrc_default)
    msg = "音频标签已更新" if ok else "写入失败或格式不支持"
    return render_index(lrc_path, audio_path, msg)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port)
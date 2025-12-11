import os, re, tempfile, shutil, uuid, time, hmac, hashlib, json, secrets, subprocess
from datetime import datetime
from flask import Flask, request, send_file, render_template_string, abort, url_for, redirect
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
import yt_dlp, imageio_ffmpeg

DEPLOY_MARK = "PYTHONANYWHERE v7-preview-unlock"

# ffmpeg (sin ffprobe)
ffbin = imageio_ffmpeg.get_ffmpeg_exe()
FFMPEG_DIR = os.path.dirname(ffbin)
os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")
os.environ["FFMPEG_LOCATION"] = FFMPEG_DIR

app = Flask(__name__)

# Require APP_SECRET in production
if not os.environ.get("APP_SECRET"):
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("APP_SECRET environment variable is required in production")
    print("⚠️  WARNING: Using random APP_SECRET (development only)")

SECRET = (os.environ.get("APP_SECRET") or secrets.token_hex(16)).encode()

TMP_BASE = os.path.join(tempfile.gettempdir(), "ytmp3_sessions")
os.makedirs(TMP_BASE, exist_ok=True)
SESSION_TTL = 30 * 60  # 30 min
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE

# ---------- HTMLs ----------
HOME_HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>YT a MP3</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, Arial, sans-serif; max-width: 680px; margin: 2rem auto; padding: 1rem; line-height: 1.5; }
  nav a { display:block; margin:.5rem 0; }
</style>
</head>
<body>
<header><h1>Convertir y recortar audio</h1></header>
<main>
  <nav aria-label="Elegir modo">
    <a href="{{ url_for('youtube_get') }}">Usar enlace de YouTube</a>
    <a href="{{ url_for('upload_get') }}">Subir archivo</a>
  </nav>
</main>
</body>
</html>'''

YOUTUBE_HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Usar enlace de YouTube</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, Arial, sans-serif; max-width: 680px; margin: 2rem auto; padding: 1rem; line-height: 1.5; }
  .group { margin-bottom: 1rem; }
  label { display: block; font-weight: 600; margin-bottom: .25rem; }
  input[type=url] { width: 100%; padding: .65rem; font-size: 1rem; }
  button { padding: .65rem 1rem; font-size: 1rem; cursor: pointer; }
  .hint { font-size: .95rem; }
  .status { margin-top: 1rem; }
  .sr-only { position: absolute; left: -10000px; top: auto; width: 1px; height: 1px; overflow: hidden; }
</style>
</head>
<body>
<header>
  <h1>Usar enlace de YouTube</h1>
  <p><a href="{{ url_for('index') }}">Volver</a></p>
</header>

<main role="main" aria-labelledby="h2">
  <h2 id="h2" class="sr-only">Formulario de conversión</h2>

  <form action="{{ url_for('prepare') }}" method="post" aria-describedby="instrucciones">
    <div id="instrucciones" class="hint">
      Pega un enlace de YouTube y pulsa “Preparar audio”.
    </div>

    <div class="group">
      <label for="url">Enlace de YouTube</label>
      <input id="url" name="url" type="url" inputmode="url" required>
    </div>

    <button type="submit">Preparar audio</button>
    <div id="status" class="status" aria-live="polite"></div>
  </form>
</main>
<script>
  const form = document.querySelector('form');
  const status = document.getElementById('status');
  form.addEventListener('submit', () => {
    if (status) status.textContent = 'Procesando… si el vídeo es largo, puede tardar.';
  });
</script>
</body>
</html>'''

UPLOAD_HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Subir archivo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, Arial, sans-serif; max-width: 680px; margin: 2rem auto; padding: 1rem; line-height: 1.5; }
  .group { margin-bottom: 1rem; }
  label { display: block; font-weight: 600; margin-bottom: .25rem; }
  input[type=file] { width: 100%; padding: .4rem; font-size: 1rem; }
  button { padding: .65rem 1rem; font-size: 1rem; cursor: pointer; }
  .hint { font-size: .95rem; }
  .sr-only { position: absolute; left: -10000px; top: auto; width: 1px; height: 1px; overflow: hidden; }
</style>
</head>
<body>
<header>
  <h1>Subir archivo</h1>
  <p><a href="{{ url_for('index') }}">Volver</a></p>
</header>

<main role="main" aria-labelledby="h2">
  <h2 id="h2" class="sr-only">Formulario de subida</h2>

  <form action="{{ url_for('upload_post') }}" method="post" enctype="multipart/form-data">
    <div class="group">
      <label for="file">Archivo de audio o vídeo</label>
      <input id="file" name="file" type="file" accept="audio/*,video/*" required>
      <div class="hint">Se convertirá a MP3 para editar y descargar.</div>
    </div>
    <button type="submit">Preparar audio</button>
  </form>
</main>
</body>
</html>'''

EDITOR_HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Editar recorte – {{ title }}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, Arial, sans-serif; max-width: 720px; margin: 2rem auto; padding: 1rem; line-height: 1.5; }
  .row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin: .5rem 0; }
  button { padding: .55rem .8rem; font-size: 1rem; cursor: pointer; }
  input[type=text] { padding: .55rem; font-size: 1rem; width: 10ch; }
  label { font-weight: 600; margin-right: .5rem; }
  .hint { font-size: .95rem; margin: .25rem 0 .75rem; }
  .block { margin: 1rem 0; }
  .muted { opacity: .8; }
  .status { margin-top: .5rem; }
  .sr-only { position: absolute; left: -10000px; top: auto; width: 1px; height: 1px; overflow: hidden; }
</style>
</head>
<body>
<header>
  <h1>Editar recorte</h1>
  <div class="muted">{{ title }}</div>
  <div class="muted">Duración inicial: <span id="totalD">{{ duration_str }}</span></div>
  <p><a href="{{ home_url }}">Volver</a></p>
</header>

<main role="main">
  <div class="block">
    <audio id="player" controls preload="metadata" src="{{ audio_url }}">Tu navegador no soporta audio.</audio>
  </div>

  <section class="block" aria-labelledby="navh">
    <h2 id="navh" class="sr-only">Navegación temporal</h2>
    <div class="row">
      <button type="button" data-step="-30">−30 s</button>
      <button type="button" data-step="-5">−5 s</button>
      <button type="button" data-step="-1">−1 s</button>
      <button type="button" data-step="-0.1">−0.1 s</button>
      <button type="button" data-step="0.1">+0.1 s</button>
      <button type="button" data-step="1">+1 s</button>
      <button type="button" data-step="5">+5 s</button>
      <button type="button" data-step="30">+30 s</button>
    </div>
    <div class="hint">Usa los botones para ajustar la posición actual del reproductor.</div>
  </section>

  <section class="block" aria-labelledby="markh">
    <h2 id="markh" class="sr-only">Marcar inicio y fin</h2>
    <div class="row">
      <button type="button" id="markStart">Usar posición como inicio</button>
      <button type="button" id="markEnd">Usar posición como fin</button>
      <button type="button" id="clearSel">Usar todo el audio</button>
    </div>
    <div class="row">
      <label for="start">Inicio</label>
      <input id="start" name="start" type="text" inputmode="numeric" placeholder="mm:ss.sss" value="0:00.000" aria-describedby="fmt">
      <label for="end">Fin</label>
      <input id="end" name="end" type="text" inputmode="numeric" placeholder="mm:ss.sss" value="{{ duration_str }}" data-init-end="{{ duration_str }}">
    </div>
    <div id="fmt" class="hint">Formato: mm:ss.sss o hh:mm:ss.sss</div>
    <div class="row">
      <label><input type="checkbox" id="lock30"> Bloquear a 30 s desde el inicio</label>
      <label><input type="checkbox" id="precise" checked> Corte preciso (recomendado para tonos)</label>
      <label><input type="checkbox" id="fades" checked> Micro-fundidos 5 ms</label>
    </div>
    <div id="live" class="status" aria-live="polite"></div>
  </section>

  <!-- Formulario de recorte -->
  <form class="block" action="{{ trim_url }}" method="post">
    <input type="hidden" name="id" value="{{ sid }}">
    <input type="hidden" name="sig" value="{{ sig }}">
    <input type="hidden" id="start_h" name="start">
    <input type="hidden" id="end_h" name="end">
    <input type="hidden" id="ringtone_h" name="ringtone_mode" value="false">
    <input type="hidden" id="precise_h" name="precise" value="true">
    <input type="hidden" id="fades_h" name="fades" value="true">
    <div class="row">
      <button type="button" id="previewClip">Previsualizar recorte</button>
      <button type="submit">Recortar y descargar</button>
    </div>
  </form>

  <!-- Cancelar como POST -->
  <form class="block" action="{{ cancel_url }}" method="post">
    <input type="hidden" name="id" value="{{ sid }}">
    <input type="hidden" name="sig" value="{{ sig_cancel }}">
    <button type="submit">Cancelar</button>
  </form>
</main>

<script>
  const player = document.getElementById('player');
  const live = document.getElementById('live');
  const startI = document.getElementById('start');
  const endI = document.getElementById('end');
  const startH = document.getElementById('start_h');
  const endH = document.getElementById('end_h');
  const lock30 = document.getElementById('lock30');
  const precise = document.getElementById('precise');
  const fades = document.getElementById('fades');
  const ringtoneH = document.getElementById('ringtone_h');
  const preciseH = document.getElementById('precise_h');
  const fadesH = document.getElementById('fades_h');
  const previewBtn = document.getElementById('previewClip');
  const clearBtn = document.getElementById('clearSel');

  function fmt(t) {
    if (!isFinite(t) || t < 0) t = 0;
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = (t % 60);
    const sStr = s.toFixed(3).padStart(6,'0');
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${sStr.padStart(6,'0')}`;
    return `${m}:${sStr.padStart(6,'0')}`;
  }
  function parseTime(str) {
    if (!str) return NaN;
    const parts = str.split(':');
    if (parts.length === 1) return parseFloat(parts[0]) || NaN;
    if (parts.length === 2) {
      const m = parseInt(parts[0],10); const s = parseFloat(parts[1]);
      if (isNaN(m) || isNaN(s)) return NaN; return m*60 + s;
    }
    if (parts.length === 3) {
      const h = parseInt(parts[0],10), m = parseInt(parts[1],10), s = parseFloat(parts[2]);
      if ([h,m,s].some(isNaN)) return NaN; return h*3600 + m*60 + s;
    }
    return NaN;
  }
  function announce() {
    const st = parseTime(startI.value);
    const en = parseTime(endI.value);
    if (isFinite(st) && isFinite(en) && en > st) {
      const dur = en - st;
      live.textContent = `Inicio ${startI.value}. Fin ${endI.value}. Duración del recorte: ${fmt(dur)}.`;
    }
    startH.value = startI.value;
    endH.value = endI.value;
    ringtoneH.value = lock30.checked ? "true" : "false";
    preciseH.value = precise.checked ? "true" : "false";
    fadesH.value = fades.checked ? "true" : "false";
  }
  function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }

  // Ajustar Fin a la duración real si nadie lo cambió aún
  player.addEventListener('loadedmetadata', ()=>{
    const d = player.duration;
    if (Number.isFinite(d) && endI.value === endI.dataset.initEnd) {
      endI.value = fmt(d);
      document.getElementById('totalD').textContent = fmt(d);
      announce();
    }
  });

  // Estado de previsualización
  let previewing = false;
  let nextPlayIsPreview = false;

  // Al reproducir con el control nativo: por defecto NO es previsualización
  player.addEventListener('play', ()=>{
    previewing = nextPlayIsPreview;
    nextPlayIsPreview = false;
  });

  // Al pausar de cualquier forma: salir de previsualización
  player.addEventListener('pause', ()=>{
    previewing = false;
  });

  function onChangeLimitsLive(){
    if (!previewing) return;
    const st = parseTime(startI.value), en = parseTime(endI.value);
    if (!(isFinite(st) && isFinite(en) && en > st)) {
      previewing = false; player.pause(); return;
    }
    if (player.currentTime < st || player.currentTime > en) {
      player.currentTime = st;
      const p = player.play(); if (p && p.catch) p.catch(()=>{});
    }
  }

  document.querySelectorAll('button[data-step]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const step = parseFloat(btn.getAttribute('data-step'));
      const d = isFinite(player.duration) ? player.duration : 0;
      player.currentTime = clamp((player.currentTime||0)+step, 0, d || 0);
      announce();
      onChangeLimitsLive();
    });
  });

  document.getElementById('markStart').addEventListener('click', ()=>{
    const pos = player.currentTime || 0;
    startI.value = fmt(pos);
    if (lock30.checked) {
      const d = isFinite(player.duration) ? player.duration : null;
      if (d != null) endI.value = fmt(Math.min(pos + 30.0, d));
    }
    announce();
    onChangeLimitsLive();
  });
  document.getElementById('markEnd').addEventListener('click', ()=>{
    const pos = player.currentTime || 0;
    endI.value = fmt(pos);
    announce();
    onChangeLimitsLive();
  });

  clearBtn.addEventListener('click', ()=>{
    const d = Number.isFinite(player.duration) ? player.duration : null;
    if (!d) return;
    previewing = false;          // corta cualquier previsualización
    player.pause();
    player.currentTime = 0;
    lock30.checked = false;
    endI.readOnly = false;
    startI.value = "0:00.000";
    endI.value = fmt(d);
    announce();
    live.textContent = 'Selección anulada. Usando todo el audio.';
  });

  lock30.addEventListener('change', ()=>{
    const ro = lock30.checked;
    endI.readOnly = ro;
    if (ro) {
      const st = parseTime(startI.value);
      const d = isFinite(player.duration) ? player.duration : null;
      if (isFinite(st) && d != null) endI.value = fmt(Math.min(st + 30.0, d));
    }
    announce();
    onChangeLimitsLive();
  });
  startI.addEventListener('input', ()=>{
    if (lock30.checked) {
      const st = parseTime(startI.value);
      const d = isFinite(player.duration) ? player.duration : null;
      if (isFinite(st) && d != null) endI.value = fmt(Math.min(Math.max(st,0) + 30.0, d));
    }
    announce();
    onChangeLimitsLive();
  });
  endI.addEventListener('input', ()=>{
    if (lock30.checked) { lock30.checked = false; endI.readOnly = false; }
    announce();
    onChangeLimitsLive();
  });

  // Parar al llegar a fin de la previsualización. No recolocar al inicio.
  player.addEventListener('timeupdate', ()=>{
    if (!previewing) return;
    const st = parseTime(startI.value), en = parseTime(endI.value);
    if (!(isFinite(st) && isFinite(en) && en > st)) { previewing=false; player.pause(); return; }
    if (player.currentTime >= en - 0.0005) {
      previewing = false;
      player.pause();
      live.textContent = 'Previsualización finalizada.';
    }
  });

  // Botón de previsualización
  previewBtn.addEventListener('click', ()=>{
    const st = parseTime(startI.value);
    const en = parseTime(endI.value);
    if (!(isFinite(st) && isFinite(en) && en > st)) {
      live.textContent = 'Selecciona inicio y fin válidos para previsualizar.';
      return;
    }
    player.currentTime = st;
    nextPlayIsPreview = true; // marca que el próximo play es de previsualización
    const p = player.play(); if (p && p.catch) p.catch(()=>{});
    live.textContent = `Reproduciendo recorte ${startI.value} → ${endI.value}.`;
  });

  window.addEventListener('load', ()=>{
    endI.readOnly = false;
    announce();
  });
</script>
</body>
</html>'''

# ---------- util firmas/sesiones ----------
def sign_token(id_str: str, scope: str) -> str:
    return hmac.new(SECRET, f"{id_str}:{scope}".encode(), hashlib.sha256).hexdigest()

def verify_token(id_str: str, scope: str, token: str) -> bool:
    try:
        expected = sign_token(id_str, scope)
        return hmac.compare_digest(expected, token)
    except Exception:
        return False

def sess_dir(sid: str) -> str:
    return os.path.join(TMP_BASE, sid)

_last_cleanup = 0
CLEANUP_INTERVAL = 300  # 5 min

def cleanup_expired():
    """Cleanup expired sessions. Only runs every CLEANUP_INTERVAL seconds."""
    global _last_cleanup
    now = time.time()
    
    # Skip if cleaned up recently
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return
    
    _last_cleanup = now
    try:
        for name in os.listdir(TMP_BASE):
            p = os.path.join(TMP_BASE, name)
            if not os.path.isdir(p): continue
            try:
                mtime = os.path.getmtime(p)
                if now - mtime > SESSION_TTL:
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    except FileNotFoundError:
        pass

# ---------- validación y helpers ----------
YTLINK = re.compile(r'^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be)/', re.I)

UA_ANDROID = "com.google.android.youtube/19.20.34 (Linux; Android 14)"
CLIENTS = [
    ("android", UA_ANDROID),
    ("mweb", "Mozilla/5.0 (Linux; Android 14; Mobile)"),
    ("web_music", "Mozilla/5.0"),
]

def hhmmss_from_seconds(s: float) -> str:
    s = max(0.0, float(s))
    h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
    return f"{h}:{m:02d}:{sec:06.3f}" if h>0 else f"{m}:{sec:06.3f}"

def parse_time_to_seconds(txt: str) -> float:
    txt = (txt or "").strip()
    if not txt: return float("nan")
    parts = txt.split(":")
    try:
        if len(parts)==1: return float(parts[0])
        if len(parts)==2: return int(parts[0])*60 + float(parts[1])
        if len(parts)==3: return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
    except Exception:
        return float("nan")
    return float("nan")

def ffmpeg_to_mp3(src: str, dst: str):
    args = [ffbin, "-hide_banner", "-nostdin", "-y", "-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "0", dst]
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst)==0:
        msg = proc.stderr.decode(errors="ignore")[-400:]
        abort(500, f"FFmpeg falló al convertir a MP3: {msg}")

def run_ffmpeg_trim(src: str, dst: str, start: float, end: float, precise: bool, fades: bool):
    if end <= start:
        abort(400, "El tiempo de fin debe ser mayor que el de inicio")
    clip_len = end - start
    if clip_len < 0.01:
        abort(400, "El recorte debe tener al menos 0.01 s")

    args = [ffbin, "-hide_banner", "-nostdin", "-y"]
    if precise:
        # Recorte en filtros + fades con tiempo relativo seguro.
        filters = [f"atrim=start={start:.6f}:end={end:.6f}", "asetpts=PTS-STARTPTS"]
        if fades:
            out_st = max(0.0, clip_len - 0.005)
            filters.append("afade=t=in:d=0.005")
            filters.append(f"afade=t=out:st={out_st:.6f}:d=0.005")
        args += ["-i", src, "-af", ",".join(filters), "-c:a", "libmp3lame", "-q:a", "0", dst]
    else:
        # Rápido, sin recodificar.
        args += ["-ss", f"{start:.6f}", "-to", f"{end:.6f}", "-i", src, "-c", "copy", dst]

    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst)==0:
        msg = proc.stderr.decode(errors="ignore")[-400:]
        abort(500, f"FFmpeg falló al recortar: {msg}")

def yt_extract_then_download(url: str, outtmpl: str):
    base_common = {
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "concurrent_fragment_downloads": 1,
        "geo_bypass": True,
        "ffmpeg_location": FFMPEG_DIR,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_UPLOAD_SIZE,  # Limit download size
    }
    info = None; chosen = None; last_err = None

    for client, ua in CLIENTS:
        opts_info = dict(base_common)
        opts_info.update({
            "user_agent": ua,
            "http_headers": {"User-Agent": ua},
            "extractor_args": {"youtube": {"player_client": [client]}},
        })
        try:
          with yt_dlp.YoutubeDL(opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
          chosen = (client, ua)
          break
        except yt_dlp.utils.DownloadError as e:
          last_err = e

    if info is None:
        raise last_err if last_err else RuntimeError("No se pudo extraer información del vídeo")

    duration = float(info.get("duration") or 0.0)
    client, ua = chosen
    opts_dl = dict(base_common)
    opts_dl.update({
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "user_agent": ua,
        "http_headers": {"User-Agent": ua},
        "extractor_args": {"youtube": {"player_client": [client]}},
    })
    with yt_dlp.YoutubeDL(opts_dl) as ydl:
        result = ydl.extract_info(url, download=True)
        media_path = ydl.prepare_filename(result)

    return {"title": info.get("title") or "audio", "duration": duration}, media_path

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
def probe_duration_seconds(path: str) -> float:
    try:
        proc = subprocess.run([ffbin, "-hide_banner", "-nostdin", "-i", path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        m = _DURATION_RE.search(proc.stderr.decode(errors="ignore"))
        if not m: return 0.0
        h = int(m.group(1)); m_ = int(m.group(2)); s = float(m.group(3))
        return h*3600 + m_*60 + s
    except Exception:
        return 0.0

def derive_title_from_filename(filename: str) -> str:
    name = os.path.basename(filename or "").strip()
    name = secure_filename(name)
    base, _ = os.path.splitext(name)
    base = base.strip()
    return base or "audio"

def safe_download_name(base: str) -> str:
    base = (base or "audio")
    base = re.sub(r'[\\/:*?"<>|]+', '_', base).strip()
    base = re.sub(r'\s+', ' ', base)
    return base or "audio"

# ---------- rutas ----------
@app.get("/")
def index():
    cleanup_expired()
    print("DEPLOY_MARK:", DEPLOY_MARK, flush=True)
    print("yt-dlp:", yt_dlp.version.__version__, flush=True)
    return render_template_string(HOME_HTML)

@app.get("/youtube")
def youtube_get():
    return render_template_string(YOUTUBE_HTML)

@app.get("/upload")
def upload_get():
    return render_template_string(UPLOAD_HTML)

@app.post("/prepare")
def prepare():
    cleanup_expired()
    url = (request.form.get("url") or "").strip()
    if not YTLINK.match(url):
        abort(400, "URL no válida. Debe ser de youtube.com o youtu.be")
    url = re.sub(r'(\?|&)si=[^&]+', '', url)

    sid = uuid.uuid4().hex
    sdir = os.path.join(TMP_BASE, sid)
    os.makedirs(sdir, exist_ok=True)
    outtmpl = os.path.join(sdir, "%(title).200B.%(ext)s")

    try:
        info, media_path = yt_extract_then_download(url, outtmpl)
    except HTTPException:
        shutil.rmtree(sdir, ignore_errors=True); raise
    except Exception as e:
        shutil.rmtree(sdir, ignore_errors=True)
        abort(502, f"yt-dlp: {str(e)[:300]}")

    if not (media_path and os.path.exists(media_path)):
        shutil.rmtree(sdir, ignore_errors=True)
        abort(500, "No se descargó el audio")

    src_mp3 = os.path.join(sdir, "source.mp3")
    ffmpeg_to_mp3(media_path, src_mp3)
    try:
        if os.path.exists(media_path): os.remove(media_path)
    except Exception:
        pass

    duration = float(info.get("duration") or 0.0)
    meta = {"title": info.get("title") or "audio", "duration": duration, "created": datetime.utcnow().isoformat() + "Z"}
    with open(os.path.join(sdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    return render_template_string(
        EDITOR_HTML,
        title=meta["title"],
        duration_str=hhmmss_from_seconds(duration),
        audio_url=url_for("audio_stream", sid=sid, sig=sign_token(sid, "audio")),
        sid=sid,
        sig=sign_token(sid, "trim"),
        sig_cancel=sign_token(sid, "cancel"),
        trim_url=url_for("trim"),
        cancel_url=url_for("cancel"),
        home_url=url_for("index"),
    )

@app.post("/upload")
def upload_post():
    cleanup_expired()
    if "file" not in request.files:
        abort(400, "No se envió archivo")
    f = request.files["file"]
    if not f or not f.filename:
        abort(400, "Archivo inválido")

    sid = uuid.uuid4().hex
    sdir = os.path.join(TMP_BASE, sid)
    os.makedirs(sdir, exist_ok=True)

    original_path = os.path.join(sdir, "input")
    try:
        f.save(original_path)
    except Exception as e:
        shutil.rmtree(sdir, ignore_errors=True)
        abort(500, f"No se pudo guardar el archivo: {e}")

    title = derive_title_from_filename(f.filename)

    src_mp3 = os.path.join(sdir, "source.mp3")
    try:
        ffmpeg_to_mp3(original_path, src_mp3)
        os.remove(original_path)
    except HTTPException:
        shutil.rmtree(sdir, ignore_errors=True); raise
    except Exception as e:
        shutil.rmtree(sdir, ignore_errors=True)
        abort(500, f"FFmpeg fallo: {str(e)[:300]}")

    duration = probe_duration_seconds(src_mp3)

    meta = {"title": title, "duration": float(duration or 0.0), "created": datetime.utcnow().isoformat() + "Z"}
    with open(os.path.join(sdir, "meta.json"), "w", encoding="utf-8") as jf:
        json.dump(meta, jf, ensure_ascii=False)

    return render_template_string(
        EDITOR_HTML,
        title=meta["title"],
        duration_str=hhmmss_from_seconds(meta["duration"]),
        audio_url=url_for("audio_stream", sid=sid, sig=sign_token(sid, "audio")),
        sid=sid,
        sig=sign_token(sid, "trim"),
        sig_cancel=sign_token(sid, "cancel"),
        trim_url=url_for("trim"),
        cancel_url=url_for("cancel"),
        home_url=url_for("index"),
    )

@app.get("/audio/<sid>")
def audio_stream(sid):
    sig = request.args.get("sig", "")
    if not verify_token(sid, "audio", sig):
        abort(403, "Token inválido")
    sdir = sess_dir(sid)
    src = os.path.join(sdir, "source.mp3")
    if not os.path.exists(src):
        abort(410, "Sesión no encontrada o expirada")
    try: os.utime(sdir, None)
    except Exception: pass
    resp = send_file(src, mimetype="audio/mpeg", as_attachment=False, download_name="source.mp3")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp

@app.post("/trim")
def trim():
    cleanup_expired()
    sid = (request.form.get("id") or "").strip()
    sig = (request.form.get("sig") or "").strip()
    if not verify_token(sid, "trim", sig):
        abort(403, "Token inválido")

    sdir = sess_dir(sid)
    meta_path = os.path.join(sdir, "meta.json")
    src = os.path.join(sdir, "source.mp3")
    if not (os.path.isdir(sdir) and os.path.exists(src) and os.path.exists(meta_path)):
        shutil.rmtree(sdir, ignore_errors=True)
        abort(410, "Sesión no encontrada o expirada")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    duration = float(meta.get("duration") or 0.0)

    start_txt = request.form.get("start") or ""
    end_txt = request.form.get("end") or ""
    ringtone_mode = (request.form.get("ringtone_mode") or "false").lower() == "true"
    precise = (request.form.get("precise") or "true").lower() == "true"
    fades = (request.form.get("fades") or "true").lower() == "true"

    start = parse_time_to_seconds(start_txt)
    end = parse_time_to_seconds(end_txt)

    if ringtone_mode:
        if not (start == start):
            abort(400, "Inicio inválido")
        if duration: end = min(start + 30.0, duration)
        else: end = start + 30.0
    else:
        if not (start == start) or not (end == end):
            abort(400, "Tiempos inválidos")

    if start < 0: start = 0.0
    if duration and start >= duration: start = max(duration - 0.1, 0.0)
    if duration and end > duration: end = duration
    if end - start <= 0.01: abort(400, "El recorte debe tener al menos 0.01 s")

    dst = os.path.join(sdir, "cut.mp3")
    run_ffmpeg_trim(src, dst, start, end, precise or ringtone_mode, fades if (precise or ringtone_mode) else False)

    base = safe_download_name(meta.get("title") or "audio")
    filename = f"{base}-tono30s.mp3" if ringtone_mode else f"{base}-clip.mp3"
    resp = send_file(dst, as_attachment=True, download_name=filename)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"

    @resp.call_on_close
    def _cleanup():
        try: shutil.rmtree(sdir, ignore_errors=True)
        except Exception: pass

    return resp

@app.post("/cancel")
def cancel():
    sid = (request.form.get("id") or "").strip()
    sig = (request.form.get("sig") or "").strip()
    if not verify_token(sid, "cancel", sig):
        abort(403, "Token inválido")
    sdir = sess_dir(sid)
    shutil.rmtree(sdir, ignore_errors=True)
    return redirect(url_for("index"))

# Descarga directa completa sin editor (fallback)
@app.post("/download")
def legacy_download():
    url = (request.form.get("url") or "").strip()
    if not YTLINK.match(url):
        abort(400, "URL no válida. Debe ser de youtube.com o youtu.be")
    url = re.sub(r'(\?|&)si=[^&]+', "", url)

    tmpdir = tempfile.mkdtemp(prefix="ytmp3_legacy_")
    outtmpl = os.path.join(tmpdir, "%(title).200B.%(ext)s")
    try:
        info, media_path = yt_extract_then_download(url, outtmpl)
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True); raise
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        abort(502, f"yt-dlp: {str(e)[:300]}")

    if not (media_path and os.path.exists(media_path)):
        shutil.rmtree(tmpdir, ignore_errors=True)
        abort(500, "No se descargó el audio")

    mp3_path = os.path.join(tmpdir, "audio.mp3")
    ffmpeg_to_mp3(media_path, mp3_path)
    try:
        if os.path.exists(media_path): os.remove(media_path)
    except Exception:
        pass

    resp = send_file(mp3_path, as_attachment=True, download_name="audio.mp3")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"

    @resp.call_on_close
    def _cleanup():
        try:
            if os.path.exists(mp3_path): os.remove(mp3_path)
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    return resp

if __name__ == "__main__":
  port = int(os.getenv("PORT", "8080"))
  app.run(host="0.0.0.0", port=port)

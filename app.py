# -*- coding: utf-8 -*-
import os, re, tempfile, shutil, uuid, time, hmac, hashlib, json, secrets, subprocess, threading
from datetime import datetime, timezone
from flask import Flask, request, send_file, render_template_string, abort, url_for, redirect, Response, stream_with_context
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
import yt_dlp, imageio_ffmpeg

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
    print("WARNING: Using random APP_SECRET (development only)")

SECRET = (os.environ.get("APP_SECRET") or secrets.token_hex(16)).encode()

TMP_BASE = os.path.join(tempfile.gettempdir(), "ytmp3_sessions")
os.makedirs(TMP_BASE, exist_ok=True)
SESSION_TTL = 30 * 60  # 30 min
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB
RINGTONE_SECONDS = 29.0  # iOS rechaza tonos de 30 s o más: debe ser < 30
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE

# Sistema de progreso para SSE
progress_store = {}  # {session_id: {"progress": 0-100, "message": str, "status": str, "error": str}}
progress_lock = threading.Lock()
PROGRESS_TTL = 60 * 60  # 1 h: purga entradas de progreso huérfanas

# Límite de descargas de YouTube simultáneas (evita saturar el servidor)
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "3"))
download_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_DOWNLOADS)

# ---------- HTMLs ----------
HOME_HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Convertir y recortar audio</title>
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
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  .hint { font-size: .95rem; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
  .progress-container { display: none; margin-top: 1.5rem; padding: 1rem; background: #f5f5f5; border-radius: 8px; }
  .progress-container.active { display: block; }
  .progress-label { display: flex; justify-content: space-between; margin-bottom: 0.5rem; font-weight: 600; }
  .progress-percentage { color: #00509e; font-size: 1.1rem; }
  .progress-bar { width: 100%; height: 24px; background: #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: inset 0 1px 3px rgba(0,0,0,0.2); }
  .progress-fill { height: 100%; background: linear-gradient(90deg, #0066cc, #0088ff); border-radius: 12px; transition: width 0.3s ease; position: relative; }
  .progress-fill::after { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent); animation: shimmer 2s infinite; }
  @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
  .progress-message { margin-top: 0.5rem; font-size: 0.9rem; color: #595959; font-style: italic; }
  .progress-bar.complete .progress-fill { background: linear-gradient(90deg, #4caf50, #66bb6a); }
  .progress-bar.error .progress-fill { background: linear-gradient(90deg, #f44336, #e57373); }
  @media (prefers-color-scheme: dark) {
    .progress-container { background: #2a2a2a; }
    .progress-bar { background: #1a1a1a; }
    .progress-message { color: #b0b0b0; }
  }
  @media (prefers-reduced-motion: reduce) {
    .progress-fill, .progress-fill::after { animation: none; transition: none; }
  }
</style>
</head>
<body>
<header>
  <h1>Usar enlace de YouTube</h1>
  <p><a href="{{ url_for('index') }}">Volver</a></p>
</header>
<main role="main" aria-labelledby="h2">
  <h2 id="h2" class="sr-only">Formulario de conversión</h2>
  <form id="prepareForm" aria-describedby="instrucciones">
    <div id="instrucciones" class="hint">Pega un enlace de YouTube y pulsa "Preparar audio".</div>
    <div class="group">
      <label for="url">Enlace de YouTube</label>
      <input id="url" name="url" type="url" inputmode="url" required>
      <button type="button" id="pasteBtn">Pegar enlace</button>
    </div>
    <button type="submit" id="submitBtn">Preparar audio</button>
  </form>
  <div role="alert" aria-live="assertive" class="sr-only" id="alertRegion"></div>
  <div id="progressContainer" class="progress-container" role="region" aria-label="Progreso de procesamiento">
    <div aria-live="polite" aria-atomic="true" class="sr-only" id="announcer"></div>
    <div class="progress-label">
      <span id="progressStatus">Preparando</span>
      <span class="progress-percentage" id="progressPercent">0%</span>
    </div>
    <div id="progressBar" class="progress-bar" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" aria-labelledby="progressStatus">
      <div class="progress-fill" id="progressFill" style="width: 0%">
        <span class="sr-only" id="progressSR">0% completado</span>
      </div>
    </div>
    <div class="progress-message" id="progressMessage"></div>
  </div>
</main>
<script>
(function() {
  const form = document.getElementById('prepareForm');
  const submitBtn = document.getElementById('submitBtn');
  const progressContainer = document.getElementById('progressContainer');
  const progressBar = document.getElementById('progressBar');
  const progressFill = document.getElementById('progressFill');
  const progressPercent = document.getElementById('progressPercent');
  const progressMessage = document.getElementById('progressMessage');
  const progressStatus = document.getElementById('progressStatus');
  const progressSR = document.getElementById('progressSR');
  const announcer = document.getElementById('announcer');
  const alertRegion = document.getElementById('alertRegion');
  let lastAnnouncedProgress = -1;
  let eventSource = null;
  const urlInput = document.getElementById('url');
  const pasteBtn = document.getElementById('pasteBtn');
  pasteBtn.addEventListener('click', async function() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        urlInput.value = text.trim();
        urlInput.focus();
        alertRegion.textContent = 'Enlace pegado.';
      } else {
        alertRegion.textContent = 'El portapapeles está vacío.';
      }
    } catch (err) {
      alertRegion.textContent = 'No se pudo acceder al portapapeles. Pega el enlace manualmente.';
      urlInput.focus();
    }
  });
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    const url = document.getElementById('url').value.trim();
    if (!url) return;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Procesando...';
    progressContainer.classList.add('active');
    updateProgress(0, 'Iniciando procesamiento...', 'preparing');
    fetch('{{ url_for("prepare") }}', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'url=' + encodeURIComponent(url)
    })
    .then(r => r.json())
    .then(data => {
      if (data.error) { showError(data.error); return; }
      const sid = data.session_id;
      eventSource = new EventSource('{{ url_for("progress_stream", sid="") }}' + sid + '?sig=' + encodeURIComponent(data.sig));
      eventSource.addEventListener('progress', function(e) {
        const data = JSON.parse(e.data);
        updateProgress(data.progress, data.message, data.status);
      });
      eventSource.addEventListener('complete', function(e) {
        const data = JSON.parse(e.data);
        eventSource.close();
        window.location.href = data.editor_url;
      });
      eventSource.addEventListener('error_event', function(e) {
        const data = JSON.parse(e.data);
        eventSource.close();
        showError(data.error);
      });
      eventSource.onerror = function() {
        eventSource.close();
        showError('Error de conexión. Por favor, intenta de nuevo.');
      };
    })
    .catch(err => { showError('Error: ' + err.message); });
  });
  function updateProgress(progress, message, status) {
    progress = Math.min(Math.max(progress, 0), 100);
    progressFill.style.width = progress + '%';
    progressPercent.textContent = Math.round(progress) + '%';
    progressMessage.textContent = message;
    progressBar.setAttribute('aria-valuenow', progress);
    progressSR.textContent = Math.round(progress) + '% completado';
    if (status === 'complete') {
      progressBar.classList.add('complete');
      progressStatus.textContent = 'Completado';
    } else if (status === 'error') {
      progressBar.classList.add('error');
      progressStatus.textContent = 'Error';
    } else {
      progressStatus.textContent = 'Procesando';
    }
    const roundedProgress = Math.floor(progress / 25) * 25;
    if (roundedProgress !== lastAnnouncedProgress && roundedProgress > 0) {
      lastAnnouncedProgress = roundedProgress;
      announcer.textContent = 'Progreso: ' + roundedProgress + '%';
    }
  }
  function showError(error) {
    updateProgress(0, error, 'error');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Preparar audio';
    alertRegion.textContent = 'Error: ' + error;
    setTimeout(() => {
      progressContainer.classList.remove('active');
      progressBar.classList.remove('error');
    }, 5000);
  }
})();
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
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
</style>
</head>
<body>
<header>
  <h1>Subir archivo</h1>
  <p><a href="{{ url_for('index') }}">Volver</a></p>
</header>

<main role="main" aria-labelledby="h2">
  <h2 id="h2" class="sr-only">Formulario de subida</h2>

  <form id="uploadForm" action="{{ url_for('upload_post') }}" method="post" enctype="multipart/form-data">
    <div class="group">
      <label for="file">Archivo de audio o vídeo</label>
      <input id="file" name="file" type="file" accept="audio/*,video/*" required>
      <div class="hint">Se convertirá a MP3 para editar y descargar.</div>
    </div>
    <button type="submit" id="uploadBtn">Preparar audio</button>
    <p id="uploadStatus" class="hint" role="status" aria-live="polite"></p>
  </form>
</main>
<script>
(function(){
  const form = document.getElementById('uploadForm');
  const btn = document.getElementById('uploadBtn');
  const status = document.getElementById('uploadStatus');
  form.addEventListener('submit', function(){
    // No bloqueamos el envío nativo; solo damos feedback mientras se procesa.
    status.textContent = 'Subiendo y procesando el archivo. Esto puede tardar un poco; por favor, espera…';
    setTimeout(function(){ btn.disabled = true; btn.textContent = 'Procesando…'; }, 0);
  });
})();
</script>
</body>
</html>'''

EDITOR_HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Editar audio – {{ title }}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, Arial, sans-serif; max-width: 720px; margin: 2rem auto; padding: 1rem; line-height: 1.5; }
  h2 { font-size: 1.15rem; margin: .25rem 0 .5rem; }
  .row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin: .5rem 0; }
  button { padding: .6rem .9rem; font-size: 1rem; min-height: 44px; cursor: pointer; }
  .primary { font-weight: 700; }
  input[type=text] { padding: .55rem; font-size: 1rem; width: 9ch; min-height: 44px; }
  .lbl { font-weight: 600; min-width: 3.5em; display: inline-block; }
  .hint { font-size: .95rem; margin: .25rem 0 .75rem; }
  .timeval { font-size: 1.05rem; margin: .5rem 0; }
  .block { margin: 1.25rem 0; padding-top: .5rem; border-top: 1px solid rgba(128,128,128,.25); }
  .muted { opacity: .85; }
  .status { margin-top: .5rem; }
  details summary { cursor: pointer; font-weight: 600; }
  audio { width: 100%; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
</style>
</head>
<body>
<header>
  <h1>Editar audio</h1>
  <div class="muted">{{ title }}</div>
  <div class="muted">Duración total: <span id="totalD">{{ duration_str }}</span></div>
  <p><a href="{{ home_url }}">Volver al inicio</a></p>
</header>

<main role="main">
  <div id="live" class="sr-only" aria-live="polite" aria-atomic="true"></div>
  <div id="alert" class="sr-only" role="alert" aria-live="assertive"></div>

  <section class="block" aria-labelledby="playh">
    <h2 id="playh">1. Reproducir y buscar</h2>
    <audio id="player" controls preload="metadata" src="{{ audio_url }}" aria-label="Reproductor de audio: {{ title }}">Tu navegador no soporta audio.</audio>
    <p class="timeval">Posición actual: <strong id="curPos">0:00.0</strong></p>
    <div class="row" role="group" aria-label="Mover la posición del reproductor">
      <button type="button" data-step="-5" aria-label="Retroceder 5 segundos">−5 s</button>
      <button type="button" data-step="-1" aria-label="Retroceder 1 segundo">−1 s</button>
      <button type="button" data-step="-0.1" aria-label="Retroceder una décima de segundo">−0.1 s</button>
      <button type="button" data-step="0.1" aria-label="Avanzar una décima de segundo">+0.1 s</button>
      <button type="button" data-step="1" aria-label="Avanzar 1 segundo">+1 s</button>
      <button type="button" data-step="5" aria-label="Avanzar 5 segundos">+5 s</button>
    </div>
  </section>

  <section class="block" aria-labelledby="markh">
    <h2 id="markh">2. Marcar inicio y fin</h2>
    <p class="hint">Reproduce el audio y, al llegar al punto que quieras, pulsa el botón correspondiente.</p>
    <div class="row">
      <button type="button" id="markStart" class="primary">Marcar inicio aquí</button>
      <button type="button" id="markEnd" class="primary">Marcar fin aquí</button>
    </div>
    <p class="timeval">Inicio: <strong id="startTxt">0:00.0</strong> · Fin: <strong id="endTxt">{{ duration_str }}</strong> · Recorte: <strong id="clipDur">—</strong></p>
  </section>

  <section class="block" aria-labelledby="fineh">
    <h2 id="fineh">3. Ajuste fino</h2>
    <div class="row" role="group" aria-label="Ajustar el inicio">
      <span class="lbl">Inicio</span>
      <button type="button" data-adj="start" data-d="-1" aria-label="Inicio: retroceder 1 segundo">−1 s</button>
      <button type="button" data-adj="start" data-d="-0.1" aria-label="Inicio: retroceder una décima">−0.1 s</button>
      <button type="button" data-adj="start" data-d="0.1" aria-label="Inicio: avanzar una décima">+0.1 s</button>
      <button type="button" data-adj="start" data-d="1" aria-label="Inicio: avanzar 1 segundo">+1 s</button>
    </div>
    <div class="row" role="group" aria-label="Ajustar el fin">
      <span class="lbl">Fin</span>
      <button type="button" data-adj="end" data-d="-1" aria-label="Fin: retroceder 1 segundo">−1 s</button>
      <button type="button" data-adj="end" data-d="-0.1" aria-label="Fin: retroceder una décima">−0.1 s</button>
      <button type="button" data-adj="end" data-d="0.1" aria-label="Fin: avanzar una décima">+0.1 s</button>
      <button type="button" data-adj="end" data-d="1" aria-label="Fin: avanzar 1 segundo">+1 s</button>
    </div>
  </section>

  <section class="block" aria-labelledby="checkh">
    <h2 id="checkh">4. Comprobar el recorte</h2>
    <div class="row">
      <button type="button" id="hearStart">Escuchar el inicio del corte</button>
      <button type="button" id="hearEnd">Escuchar el final del corte</button>
    </div>
    <div class="row">
      <button type="button" id="previewClip">Escuchar el recorte entero</button>
      <button type="button" id="loopClip">Escuchar en bucle</button>
      <button type="button" id="stopPlay">Parar</button>
    </div>
  </section>

  <section class="block" aria-labelledby="opth">
    <h2 id="opth">Opciones</h2>
    <div class="row"><label><input type="checkbox" id="precise" checked> Corte preciso (recomendado para tonos)</label></div>
    <div class="row"><label><input type="checkbox" id="fades" checked> Micro-fundidos de 5 ms (evita clics)</label></div>
    <details>
      <summary>Avanzado: escribir los tiempos a mano</summary>
      <div class="row">
        <label for="startManual">Inicio</label>
        <input id="startManual" type="text" inputmode="numeric" placeholder="m:ss.s">
        <label for="endManual">Fin</label>
        <input id="endManual" type="text" inputmode="numeric" placeholder="m:ss.s">
        <button type="button" id="applyManual">Aplicar</button>
      </div>
      <p class="hint">Formato: m:ss.s, mm:ss.sss o segundos (por ejemplo 83.5).</p>
    </details>
  </section>

  <section class="block" aria-labelledby="dlh">
    <h2 id="dlh">5. Descargar</h2>
    <div class="row">
      <button type="button" id="ringtonePreset" class="primary">Crear tono de llamada ({{ ringtone_seconds }} s)</button>
    </div>
    <p id="ringtoneState" class="hint" aria-live="polite"></p>
    <form id="trimForm" action="{{ trim_url }}" method="post">
      <input type="hidden" name="id" value="{{ sid }}">
      <input type="hidden" name="sig" value="{{ sig }}">
      <input type="hidden" id="start_h" name="start">
      <input type="hidden" id="end_h" name="end">
      <input type="hidden" id="ringtone_h" name="ringtone_mode" value="false">
      <input type="hidden" id="precise_h" name="precise" value="true">
      <input type="hidden" id="fades_h" name="fades" value="true">
      <div class="row"><button type="submit" class="primary">Descargar recorte</button></div>
    </form>
    <form action="{{ download_full_url }}" method="post">
      <input type="hidden" name="id" value="{{ sid }}">
      <input type="hidden" name="sig" value="{{ sig_full }}">
      <div class="row"><button type="submit">Descargar audio completo</button></div>
    </form>
  </section>

  <form action="{{ cancel_url }}" method="post" class="block">
    <input type="hidden" name="id" value="{{ sid }}">
    <input type="hidden" name="sig" value="{{ sig_cancel }}">
    <button type="submit">Descartar y empezar de nuevo</button>
  </form>
</main>

<script>
(function(){
  const DUR_INIT = {{ duration_sec }};
  const RING = {{ ringtone_seconds }};
  const player = document.getElementById('player');
  const live = document.getElementById('live');
  const alertR = document.getElementById('alert');
  const curPos = document.getElementById('curPos');
  const totalD = document.getElementById('totalD');
  const startTxt = document.getElementById('startTxt');
  const endTxt = document.getElementById('endTxt');
  const clipDur = document.getElementById('clipDur');
  const precise = document.getElementById('precise');
  const fades = document.getElementById('fades');
  const startH = document.getElementById('start_h');
  const endH = document.getElementById('end_h');
  const ringtoneH = document.getElementById('ringtone_h');
  const preciseH = document.getElementById('precise_h');
  const fadesH = document.getElementById('fades_h');
  const ringtoneState = document.getElementById('ringtoneState');
  const trimForm = document.getElementById('trimForm');

  let durationSec = (Number.isFinite(DUR_INIT) && DUR_INIT > 0) ? DUR_INIT : 0;
  let startSec = 0;
  let endSec = durationSec;
  let ringtone = false;
  let playMode = null; // {from, end, loop}

  function clamp(v,a,b){ return Math.max(a, Math.min(b, v)); }

  function fmt(t){
    t = Math.max(0, t);
    const m = Math.floor(t/60);
    const s = t - m*60;
    return m + ':' + s.toFixed(1).padStart(4,'0');
  }
  function spoken(t){
    let dt = Math.round(Math.max(0,t)*10);
    const m = Math.floor(dt/600); dt -= m*600;
    const s = Math.floor(dt/10); const tenths = dt%10;
    const parts = [];
    if (m>0) parts.push(m + (m===1?' minuto':' minutos'));
    if (s>0 || (m===0 && tenths===0)) parts.push(s + (s===1?' segundo':' segundos'));
    if (tenths>0) parts.push(tenths + (tenths===1?' décima':' décimas'));
    return parts.join(' ');
  }
  function say(msg){ live.textContent = ''; live.textContent = msg; }
  function alertSay(msg){ alertR.textContent = ''; alertR.textContent = msg; }

  function parseTime(str){
    if (!str) return NaN;
    const parts = String(str).trim().split(':');
    if (parts.length === 1) { const v = parseFloat(parts[0]); return isNaN(v)?NaN:v; }
    if (parts.length === 2) { const m=parseInt(parts[0],10), s=parseFloat(parts[1]); return (isNaN(m)||isNaN(s))?NaN:m*60+s; }
    if (parts.length === 3) { const h=parseInt(parts[0],10), m=parseInt(parts[1],10), s=parseFloat(parts[2]); return ([h,m,s].some(isNaN))?NaN:h*3600+m*60+s; }
    return NaN;
  }

  function syncHidden(){
    startH.value = startSec.toFixed(3);
    endH.value = endSec.toFixed(3);
    ringtoneH.value = ringtone ? 'true' : 'false';
    preciseH.value = precise.checked ? 'true' : 'false';
    fadesH.value = fades.checked ? 'true' : 'false';
  }
  function renderTimes(){
    startTxt.textContent = fmt(startSec);
    endTxt.textContent = fmt(endSec);
    clipDur.textContent = (endSec > startSec) ? fmt(endSec - startSec) : '—';
    syncHidden();
  }
  function updateRingtoneState(){
    ringtoneState.textContent = ringtone
      ? ('Modo tono activado: el fin se mantiene a ' + RING + ' segundos desde el inicio.')
      : '';
  }

  function setStart(sec, announce){
    startSec = clamp(sec, 0, durationSec);
    if (ringtone) endSec = Math.min(startSec + RING, durationSec);
    else if (endSec <= startSec) endSec = Math.min(startSec + 0.1, durationSec);
    renderTimes();
    if (announce) say('Inicio en ' + spoken(startSec) + '. Recorte de ' + spoken(Math.max(0,endSec-startSec)) + '.');
  }
  function setEnd(sec, announce){
    if (ringtone) { ringtone = false; updateRingtoneState(); }
    endSec = clamp(sec, 0, durationSec);
    if (endSec <= startSec) startSec = Math.max(endSec - 0.1, 0);
    renderTimes();
    if (announce) say('Fin en ' + spoken(endSec) + '. Recorte de ' + spoken(Math.max(0,endSec-startSec)) + '.');
  }

  function seekTo(t, announce){
    t = clamp(t, 0, durationSec || 0);
    try { player.currentTime = t; } catch(e){}
    curPos.textContent = fmt(t);
    if (announce) say('Posición ' + spoken(t) + '.');
  }

  // Reproducción de un segmento, robusta en iOS: play() en el gesto y seek después.
  function playSegment(from, to, loop, label){
    if (!(to > from)) { alertSay('Marca un inicio y un fin válidos.'); return; }
    playMode = { from: from, end: to, loop: loop };
    const doSeek = () => { try { player.currentTime = from; } catch(e){} };
    const p = player.play();
    if (p && p.then) p.then(doSeek).catch(doSeek); else doSeek();
    if (label) say(label);
  }
  function stopPlayback(announce){
    playMode = null;
    player.pause();
    if (announce) say('Reproducción detenida.');
  }

  // Mover el cursor del reproductor
  document.querySelectorAll('button[data-step]').forEach(btn => {
    btn.addEventListener('click', () => {
      const step = parseFloat(btn.getAttribute('data-step'));
      seekTo((player.currentTime || 0) + step, true);
    });
  });

  // Marcar
  document.getElementById('markStart').addEventListener('click', () => setStart(player.currentTime || 0, true));
  document.getElementById('markEnd').addEventListener('click', () => setEnd(player.currentTime || 0, true));

  // Ajuste fino de las marcas
  document.querySelectorAll('button[data-adj]').forEach(btn => {
    btn.addEventListener('click', () => {
      const d = parseFloat(btn.getAttribute('data-d'));
      if (btn.getAttribute('data-adj') === 'start') setStart(startSec + d, true);
      else setEnd(endSec + d, true);
    });
  });

  // Comprobar
  document.getElementById('hearStart').addEventListener('click', () => {
    // Primeros segundos del recorte: empieza justo en el inicio marcado.
    playSegment(startSec, Math.min(startSec + 2, endSec), false, 'Escuchando el inicio del corte.');
  });
  document.getElementById('hearEnd').addEventListener('click', () => {
    // Últimos segundos del recorte: termina justo en el fin marcado.
    playSegment(Math.max(endSec - 2, startSec), endSec, false, 'Escuchando el final del corte.');
  });
  document.getElementById('previewClip').addEventListener('click', () => {
    playSegment(startSec, endSec, false, 'Escuchando el recorte.');
  });
  document.getElementById('loopClip').addEventListener('click', () => {
    playSegment(startSec, endSec, true, 'Escuchando el recorte en bucle. Pulsa Parar para terminar.');
  });
  document.getElementById('stopPlay').addEventListener('click', () => stopPlayback(true));

  // Avanzado: tiempos a mano
  document.getElementById('applyManual').addEventListener('click', () => {
    const s = parseTime(document.getElementById('startManual').value);
    const e = parseTime(document.getElementById('endManual').value);
    if (isFinite(s)) setStart(s, false);
    if (isFinite(e)) setEnd(e, false);
    say('Tiempos aplicados. Inicio ' + spoken(startSec) + ', fin ' + spoken(endSec) + '.');
  });

  // Preset de tono
  document.getElementById('ringtonePreset').addEventListener('click', () => {
    ringtone = true;
    endSec = Math.min(startSec + RING, durationSec);
    updateRingtoneState();
    renderTimes();
    say('Modo tono de llamada activado. Fin fijado a ' + RING + ' segundos desde el inicio, en ' + spoken(endSec) + '. Ajusta el inicio y descarga.');
  });

  precise.addEventListener('change', syncHidden);
  fades.addEventListener('change', syncHidden);

  // Reproductor: tiempo actual + lógica de fin de segmento/bucle
  player.addEventListener('timeupdate', () => {
    curPos.textContent = fmt(player.currentTime || 0);
    if (playMode && player.currentTime >= playMode.end - 0.02) {
      if (playMode.loop) { try { player.currentTime = playMode.from; } catch(e){} }
      else { player.pause(); playMode = null; }
    }
  });
  // Si el usuario pausa a mano, salimos del modo segmento/bucle.
  player.addEventListener('pause', () => { playMode = null; });

  player.addEventListener('loadedmetadata', () => {
    const d = player.duration;
    if (Number.isFinite(d) && d > 0) {
      durationSec = d;
      totalD.textContent = fmt(d);
      if (!(endSec > 0) || endSec === DUR_INIT || endSec > d) endSec = d;
      renderTimes();
    }
  });

  trimForm.addEventListener('submit', (e) => {
    syncHidden();
    if (!(endSec > startSec)) {
      e.preventDefault();
      alertSay('El recorte no es válido: el fin debe ser mayor que el inicio.');
    }
  });

  renderTimes();
})();
</script>
</body>
</html>'''

# ---------- Sistema de progreso ----------
def update_progress(sid: str, progress: int, message: str, status: str = "processing"):
    """Actualiza el progreso de una sesión"""
    with progress_lock:
        if sid not in progress_store:
            progress_store[sid] = {}
        progress_store[sid].update({
            "progress": progress,
            "message": message,
            "status": status,
            "timestamp": time.time()
        })

def set_progress_error(sid: str, error: str):
    """Marca una sesión con error"""
    with progress_lock:
        if sid not in progress_store:
            progress_store[sid] = {}
        progress_store[sid].update({
            "status": "error",
            "error": error,
            "timestamp": time.time()
        })

def set_progress_complete(sid: str, message: str = "Completado"):
    """Marca una sesión como completada"""
    with progress_lock:
        if sid not in progress_store:
            progress_store[sid] = {}
        progress_store[sid].update({
            "progress": 100,
            "message": message,
            "status": "complete",
            "timestamp": time.time()
        })

def get_progress(sid: str):
    """Obtiene el progreso actual de una sesión"""
    with progress_lock:
        return progress_store.get(sid, {}).copy()

def cleanup_progress(sid: str):
    """Limpia el progreso de una sesión"""
    with progress_lock:
        progress_store.pop(sid, None)

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

    # Purga entradas de progreso huérfanas (cliente que nunca abrió el SSE)
    with progress_lock:
        stale = [s for s, d in progress_store.items()
                 if now - d.get("timestamp", now) > PROGRESS_TTL]
        for s in stale:
            progress_store.pop(s, None)

# ---------- validación y helpers ----------
YTLINK = re.compile(r'^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be)/', re.I)

# Runtimes JS que yt-dlp puede usar para resolver challenges (nsig + PO tokens).
# Se listan ambos: usa el que esté disponible (Deno en Railway, Node en local).
JS_RUNTIMES = {"deno": {}, "node": {}}

# Estrategias de extracción, en orden de preferencia.
# La 1ª deja que yt-dlp use sus clientes por defecto (web/tv) junto al solver JS
# para generar PO tokens: es lo que mejor evade el bloqueo por IP de datacenter.
# El resto son fallbacks con clientes que a veces funcionan sin PO token.
EXTRACTION_STRATEGIES = [
    {"name": "default", "clients": None},   # sin forzar player_client
    {"name": "android", "clients": ["android"]},
    {"name": "ios", "clients": ["ios"]},
    {"name": "tv", "clients": ["tv"]},
    {"name": "web_safari", "clients": ["web_safari"]},
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
        print(f"[ffmpeg] conversión a MP3 falló: {msg}", flush=True)
        abort(500, "No se pudo convertir el audio a MP3.")

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
        print(f"[ffmpeg] recorte falló: {msg}", flush=True)
        abort(500, "No se pudo recortar el audio.")

def _ytdlp_log(msg: str):
    """Log de diagnóstico (visible también en los logs de Railway)."""
    print(f"[yt-dlp] {msg}", flush=True)

def _build_opts(base: dict, clients):
    """Crea un dict de opciones con la estrategia de cliente indicada."""
    opts = dict(base)
    extractor_args = {"youtube": {}}
    if clients:
        extractor_args["youtube"]["player_client"] = clients
    opts["extractor_args"] = extractor_args
    return opts

def yt_extract_then_download(url: str, outtmpl: str, sid: str = None):
    """
    Descarga audio de YouTube usando yt-dlp.
    2026: usa el solver JS (Deno/Node) con clientes por defecto para generar
    PO tokens y evitar el bloqueo por IP; con fallback a clientes móviles.
    """
    base_common = {
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "concurrent_fragment_downloads": 1,
        "geo_bypass": True,
        "ffmpeg_location": FFMPEG_DIR,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_UPLOAD_SIZE,
        # Anti-bot improvements
        "extractor_retries": 3,
        "fragment_retries": 5,
        "skip_unavailable_fragments": True,
        "nocheckcertificate": True,
        # Runtime JS para resolver nsig + PO tokens (clave en datacenter)
        "js_runtimes": JS_RUNTIMES,
    }

    _ytdlp_log(f"version {yt_dlp.version.__version__}")

    # Usar cookies si están disponibles en variable de entorno (opcional, refuerzo)
    cookies_txt = os.environ.get("YOUTUBE_COOKIES")
    if cookies_txt:
        cookies_file = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
        with open(cookies_file, "w", encoding="utf-8") as f:
            f.write(cookies_txt)
        base_common["cookiefile"] = cookies_file
        _ytdlp_log("using YOUTUBE_COOKIES")

    if sid:
        update_progress(sid, 10, "Extrayendo información del vídeo...", "processing")

    info = None; chosen = None; last_err = None

    for strat in EXTRACTION_STRATEGIES:
        _ytdlp_log(f"trying strategy: {strat['name']}")
        opts_info = _build_opts(base_common, strat["clients"])
        try:
            with yt_dlp.YoutubeDL(opts_info) as ydl:
                info = ydl.extract_info(url, download=False)
            chosen = strat
            _ytdlp_log(f"success with strategy: {strat['name']}")
            break
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            _ytdlp_log(f"failed {strat['name']}: {str(e)[:120]}")

    if info is None:
        error_msg = str(last_err) if last_err else "No se pudo extraer información del vídeo"
        _ytdlp_log(f"all strategies failed. Last error: {error_msg[:200]}")
        raise last_err if last_err else RuntimeError(error_msg)

    if sid:
        update_progress(sid, 30, "Descargando audio...", "processing")

    duration = float(info.get("duration") or 0.0)
    opts_dl = _build_opts(base_common, chosen["clients"])
    opts_dl.update({
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
    })

    # Hook de progreso para yt-dlp
    def progress_hook(d):
        if sid and d['status'] == 'downloading':
            try:
                percent = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
                # Mapear 30-70% del progreso total
                progress = 30 + (percent * 0.4)
                update_progress(sid, int(progress), f"Descargando: {int(percent)}%", "processing")
            except Exception:
                pass
    
    opts_dl['progress_hooks'] = [progress_hook]
    
    with yt_dlp.YoutubeDL(opts_dl) as ydl:
        result = ydl.extract_info(url, download=True)
        media_path = ydl.prepare_filename(result)

    if sid:
        update_progress(sid, 70, "Audio descargado", "processing")

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

# ---------- Helper para respuestas HTML con UTF-8 ----------
def render_html(template_string, **context):
    """Renderiza HTML con charset UTF-8 correcto"""
    html = render_template_string(template_string, **context)
    response = app.make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

def render_editor(sid: str, meta: dict):
    """Renderiza el editor con todas las firmas/URLs que necesita la plantilla."""
    return render_html(
        EDITOR_HTML,
        title=meta["title"],
        duration_str=hhmmss_from_seconds(meta.get("duration") or 0.0),
        duration_sec=float(meta.get("duration") or 0.0),
        ringtone_seconds=int(RINGTONE_SECONDS),
        audio_url=url_for("audio_stream", sid=sid, sig=sign_token(sid, "audio")),
        sid=sid,
        sig=sign_token(sid, "trim"),
        sig_cancel=sign_token(sid, "cancel"),
        sig_full=sign_token(sid, "full"),
        trim_url=url_for("trim"),
        cancel_url=url_for("cancel"),
        download_full_url=url_for("download_full"),
        home_url=url_for("index"),
    )

# ---------- rutas ----------
@app.get("/")
def index():
    cleanup_expired()
    return render_html(HOME_HTML)

@app.get("/youtube")
def youtube_get():
    return render_html(YOUTUBE_HTML)

@app.get("/upload")
def upload_get():
    return render_html(UPLOAD_HTML)

@app.post("/prepare")
def prepare():
    cleanup_expired()
    url = (request.form.get("url") or "").strip()
    if not YTLINK.match(url):
        return {"error": "URL no válida. Debe ser de youtube.com o youtu.be"}, 400
    url = re.sub(r'(\?|&)si=[^&]+', '', url)

    sid = uuid.uuid4().hex
    
    # Iniciar procesamiento en background
    def process_video():
        sdir = os.path.join(TMP_BASE, sid)
        acquired = False
        try:
            os.makedirs(sdir, exist_ok=True)
            outtmpl = os.path.join(sdir, "%(title).200B.%(ext)s")

            update_progress(sid, 1, "En cola, esperando turno...", "processing")
            if not download_semaphore.acquire(timeout=120):
                set_progress_error(sid, "El servidor está ocupado. Inténtalo de nuevo en unos minutos.")
                shutil.rmtree(sdir, ignore_errors=True)
                return
            acquired = True

            update_progress(sid, 5, "Iniciando descarga...", "processing")

            info, media_path = yt_extract_then_download(url, outtmpl, sid)

            if not (media_path and os.path.exists(media_path)):
                set_progress_error(sid, "No se descargó el audio")
                shutil.rmtree(sdir, ignore_errors=True)
                return

            update_progress(sid, 75, "Convirtiendo a MP3...", "processing")

            src_mp3 = os.path.join(sdir, "source.mp3")
            ffmpeg_to_mp3(media_path, src_mp3)

            try:
                if os.path.exists(media_path): os.remove(media_path)
            except Exception:
                pass

            duration = float(info.get("duration") or 0.0)
            meta = {"title": info.get("title") or "audio", "duration": duration, "created": datetime.now(timezone.utc).isoformat()}
            with open(os.path.join(sdir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)

            set_progress_complete(sid, "Audio preparado correctamente")

        except Exception as e:
            print(f"[prepare] error procesando {sid}: {e}", flush=True)
            set_progress_error(sid, str(e)[:300])
            shutil.rmtree(sdir, ignore_errors=True)
        finally:
            if acquired:
                download_semaphore.release()

    # Iniciar thread
    thread = threading.Thread(target=process_video, daemon=True)
    thread.start()

    return {"session_id": sid, "sig": sign_token(sid, "progress")}, 200

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
        print(f"[upload] no se pudo guardar el archivo: {e}", flush=True)
        shutil.rmtree(sdir, ignore_errors=True)
        abort(500, "No se pudo guardar el archivo.")

    title = derive_title_from_filename(f.filename)

    src_mp3 = os.path.join(sdir, "source.mp3")
    try:
        ffmpeg_to_mp3(original_path, src_mp3)
        os.remove(original_path)
    except HTTPException:
        shutil.rmtree(sdir, ignore_errors=True); raise
    except Exception as e:
        print(f"[upload] fallo de ffmpeg: {e}", flush=True)
        shutil.rmtree(sdir, ignore_errors=True)
        abort(500, "No se pudo procesar el archivo.")

    duration = probe_duration_seconds(src_mp3)

    meta = {"title": title, "duration": float(duration or 0.0), "created": datetime.now(timezone.utc).isoformat()}
    with open(os.path.join(sdir, "meta.json"), "w", encoding="utf-8") as jf:
        json.dump(meta, jf, ensure_ascii=False)

    return render_editor(sid, meta)

@app.get("/progress/<sid>")
def progress_stream(sid):
    """Stream de progreso usando Server-Sent Events"""
    sig = request.args.get("sig", "")
    if not verify_token(sid, "progress", sig):
        abort(403, "Token inválido")

    def generate():
        last_status = None
        timeout = 300  # 5 minutos timeout
        start_time = time.time()
        
        while True:
            if time.time() - start_time > timeout:
                yield f"event: error_event\ndata: {json.dumps({'error': 'Timeout'})}\n\n"
                break
            
            progress_data = get_progress(sid)
            
            if not progress_data:
                time.sleep(0.5)
                continue
            
            status = progress_data.get("status", "processing")
            
            # Enviar actualización
            if status != last_status or progress_data.get("progress", 0) > 0:
                yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"
                last_status = status
            
            # Si completó, enviar evento final con URL del editor
            if status == "complete":
                sdir = sess_dir(sid)
                meta_path = os.path.join(sdir, "meta.json")
                if os.path.exists(meta_path):
                    editor_url = url_for("editor", sid=sid, sig=sign_token(sid, "editor"))
                    yield f"event: complete\ndata: {json.dumps({'editor_url': editor_url})}\n\n"
                cleanup_progress(sid)
                break
            
            # Si hubo error, enviar evento de error
            if status == "error":
                error_msg = progress_data.get("error", "Error desconocido")
                yield f"event: error_event\ndata: {json.dumps({'error': error_msg})}\n\n"
                cleanup_progress(sid)
                break
            
            time.sleep(0.5)
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.get("/editor/<sid>")
def editor(sid):
    """Muestra el editor de audio"""
    sig = request.args.get("sig", "")
    if not verify_token(sid, "editor", sig):
        abort(403, "Token inválido")
    
    sdir = sess_dir(sid)
    meta_path = os.path.join(sdir, "meta.json")
    src = os.path.join(sdir, "source.mp3")
    
    if not (os.path.isdir(sdir) and os.path.exists(src) and os.path.exists(meta_path)):
        abort(410, "Sesión no encontrada o expirada")
    
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    return render_editor(sid, meta)

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
        if duration: end = min(start + RINGTONE_SECONDS, duration)
        else: end = start + RINGTONE_SECONDS
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
    filename = f"{base}-tono.mp3" if ringtone_mode else f"{base}-clip.mp3"
    # La sesión NO se borra aquí: permite sacar varios recortes de una misma
    # descarga. Se limpia por TTL o con "Descartar y empezar de nuevo".
    resp = send_file(dst, as_attachment=True, download_name=filename)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp

@app.post("/download_full")
def download_full():
    """Descarga el audio completo tal cual (sin recortar ni recodificar)."""
    cleanup_expired()
    sid = (request.form.get("id") or "").strip()
    sig = (request.form.get("sig") or "").strip()
    if not verify_token(sid, "full", sig):
        abort(403, "Token inválido")

    sdir = sess_dir(sid)
    meta_path = os.path.join(sdir, "meta.json")
    src = os.path.join(sdir, "source.mp3")
    if not (os.path.isdir(sdir) and os.path.exists(src) and os.path.exists(meta_path)):
        shutil.rmtree(sdir, ignore_errors=True)
        abort(410, "Sesión no encontrada o expirada")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    base = safe_download_name(meta.get("title") or "audio")
    resp = send_file(src, as_attachment=True, download_name=f"{base}.mp3")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
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

    if not download_semaphore.acquire(timeout=120):
        abort(503, "El servidor está ocupado. Inténtalo de nuevo en unos minutos.")

    tmpdir = tempfile.mkdtemp(prefix="ytmp3_legacy_")
    outtmpl = os.path.join(tmpdir, "%(title).200B.%(ext)s")
    try:
        info, media_path = yt_extract_then_download(url, outtmpl)
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True); raise
    except Exception as e:
        print(f"[download] error yt-dlp: {e}", flush=True)
        shutil.rmtree(tmpdir, ignore_errors=True)
        abort(502, "No se pudo descargar el audio de YouTube.")
    finally:
        download_semaphore.release()

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

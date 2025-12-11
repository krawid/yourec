# YourRec - Editor de Audio de YouTube

Aplicación web Flask para descargar audio de YouTube y editarlo (recortar, crear tonos de llamada).

## Características

- ✅ Descarga audio de YouTube con yt-dlp
- ✅ Sube archivos de audio/vídeo locales
- ✅ Editor visual con reproductor HTML5
- ✅ Recorte preciso con FFmpeg
- ✅ Modo tono de llamada (30 segundos)
- ✅ Previsualización antes de descargar
- ✅ Micro-fundidos para evitar clicks
- ✅ Interfaz accesible (ARIA)

## Deployment en Railway

### 1. Variables de entorno requeridas

```bash
APP_SECRET=tu_secret_aleatorio_aqui_minimo_32_caracteres
```

Genera un secret seguro:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Configuración

Railway detecta automáticamente:
- Python (via `requirements.txt`)
- Gunicorn (via `Procfile`)
- FFmpeg (via buildpack)

### 3. Dominio custom

1. En Railway: Settings → Domains → Add Custom Domain
2. Añade: `audio.krawid.es` (o el que prefieras)
3. Railway te da un CNAME
4. En Cloudflare DNS añade:
   - Tipo: CNAME
   - Nombre: audio
   - Contenido: [el que te dio Railway]
   - Proxy: Activado

## Desarrollo local

```bash
# Instalar dependencias
pip install -r requirements.txt

# Configurar variable de entorno
export APP_SECRET="tu_secret_aqui"

# Ejecutar
python app.py
```

La app estará en `http://localhost:8080`

## Límites

- Tamaño máximo de archivo: 500 MB
- Timeout de descarga: 300 segundos
- Sesiones temporales: 30 minutos TTL
- Workers: 2 (configurable en Procfile)

## Tecnologías

- **Backend**: Flask + Gunicorn
- **Descarga**: yt-dlp (multi-client: android, mweb, web_music)
- **Procesamiento**: FFmpeg (via imageio-ffmpeg)
- **Frontend**: HTML5 + JavaScript vanilla
- **Seguridad**: HMAC-SHA256 tokens

## Estructura

```
yourec/
├── app.py              # Aplicación Flask principal
├── requirements.txt    # Dependencias Python
├── Procfile           # Comando de inicio para Railway
├── railway.toml       # Configuración Railway
├── runtime.txt        # Versión de Python
└── README.md          # Este archivo
```

## Licencia

Uso personal/educativo

# Cambios Realizados para Deployment en Railway

## ✅ PROBLEMAS CORREGIDOS

### 1. **Error crítico de JavaScript (línea 476)**
**Antes:**
```javascript
nextPlayIsPreview = True = true;
```
**Después:**
```javascript
nextPlayIsPreview = true;
```
**Impacto:** Causaba error en consola del navegador, rompía la previsualización.

---

### 2. **Seguridad: APP_SECRET mejorado**
**Antes:**
```python
SECRET = (os.environ.get("APP_SECRET") or secrets.token_hex(16)).encode()
```
Generaba secret aleatorio en cada reinicio → sesiones invalidadas.

**Después:**
```python
if not os.environ.get("APP_SECRET"):
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("APP_SECRET environment variable is required in production")
    print("⚠️  WARNING: Using random APP_SECRET (development only)")

SECRET = (os.environ.get("APP_SECRET") or secrets.token_hex(16)).encode()
```
**Impacto:** Fuerza configurar APP_SECRET en producción, evita pérdida de sesiones.

---

### 3. **Límite de tamaño de archivo**
**Añadido:**
```python
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE
```
**Impacto:** Previene saturación del servidor con archivos gigantes.

---

### 4. **Optimización de limpieza de sesiones**
**Antes:** Se ejecutaba en cada request (lento).

**Después:**
```python
_last_cleanup = 0
CLEANUP_INTERVAL = 300  # 5 min

def cleanup_expired():
    global _last_cleanup
    now = time.time()
    
    # Skip if cleaned up recently
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return
    
    _last_cleanup = now
    # ... resto del código
```
**Impacto:** Reduce carga del servidor, solo limpia cada 5 minutos.

---

### 5. **Timeout y límites en yt-dlp**
**Añadido:**
```python
"socket_timeout": 30,  # antes: 20
"retries": 3,          # antes: 2
"max_filesize": MAX_UPLOAD_SIZE,  # NUEVO
```
**Impacto:** Mejor manejo de errores, previene descargas infinitas.

---

## 📁 ARCHIVOS NUEVOS CREADOS

### 1. **railway.toml**
Configuración específica de Railway:
- Builder: nixpacks
- Start command: gunicorn con 2 workers
- Timeout: 300 segundos
- Healthcheck configurado

### 2. **Procfile**
Comando de inicio alternativo (Railway usa railway.toml primero):
```
web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 300
```

### 3. **.gitignore**
Evita subir archivos innecesarios:
- `__pycache__/`
- `.env`
- `*.pyc`
- Archivos temporales
- Configuración de IDEs

### 4. **runtime.txt**
Especifica versión de Python:
```
python-3.11
```

### 5. **README.md**
Documentación completa:
- Características
- Instrucciones de deployment
- Configuración de variables de entorno
- Desarrollo local

### 6. **.env.example**
Plantilla para variables de entorno:
```bash
APP_SECRET=tu_secret_aqui
```

### 7. **CAMBIOS_RAILWAY.md**
Este archivo (documentación de cambios).

---

## 📦 DEPENDENCIAS ACTUALIZADAS

**requirements.txt mejorado:**
```
Flask==3.0.3
gunicorn==22.0.0
yt-dlp>=2024.8.6          # Versión mínima especificada
imageio-ffmpeg>=0.5.1     # Versión mínima especificada
Werkzeug==3.0.3           # Añadido explícitamente
```

---

## 🚀 PRÓXIMOS PASOS PARA DEPLOYMENT

### 1. Generar APP_SECRET
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Subir a GitHub
```bash
git init
git add .
git commit -m "Initial commit - YourRec app"
git branch -M main
git remote add origin https://github.com/krawid/yourec.git
git push -u origin main
```

### 3. Crear proyecto en Railway
1. Ir a railway.app
2. New Project → Deploy from GitHub repo
3. Seleccionar el repo `yourec`
4. Railway detecta Python automáticamente

### 4. Configurar variables de entorno
En Railway → Variables:
```
APP_SECRET=el_secret_que_generaste
```

### 5. Configurar dominio custom
1. Railway → Settings → Domains → Add Custom Domain
2. Escribir: `audio.krawid.es`
3. Railway te da un CNAME (ej: `yourec-production-abc123.up.railway.app`)

### 6. Configurar DNS en Cloudflare
1. Ir a Cloudflare → DNS → Add record
2. Tipo: CNAME
3. Nombre: audio
4. Contenido: `yourec-production-abc123.up.railway.app` (el que te dio Railway)
5. Proxy: Activado (nube naranja)
6. TTL: Auto
7. Guardar

### 7. Esperar propagación (5-30 min)
Listo! Tu app estará en `https://audio.krawid.es`

---

## 🔍 VERIFICACIÓN POST-DEPLOYMENT

### Checklist:
- [ ] App responde en la URL de Railway
- [ ] Dominio custom funciona (`audio.krawid.es`)
- [ ] SSL/HTTPS activo (automático con Railway)
- [ ] Descarga de YouTube funciona
- [ ] Subida de archivos funciona
- [ ] Editor de audio funciona
- [ ] Previsualización funciona
- [ ] Descarga de recortes funciona

### Logs:
```bash
# Ver logs en Railway dashboard o CLI
railway logs
```

---

## 📊 RECURSOS ESTIMADOS

**Railway:**
- CPU: ~0.1-0.5 vCPU (depende del uso)
- RAM: ~512 MB - 1 GB
- Disco: Temporal (sesiones se borran cada 30 min)
- Coste estimado: €2-5/mes

**Límites configurados:**
- Max upload: 500 MB
- Timeout: 300 segundos
- Workers: 2
- Session TTL: 30 minutos

---

## 🛡️ SEGURIDAD

✅ Tokens HMAC-SHA256 para todas las operaciones
✅ APP_SECRET requerido en producción
✅ Validación de URLs de YouTube
✅ Sanitización de nombres de archivo
✅ Límite de tamaño de archivos
✅ Limpieza automática de sesiones
✅ No se almacenan datos permanentemente

---

## 🐛 DEBUGGING

Si algo falla:

1. **Revisar logs de Railway**
2. **Verificar APP_SECRET está configurado**
3. **Comprobar que FFmpeg está disponible** (Railway lo incluye automáticamente)
4. **Verificar DNS en Cloudflare** (puede tardar hasta 48h, normalmente 5-30 min)

---

**Fecha de cambios:** Diciembre 2024
**Versión:** 1.0 (Railway-ready)

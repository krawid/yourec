# 🚀 PASOS EXACTOS PARA DESPLEGAR EN RAILWAY

## PASO 1: Generar APP_SECRET

Ejecuta en tu terminal:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Guarda el resultado**, lo necesitarás en el paso 4.

Ejemplo de output:
```
a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2
```

---

## PASO 2: Subir a GitHub

### 2.1 Inicializar Git (si no lo has hecho)
```bash
cd Documents/yourec
git init
```

### 2.2 Añadir archivos
```bash
git add .
```

### 2.3 Hacer commit
```bash
git commit -m "Initial commit - YourRec audio editor ready for Railway"
```

### 2.4 Crear repositorio en GitHub
1. Ve a https://github.com/new
2. Nombre del repo: `yourec` (o el que prefieras)
3. Descripción: "Editor de audio de YouTube - Descarga y recorta audio"
4. Público o Privado (tu elección)
5. **NO** marques "Add README" ni ".gitignore" (ya los tienes)
6. Click en "Create repository"

### 2.5 Conectar y subir
GitHub te mostrará comandos, pero básicamente:
```bash
git branch -M main
git remote add origin https://github.com/krawid/yourec.git
git push -u origin main
```

**Nota:** Reemplaza `krawid` con tu usuario de GitHub si es diferente.

---

## PASO 3: Crear proyecto en Railway

### 3.1 Ir a Railway
1. Abre https://railway.app
2. Inicia sesión (con GitHub si es posible)

### 3.2 Crear nuevo proyecto
1. Click en "New Project"
2. Selecciona "Deploy from GitHub repo"
3. Si es la primera vez, autoriza Railway a acceder a GitHub
4. Busca y selecciona el repo `yourec`
5. Railway empezará a detectar y construir automáticamente

### 3.3 Esperar el build inicial
- Railway detectará Python automáticamente
- Instalará dependencias de `requirements.txt`
- Instalará FFmpeg automáticamente
- Esto tarda 2-5 minutos

---

## PASO 4: Configurar variables de entorno

### 4.1 Ir a Variables
1. En el dashboard de Railway, click en tu proyecto
2. Click en la pestaña "Variables"

### 4.2 Añadir APP_SECRET
1. Click en "New Variable"
2. Key: `APP_SECRET`
3. Value: (pega el secret que generaste en el PASO 1)
4. Click en "Add"

Railway reiniciará automáticamente la app con la nueva variable.

---

## PASO 5: Verificar que funciona

### 5.1 Obtener URL temporal de Railway
1. En el dashboard, verás una URL tipo:
   ```
   https://yourec-production-abc123.up.railway.app
   ```
2. Click en esa URL o cópiala

### 5.2 Probar la app
1. Abre la URL en tu navegador
2. Deberías ver la página de inicio con dos opciones:
   - "Usar enlace de YouTube"
   - "Subir archivo"
3. Prueba descargar un vídeo corto de YouTube
4. Prueba el editor de audio

Si todo funciona, ¡perfecto! Continúa al PASO 6.

---

## PASO 6: Configurar dominio custom

### 6.1 En Railway
1. Ve a Settings → Domains
2. Click en "Add Custom Domain"
3. Escribe: `audio.krawid.es`
4. Click en "Add Domain"

### 6.2 Railway te dará un CNAME
Railway te mostrará algo como:
```
CNAME: yourec-production-abc123.up.railway.app
```

**Copia ese valor**, lo necesitas para el siguiente paso.

---

## PASO 7: Configurar DNS en Cloudflare

### 7.1 Ir a Cloudflare DNS
1. Abre https://dash.cloudflare.com
2. Selecciona tu dominio: `krawid.es`
3. Ve a DNS → Records

### 7.2 Añadir registro CNAME
1. Click en "Add record"
2. Rellena:
   - **Type:** CNAME
   - **Name:** audio
   - **Target:** (pega el CNAME que te dio Railway)
   - **Proxy status:** Proxied (nube naranja) ✅
   - **TTL:** Auto
3. Click en "Save"

---

## PASO 8: Esperar propagación DNS

### 8.1 Tiempo de espera
- Normalmente: 5-30 minutos
- Máximo: 48 horas (raro)

### 8.2 Verificar propagación
Puedes verificar con:
```bash
nslookup audio.krawid.es
```

O en línea: https://dnschecker.org/#CNAME/audio.krawid.es

---

## PASO 9: ¡Listo! 🎉

Tu app debería estar funcionando en:
```
https://audio.krawid.es
```

### Verificación final:
- [ ] La URL carga correctamente
- [ ] HTTPS funciona (candado verde)
- [ ] Puedes descargar audio de YouTube
- [ ] Puedes subir archivos
- [ ] El editor funciona
- [ ] La previsualización funciona
- [ ] Puedes descargar recortes

---

## 🐛 TROUBLESHOOTING

### Problema: "APP_SECRET environment variable is required"
**Solución:** Configura APP_SECRET en Railway → Variables (PASO 4)

### Problema: "502 Bad Gateway"
**Solución:** 
1. Revisa logs en Railway: Click en "View Logs"
2. Verifica que el build terminó correctamente
3. Espera 1-2 minutos, Railway puede estar reiniciando

### Problema: "Domain not found" o "DNS_PROBE_FINISHED_NXDOMAIN"
**Solución:** 
1. Verifica que añadiste el CNAME en Cloudflare correctamente
2. Espera más tiempo (propagación DNS puede tardar)
3. Verifica con: https://dnschecker.org

### Problema: Descarga de YouTube falla
**Solución:**
1. Verifica que la URL es válida
2. Algunos vídeos pueden estar bloqueados por región
3. Revisa logs en Railway para ver el error específico

### Problema: "File too large"
**Solución:** El límite es 500 MB. Usa vídeos más cortos o archivos más pequeños.

---

## 📊 MONITOREO

### Ver logs en tiempo real:
1. Railway dashboard → Tu proyecto
2. Click en "View Logs"
3. Verás todos los requests y errores

### Métricas:
1. Railway dashboard → Tu proyecto
2. Click en "Metrics"
3. Verás CPU, RAM, Network usage

---

## 💰 COSTES

Railway cobra por uso:
- **Plan gratuito:** $5 de crédito/mes
- **Después:** ~€0.01-0.02 por hora de uso

**Estimación:**
- Uso bajo: €0-2/mes (dentro del plan gratuito)
- Uso medio: €2-5/mes
- Uso alto: €5-10/mes

---

## 🔄 ACTUALIZACIONES FUTURAS

Para actualizar el código:

```bash
# 1. Hacer cambios en el código
# 2. Commit
git add .
git commit -m "Descripción de los cambios"

# 3. Push
git push

# Railway detectará el push y desplegará automáticamente
```

---

## 📞 AYUDA

Si tienes problemas:
1. Revisa los logs en Railway
2. Verifica que todos los pasos se completaron
3. Consulta la documentación de Railway: https://docs.railway.app

---

**¡Buena suerte con el deployment!** 🚀

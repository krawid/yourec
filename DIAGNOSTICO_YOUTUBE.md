# Diagnóstico: Descarga de YouTube con PO Token Provider

## Estado Actual

### ✅ Dependencias Instaladas
- Python: 3.14.4
- Node.js: v24.15.0 (>=20 ✓)
- yt-dlp: 2026.03.17 ✓
- yt-dlp-ejs: 0.8.0 ✓
- bgutil-ytdlp-pot-provider: 1.3.1 ✓

### ⚠️ Problema Identificado

El plugin `bgutil-ytdlp-pot-provider` se carga correctamente, pero tiene 3 providers:

1. **bgutil:script-node** (unavailable)
   - Busca: `C:\Users\krawi\bgutil-ytdlp-pot-provider\server\build\generate_once.js`
   - Estado: Archivo no existe

2. **bgutil:script-deno** (unavailable)
   - Busca: `C:\Users\krawi\bgutil-ytdlp-pot-provider\server\src\generate_once.ts`
   - Estado: Archivo no existe (y Deno no está instalado)

3. **bgutil:http** (available pero sin servidor)
   - Intenta conectar a: `http://127.0.0.1:4416`
   - Estado: Servidor no está corriendo
   - Error: `TransportError - server is not reachable`

### 🔍 Resultado

Sin PO Token disponible, YouTube bloquea los formatos:
```
WARNING: mweb client https formats require a GVS PO Token which was not provided.
They will be skipped as they may yield HTTP Error 403.
```

## Soluciones Posibles

### Opción 1: Provider HTTP (Recomendado para producción)
**Ventajas:**
- Mejor rendimiento con múltiples requests
- Un solo servidor para toda la app
- Ideal para Railway

**Desventajas:**
- Requiere proceso adicional corriendo
- Más complejo de configurar

**Pasos:**
1. Clonar repositorio del servidor: https://github.com/coletdjnz/bgutil-ytdlp-pot-provider
2. Instalar dependencias Node.js
3. Iniciar servidor HTTP en puerto 4416
4. Configurar yt-dlp para usar el servidor

### Opción 2: Provider Script Node (Más simple para desarrollo)
**Ventajas:**
- No requiere servidor separado
- Genera tokens on-demand
- Más simple para app pequeña

**Desventajas:**
- Overhead de iniciar Node.js en cada request
- Más lento que HTTP server

**Pasos:**
1. Clonar repositorio del servidor
2. Compilar scripts TypeScript a JavaScript
3. Configurar ruta en extractor_args

### Opción 3: Cambiar estrategia de cliente

Según la documentación actual de yt-dlp, algunos clientes NO requieren PO Token:
- `android` (versiones antiguas)
- `ios` (algunas versiones)

**Probar primero con cliente `android` sin PO Token antes de implementar provider.**

## Recomendación Inmediata

**✅ SOLUCIÓN ENCONTRADA: Cliente `android` funciona sin PO Token**

Prueba realizada con éxito:
- Cliente: `android`
- URL de prueba: https://www.youtube.com/watch?v=jNQXAC9IVRw
- Resultado: ✅ Descarga exitosa (614 KB)
- PO Token requerido: NO
- Tiempo: < 1 segundo

**Configuración funcional:**
```python
"extractor_args": {
    "youtube": {
        "player_client": ["android"],
        # NO usar skip: ["hls", "dash"]
    }
}
```

**Cambios necesarios en app.py:**
1. Quitar `skip: ["hls", "dash"]` de todas las configuraciones
2. Cambiar orden de clientes: probar `android` primero
3. Añadir logging útil para diagnóstico
4. Actualizar User-Agent para cliente android

## Próximos Pasos

1. ✅ Actualizar `requirements.txt` (HECHO)
2. ✅ Instalar dependencias (HECHO)
3. ✅ Diagnosticar problema (HECHO)
4. ✅ Probar cliente `android` sin PO Token (FUNCIONA!)
5. ⏳ Actualizar `app.py` con configuración funcional
6. ⏳ Probar en local con app completa
7. ⏳ Preparar para Railway

## Notas Técnicas

- El provider `bgutil-ytdlp-pot-provider` es un plugin que se registra automáticamente
- No es un módulo Python importable directamente
- Se activa automáticamente cuando yt-dlp detecta que YouTube requiere PO Token
- La configuración se hace vía `extractor_args` en yt-dlp options

## Referencias

- PO Token Guide: https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
- Provider Repository: https://github.com/coletdjnz/bgutil-ytdlp-pot-provider
- yt-dlp Issues: https://github.com/yt-dlp/yt-dlp/issues

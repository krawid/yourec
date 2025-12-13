# Configurar cookies de YouTube para evitar bloqueos

YouTube puede bloquear las descargas automáticas detectándolas como bots. Para evitarlo, puedes configurar cookies de autenticación.

## Opción 1: Usar extensión del navegador (Recomendado)

1. Instala una extensión para exportar cookies:
   - Chrome/Edge: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - Firefox: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

2. Ve a YouTube.com y asegúrate de estar logueado

3. Haz clic en la extensión y exporta las cookies de youtube.com

4. Copia todo el contenido del archivo cookies.txt

5. En Railway:
   - Ve a tu proyecto > Variables
   - Crea una nueva variable: `YOUTUBE_COOKIES`
   - Pega todo el contenido del archivo cookies.txt como valor
   - Guarda y redeploy

## Opción 2: Sin cookies (limitado)

Si no quieres usar cookies, la aplicación intentará descargar sin autenticación, pero YouTube puede bloquear algunas descargas.

## Verificar que funciona

Después de configurar las cookies:
1. Redeploy la aplicación en Railway
2. Prueba descargar un video
3. Si funciona, las cookies están configuradas correctamente

## Notas

- Las cookies expiran después de un tiempo (generalmente semanas o meses)
- Si empiezas a ver errores de nuevo, exporta cookies frescas
- Las cookies son específicas de tu cuenta de YouTube

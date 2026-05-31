#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para verificar descarga de YouTube con PO Token Provider
NO usa cookies de cuenta, debe funcionar sin autenticación
"""

import sys
import os
import tempfile
import yt_dlp

# URL de prueba (vídeo corto y público)
TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo" - primer vídeo de YouTube

def test_youtube_download():
    """Prueba descarga de YouTube con configuración actualizada"""
    
    print("=" * 70)
    print("TEST: Descarga de YouTube con PO Token Provider")
    print("=" * 70)
    
    # Verificar versión de yt-dlp
    print(f"\n✓ yt-dlp version: {yt_dlp.version.__version__}")
    
    # Configuración de prueba
    tmpdir = tempfile.mkdtemp(prefix="yt_test_")
    print(f"✓ Directorio temporal: {tmpdir}")
    
    ydl_opts = {
        "verbose": True,
        "quiet": False,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmpdir, "%(title).100B.%(ext)s"),
        "socket_timeout": 30,
        "retries": 3,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],  # Cliente android - no requiere PO Token
                # NO usar skip: ["hls", "dash"] para permitir más formatos
            }
        },
    }
    
    print("\n" + "=" * 70)
    print("FASE 1: Extracción de información (sin descarga)")
    print("=" * 70)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"\n→ Extrayendo info de: {TEST_URL}\n")
            info = ydl.extract_info(TEST_URL, download=False)
            
            print("\n" + "=" * 70)
            print("✅ EXTRACCIÓN EXITOSA")
            print("=" * 70)
            print(f"Título: {info.get('title', 'N/A')}")
            print(f"Duración: {info.get('duration', 0)} segundos")
            print(f"Uploader: {info.get('uploader', 'N/A')}")
            
            # Verificar formatos disponibles
            formats = info.get('formats', [])
            audio_formats = [f for f in formats if f.get('acodec') != 'none']
            print(f"\nFormatos de audio disponibles: {len(audio_formats)}")
            
            if audio_formats:
                print("\nPrimeros 3 formatos de audio:")
                for fmt in audio_formats[:3]:
                    print(f"  - {fmt.get('format_id')}: {fmt.get('ext')} "
                          f"({fmt.get('acodec')}, {fmt.get('abr', 'N/A')} kbps)")
            
    except yt_dlp.utils.DownloadError as e:
        print("\n" + "=" * 70)
        print("❌ ERROR EN EXTRACCIÓN")
        print("=" * 70)
        print(f"Error: {e}")
        print("\nPosibles causas:")
        print("- El plugin PO Token Provider no se cargó correctamente")
        print("- YouTube bloqueó la solicitud")
        print("- Problema de red")
        return 1
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        return 1
    
    print("\n" + "=" * 70)
    print("FASE 2: Descarga real de audio")
    print("=" * 70)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"\n→ Descargando audio de: {TEST_URL}\n")
            result = ydl.extract_info(TEST_URL, download=True)
            media_path = ydl.prepare_filename(result)
            
            if os.path.exists(media_path) and os.path.getsize(media_path) > 0:
                size_mb = os.path.getsize(media_path) / (1024 * 1024)
                print("\n" + "=" * 70)
                print("✅ DESCARGA EXITOSA")
                print("=" * 70)
                print(f"Archivo: {media_path}")
                print(f"Tamaño: {size_mb:.2f} MB")
                
                # Limpiar
                try:
                    os.remove(media_path)
                    os.rmdir(tmpdir)
                    print("\n✓ Archivos temporales eliminados")
                except:
                    pass
                
                return 0
            else:
                print("\n❌ El archivo descargado está vacío o no existe")
                return 1
                
    except yt_dlp.utils.DownloadError as e:
        print("\n" + "=" * 70)
        print("❌ ERROR EN DESCARGA")
        print("=" * 70)
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        return 1

def test_pot_provider_detection():
    """Verifica si el PO Token Provider está disponible"""
    print("\n" + "=" * 70)
    print("VERIFICACIÓN: PO Token Provider")
    print("=" * 70)
    
    # bgutil-ytdlp-pot-provider es un plugin que se registra automáticamente
    # No es un módulo importable, así que verificamos si está instalado vía pip
    import subprocess
    try:
        result = subprocess.run(
            ["pip", "show", "bgutil-ytdlp-pot-provider"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"✅ bgutil-ytdlp-pot-provider instalado")
            # Extraer versión si está disponible
            for line in result.stdout.split('\n'):
                if line.startswith('Version:'):
                    print(f"   {line}")
        else:
            print("❌ bgutil-ytdlp-pot-provider NO está instalado")
            print("   Instalar con: pip install bgutil-ytdlp-pot-provider")
            return False
    except Exception as e:
        print(f"⚠️  No se pudo verificar bgutil-ytdlp-pot-provider: {e}")
    
    try:
        # Verificar yt-dlp-ejs
        import yt_dlp_ejs
        print(f"✅ yt-dlp-ejs instalado")
        print(f"   Versión: {yt_dlp_ejs.__version__ if hasattr(yt_dlp_ejs, '__version__') else 'N/A'}")
    except ImportError:
        print("❌ yt-dlp-ejs NO está instalado")
        print("   Instalar con: pip install yt-dlp-ejs")
        return False
    
    print("\n✓ El PO Token Provider debería cargarse automáticamente con yt-dlp")
    print("  Verifica en el output verbose si aparece '[youtube] [pot] PO Token Providers'")
    
    return True

if __name__ == '__main__':
    print("\n🔍 PRUEBA DE DESCARGA DE YOUTUBE CON PO TOKEN PROVIDER\n")
    
    # Verificar que los providers están instalados
    if not test_pot_provider_detection():
        print("\n⚠️  Instala las dependencias faltantes y vuelve a ejecutar")
        sys.exit(1)
    
    # Ejecutar prueba de descarga
    result = test_youtube_download()
    
    if result == 0:
        print("\n" + "=" * 70)
        print("🎉 TODAS LAS PRUEBAS PASARON")
        print("=" * 70)
        print("\nLa configuración de YouTube está funcionando correctamente.")
        print("Puedes proceder a actualizar app.py con esta configuración.")
    else:
        print("\n" + "=" * 70)
        print("❌ PRUEBAS FALLARON")
        print("=" * 70)
        print("\nRevisa los errores arriba para diagnosticar el problema.")
    
    sys.exit(result)

#!/usr/bin/env python3
"""
Script de verificación pre-deployment para Railway
Ejecuta: python check_ready.py
"""

import os
import sys

def check_file_exists(filepath, required=True):
    """Verifica que un archivo existe"""
    exists = os.path.exists(filepath)
    status = "✅" if exists else ("❌" if required else "⚠️")
    req_text = "(requerido)" if required else "(opcional)"
    print(f"{status} {filepath} {req_text}")
    return exists if required else True

def check_env_var(var_name, required=True):
    """Verifica que una variable de entorno está configurada"""
    exists = os.environ.get(var_name) is not None
    status = "✅" if exists else ("❌" if required else "⚠️")
    req_text = "(requerido)" if required else "(opcional)"
    print(f"{status} Variable {var_name} {req_text}")
    return exists if required else True

def main():
    print("🔍 Verificando configuración para Railway...\n")
    
    all_ok = True
    
    # Archivos requeridos
    print("📁 Archivos requeridos:")
    all_ok &= check_file_exists("app.py", required=True)
    all_ok &= check_file_exists("requirements.txt", required=True)
    all_ok &= check_file_exists("Procfile", required=True)
    all_ok &= check_file_exists("railway.toml", required=True)
    all_ok &= check_file_exists("runtime.txt", required=True)
    all_ok &= check_file_exists(".gitignore", required=True)
    
    print("\n📄 Archivos opcionales:")
    check_file_exists("README.md", required=False)
    check_file_exists(".env.example", required=False)
    check_file_exists("CAMBIOS_RAILWAY.md", required=False)
    
    # Variables de entorno
    print("\n🔐 Variables de entorno:")
    env_ok = check_env_var("APP_SECRET", required=False)
    if not env_ok:
        print("   ⚠️  Recuerda configurar APP_SECRET en Railway antes de desplegar")
    
    # Verificar contenido de archivos críticos
    print("\n📝 Verificando contenido de archivos...")
    
    try:
        with open("requirements.txt", "r") as f:
            content = f.read()
            has_flask = "Flask" in content
            has_gunicorn = "gunicorn" in content
            has_ytdlp = "yt-dlp" in content
            has_ffmpeg = "imageio-ffmpeg" in content
            
            print(f"{'✅' if has_flask else '❌'} Flask en requirements.txt")
            print(f"{'✅' if has_gunicorn else '❌'} gunicorn en requirements.txt")
            print(f"{'✅' if has_ytdlp else '❌'} yt-dlp en requirements.txt")
            print(f"{'✅' if has_ffmpeg else '❌'} imageio-ffmpeg en requirements.txt")
            
            all_ok &= has_flask and has_gunicorn and has_ytdlp and has_ffmpeg
    except Exception as e:
        print(f"❌ Error leyendo requirements.txt: {e}")
        all_ok = False
    
    # Verificar sintaxis de Python
    print("\n🐍 Verificando sintaxis de Python...")
    try:
        import py_compile
        py_compile.compile("app.py", doraise=True)
        print("✅ app.py tiene sintaxis válida")
    except py_compile.PyCompileError as e:
        print(f"❌ Error de sintaxis en app.py: {e}")
        all_ok = False
    
    # Resumen final
    print("\n" + "="*50)
    if all_ok:
        print("✅ TODO LISTO PARA DEPLOYMENT EN RAILWAY")
        print("\nPróximos pasos:")
        print("1. Genera APP_SECRET: python -c \"import secrets; print(secrets.token_hex(32))\"")
        print("2. Sube a GitHub: git init && git add . && git commit -m 'Initial commit'")
        print("3. Crea proyecto en Railway desde GitHub")
        print("4. Configura APP_SECRET en Railway → Variables")
        print("5. Añade dominio custom: audio.krawid.es")
        print("6. Configura CNAME en Cloudflare DNS")
        return 0
    else:
        print("❌ HAY PROBLEMAS QUE RESOLVER ANTES DE DESPLEGAR")
        print("\nRevisa los errores marcados con ❌ arriba")
        return 1

if __name__ == "__main__":
    sys.exit(main())

#!/bin/bash

# =============================================================================
# Scripts de Build pour FitUploader - Cross-Platform
# =============================================================================

echo "🚀 FitUploader Build Scripts"
echo "============================="

# Fonction pour détecter l'OS
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        echo "windows"
    else
        echo "linux"
    fi
}

# Configuration
APP_NAME="FitUploader"
SCRIPT_NAME="fituploader.py"
VERSION="1.0.0"
OS_TYPE=$(detect_os)

echo "📋 Configuration détectée:"
echo "   - OS: $OS_TYPE"
echo "   - App: $APP_NAME"
echo "   - Script: $SCRIPT_NAME"
echo ""

# =============================================================================
# BUILD POUR macOS
# =============================================================================
build_macos() {
    echo "🍎 Build pour macOS"
    echo "==================="
    
    # Vérifier la présence de l'icône
    if [ ! -f "FitUploader.icns" ]; then
        echo "❌ Erreur: FitUploader.icns introuvable"
        echo "💡 Conseil: Convertissez votre PNG en ICNS avec:"
        echo "   sips -s format icns FitUploader.png --out FitUploader.icns"
        exit 1
    fi
    
    echo "📦 Création de l'exécutable macOS..."
    
    pyinstaller \
        --onefile \
        --windowed \
        --name="$APP_NAME" \
        --icon="FitUploader.icns" \
        --add-data="FitUploader.icns:." \
        --hidden-import="garth" \
        --hidden-import="fit_tool" \
        --hidden-import="tkinter" \
        --hidden-import="threading" \
        --hidden-import="queue" \
        --hidden-import="pathlib" \
        --hidden-import="json" \
        --hidden-import="hashlib" \
        --hidden-import="logging.handlers" \
        --exclude-module="PIL" \
        --exclude-module="matplotlib" \
        --exclude-module="numpy" \
        --exclude-module="pandas" \
        --clean \
        --noconfirm \
        "$SCRIPT_NAME"
    
    # Créer un bundle d'application macOS (optionnel)
    echo "📱 Création du bundle .app..."
    
    pyinstaller \
        --onedir \
        --windowed \
        --name="$APP_NAME" \
        --icon="FitUploader.icns" \
        --add-data="FitUploader.icns:." \
        --hidden-import="garth" \
        --hidden-import="fit_tool" \
        --clean \
        --noconfirm \
        "$SCRIPT_NAME"
    
    echo "✅ Build macOS terminé!"
    echo "📁 Fichiers générés:"
    echo "   - dist/$APP_NAME (exécutable unique)"
    echo "   - dist/$APP_NAME.app (bundle d'application)"
}

# =============================================================================
# BUILD POUR WINDOWS
# =============================================================================
build_windows() {
    echo "🪟 Build pour Windows"
    echo "===================="
    
    # Vérifier la présence de l'icône
    if [ ! -f "FitUploader.ico" ]; then
        echo "❌ Erreur: FitUploader.ico introuvable"
        echo "💡 Conseil: Convertissez votre PNG en ICO avec un outil en ligne"
        echo "   ou utilisez ImageMagick: convert FitUploader.png FitUploader.ico"
        exit 1
    fi
    
    echo "📦 Création de l'exécutable Windows..."
    
    pyinstaller \
        --onefile \
        --windowed \
        --name="$APP_NAME" \
        --icon="FitUploader.ico" \
        --add-data="FitUploader.ico;." \
        --hidden-import="garth" \
        --hidden-import="fit_tool" \
        --hidden-import="tkinter" \
        --hidden-import="threading" \
        --hidden-import="queue" \
        --hidden-import="pathlib" \
        --hidden-import="json" \
        --hidden-import="hashlib" \
        --hidden-import="logging.handlers" \
        --exclude-module="PIL" \
        --exclude-module="matplotlib" \
        --exclude-module="numpy" \
        --exclude-module="pandas" \
        --clean \
        --noconfirm \
        "$SCRIPT_NAME"
    
    echo "✅ Build Windows terminé!"
    echo "📁 Fichier généré: dist/$APP_NAME.exe"
}

# =============================================================================
# BUILD AVANCÉ AVEC SPEC FILE
# =============================================================================
create_spec_file() {
    echo "⚙️ Création du fichier .spec personnalisé..."
    
    cat > "${APP_NAME}.spec" << EOF
# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path

# Configuration
APP_NAME = '$APP_NAME'
SCRIPT_PATH = '$SCRIPT_NAME'
VERSION = '$VERSION'

# Détection de l'OS
is_macos = sys.platform == 'darwin'
is_windows = sys.platform == 'win32'

# Icône selon l'OS
if is_macos:
    icon_file = 'FitUploader.icns'
elif is_windows:
    icon_file = 'FitUploader.ico'
else:
    icon_file = 'FitUploader.png'

# Données à inclure
datas = []
if os.path.exists(icon_file):
    if is_windows:
        datas.append((icon_file, '.'))
    else:
        datas.append((icon_file, '.'))

# Modules cachés essentiels
hiddenimports = [
    'garth',
    'fit_tool',
    'tkinter',
    'tkinter.ttk',
    'threading',
    'queue',
    'pathlib',
    'json',
    'hashlib',
    'logging',
    'logging.handlers',
    'subprocess',
    'datetime',
    'enum',
    'dataclasses',
    'functools',
    'weakref',
    'os',
    'sys',
    'time',
    'concurrent.futures'
]

# Modules à exclure pour réduire la taille
excludes = [
    'PIL',
    'matplotlib',
    'numpy',
    'pandas',
    'scipy',
    'PyQt5',
    'PyQt6',
    'PySide2',
    'PySide6'
]

a = Analysis(
    [SCRIPT_PATH],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# Configuration de l'exécutable
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if os.path.exists(icon_file) else None,
)

# Bundle pour macOS
if is_macos:
    app = BUNDLE(
        exe,
        name=f'{APP_NAME}.app',
        icon=icon_file,
        bundle_identifier=f'com.fituploader.{APP_NAME.lower()}',
        version=VERSION,
        info_plist={
            'CFBundleDisplayName': APP_NAME,
            'CFBundleVersion': VERSION,
            'CFBundleShortVersionString': VERSION,
            'NSHighResolutionCapable': 'True',
            'LSMinimumSystemVersion': '10.14.0',
        }
    )
EOF

    echo "✅ Fichier ${APP_NAME}.spec créé"
}

# =============================================================================
# OPTIMISATIONS ET VÉRIFICATIONS
# =============================================================================
verify_build() {
    echo "🔍 Vérification du build..."
    
    if [ "$OS_TYPE" = "macos" ]; then
        if [ -f "dist/$APP_NAME" ]; then
            size=$(du -h "dist/$APP_NAME" | cut -f1)
            echo "✅ Exécutable créé: $size"
            
            # Test rapide
            echo "🧪 Test de l'exécutable..."
            ./dist/$APP_NAME --version 2>/dev/null && echo "✅ Test réussi" || echo "⚠️ Test échoué (normal si --version n'est pas implémenté)"
        fi
        
        if [ -d "dist/$APP_NAME.app" ]; then
            size=$(du -hs "dist/$APP_NAME.app" | cut -f1)
            echo "✅ Bundle .app créé: $size"
        fi
    elif [ "$OS_TYPE" = "windows" ]; then
        if [ -f "dist/$APP_NAME.exe" ]; then
            size=$(du -h "dist/$APP_NAME.exe" | cut -f1)
            echo "✅ Exécutable Windows créé: $size"
        fi
    fi
}

optimize_build() {
    echo "⚡ Optimisations du build..."
    
    # UPX compression (si disponible)
    if command -v upx &> /dev/null; then
        echo "📦 Compression UPX disponible"
        if [ -f "dist/$APP_NAME" ]; then
            upx --best "dist/$APP_NAME" 2>/dev/null && echo "✅ Exécutable compressé"
        fi
        if [ -f "dist/$APP_NAME.exe" ]; then
            upx --best "dist/$APP_NAME.exe" 2>/dev/null && echo "✅ Exécutable Windows compressé"
        fi
    else
        echo "💡 Conseil: Installez UPX pour compresser l'exécutable"
        echo "   macOS: brew install upx"
        echo "   Windows: choco install upx"
    fi
}

cleanup_build() {
    echo "🧹 Nettoyage des fichiers temporaires..."
    
    # Supprimer les dossiers temporaires
    rm -rf build/
    rm -rf __pycache__/
    
    # Garder seulement le dossier dist avec les exécutables
    echo "✅ Nettoyage terminé"
    echo "📁 Fichiers conservés dans le dossier 'dist/'"
}

# =============================================================================
# MENU PRINCIPAL
# =============================================================================
main_menu() {
    echo "Choisissez une option:"
    echo "1) Build pour l'OS actuel ($OS_TYPE)"
    echo "2) Build avec fichier .spec personnalisé"
    echo "3) Build optimisé (avec compression)"
    echo "4) Nettoyer les builds précédents"
    echo "5) Créer tous les formats"
    echo "6) Quitter"
    echo ""
    read -p "Votre choix [1-6]: " choice
    
    case $choice in
        1)
            if [ "$OS_TYPE" = "macos" ]; then
                build_macos
            elif [ "$OS_TYPE" = "windows" ]; then
                build_windows
            else
                echo "❌ OS non supporté pour ce script"
            fi
            verify_build
            ;;
        2)
            create_spec_file
            echo "📦 Build avec fichier .spec..."
            pyinstaller --clean --noconfirm "${APP_NAME}.spec"
            verify_build
            ;;
        3)
            main_menu # Relancer pour choisir le build
            optimize_build
            ;;
        4)
            cleanup_build
            ;;
        5)
            if [ "$OS_TYPE" = "macos" ]; then
                build_macos
            elif [ "$OS_TYPE" = "windows" ]; then
                build_windows
            fi
            verify_build
            optimize_build
            ;;
        6)
            echo "👋 Au revoir!"
            exit 0
            ;;
        *)
            echo "❌ Choix invalide"
            main_menu
            ;;
    esac
}

# =============================================================================
# VÉRIFICATIONS PRÉALABLES
# =============================================================================
check_requirements() {
    echo "🔍 Vérification des prérequis..."
    
    # Vérifier Python
    if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
        echo "❌ Python non trouvé"
        exit 1
    fi
    
    # Vérifier PyInstaller
    if ! python -c "import PyInstaller" 2>/dev/null && ! python3 -c "import PyInstaller" 2>/dev/null; then
        echo "❌ PyInstaller non installé"
        echo "💡 Installation: pip install pyinstaller"
        exit 1
    fi
    
    # Vérifier le script principal
    if [ ! -f "$SCRIPT_NAME" ]; then
        echo "❌ Script principal '$SCRIPT_NAME' non trouvé"
        exit 1
    fi
    
    echo "✅ Tous les prérequis sont satisfaits"
    echo ""
}

# =============================================================================
# LANCEMENT DU SCRIPT
# =============================================================================
if [ "$#" -eq 0 ]; then
    check_requirements
    main_menu
else
    # Mode ligne de commande direct
    case "$1" in
        "macos")
            build_macos
            verify_build
            ;;
        "windows")
            build_windows
            verify_build
            ;;
        "spec")
            create_spec_file
            pyinstaller --clean --noconfirm "${APP_NAME}.spec"
            verify_build
            ;;
        "clean")
            cleanup_build
            ;;
        *)
            echo "Usage: $0 [macos|windows|spec|clean]"
            echo "Ou lancez sans argument pour le menu interactif"
            ;;
    esac
fi
# =============================================================================
# Système de traduction multilingue pour FitUploader
# =============================================================================

import json
import locale
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Any, Tuple
import logging

if sys.platform == 'win32':
    # Forcer UTF-8 pour console et logs sur Windows
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    os.environ['PYTHONIOENCODING'] = 'utf-8'  # Pour subprocess et env

logger = logging.getLogger(__name__)

class TranslationManager:
    """Gestionnaire de traductions multilingue avec détection améliorée"""
    
    def __init__(self, translations_dir: Path = None):
        self.translations_dir = translations_dir or Path(__file__).parent / "translations"
        self.current_language = "en"  # Langue par défaut
        self.translations: Dict[str, Dict[str, str]] = {}
        self.fallback_language = "fr"  # Langue de secours
        
        # Créer le dossier de traductions s'il n'existe pas
        self.translations_dir.mkdir(exist_ok=True)
        
        # AJOUTER: Log de démarrage
        logger.info(f"🌍 Initialisation du système de traduction...")
        logger.info(f"📁 Dossier de traductions: {self.translations_dir}")
        
        # Détection améliorée de la langue système
        logger.info(f"🔍 Démarrage de la détection de langue système...")
        self.detect_system_language()
        
        # Charger les traductions
        logger.info(f"📚 Chargement des traductions...")
        self.load_all_translations()
        
        # AJOUTER: Log final
        logger.info(f"✅ Système de traduction initialisé - Langue active: {self.current_language}")
    
    def detect_system_language(self):
        """Détection améliorée de la langue du système avec logs détaillés"""
        logger.info(f"🔍 === DÉBUT DÉTECTION LANGUE SYSTÈME ===")
        detected_lang = None
        detection_method = "default"
        
        try:
            # === MÉTHODE 1: locale.getlocale() ===
            try:
                system_locale = locale.getlocale()
                logger.info(f"System locale (getlocale): {system_locale}")
                
                if system_locale and system_locale[0]:
                    lang_code = system_locale[0].split('_')[0].lower()
                    logger.info(f"Extracted language code from getlocale: {lang_code}")
                    
                    if self._is_supported_language(lang_code):
                        detected_lang = lang_code
                        detection_method = "getlocale"
                        logger.info(f"✅ Langue détectée via getlocale(): {detected_lang}")
                    else:
                        logger.warning(f"❌ Langue non supportée via getlocale: {lang_code}")
                else:
                    logger.warning("❌ getlocale() n'a retourné aucune locale")
                    
            except Exception as e:
                logger.warning(f"❌ Erreur avec getlocale(): {e}")
            
            # === MÉTHODE 2: locale.getdefaultlocale() ===
            if not detected_lang:
                try:
                    default_locale = locale.getdefaultlocale()
                    logger.info(f"Default locale (getdefaultlocale): {default_locale}")
                    
                    if default_locale and default_locale[0]:
                        lang_code = default_locale[0].split('_')[0].lower()
                        logger.info(f"Extracted language code from getdefaultlocale: {lang_code}")
                        
                        if self._is_supported_language(lang_code):
                            detected_lang = lang_code
                            detection_method = "getdefaultlocale"
                            logger.info(f"✅ Langue détectée via getdefaultlocale(): {detected_lang}")
                        else:
                            logger.warning(f"❌ Langue non supportée via getdefaultlocale: {lang_code}")
                    else:
                        logger.warning("❌ getdefaultlocale() n'a retourné aucune locale")
                        
                except Exception as e:
                    logger.warning(f"❌ Erreur avec getdefaultlocale(): {e}")
            
            # === MÉTHODE 3: Variable d'environnement LANG (macOS/Unix) ===
            if not detected_lang:
                try:
                    lang_env = os.environ.get('LANG', '')
                    logger.info(f"Environment LANG variable: {lang_env}")
                    
                    if lang_env:
                        # Format typique: fr_FR.UTF-8, en_US.UTF-8, etc.
                        lang_code = lang_env.split('_')[0].split('.')[0].lower()
                        logger.info(f"Extracted language code from LANG: {lang_code}")
                        
                        if self._is_supported_language(lang_code):
                            detected_lang = lang_code
                            detection_method = "LANG_env"
                            
                            # Message spécial pour le français sur macOS
                            if lang_code == 'fr' and sys.platform == 'darwin':
                                logger.info(f"🇫🇷 Langue française détectée via variable d'environnement LANG")
                            else:
                                logger.info(f"✅ Langue détectée via variable LANG: {detected_lang}")
                        else:
                            logger.warning(f"❌ Langue non supportée via LANG: {lang_code}")
                    else:
                        logger.warning("❌ Variable LANG non définie")
                        
                except Exception as e:
                    logger.warning(f"❌ Erreur avec variable LANG: {e}")
            
            # === MÉTHODE 4: Autres variables d'environnement ===
            if not detected_lang:
                env_vars = ['LC_ALL', 'LC_MESSAGES', 'LANGUAGE']
                for var_name in env_vars:
                    try:
                        var_value = os.environ.get(var_name, '')
                        if var_value:
                            logger.info(f"Environment {var_name} variable: {var_value}")
                            lang_code = var_value.split('_')[0].split('.')[0].split(':')[0].lower()
                            
                            if self._is_supported_language(lang_code):
                                detected_lang = lang_code
                                detection_method = f"{var_name}_env"
                                logger.info(f"✅ Langue détectée via {var_name}: {detected_lang}")
                                break
                                
                    except Exception as e:
                        logger.debug(f"Erreur avec {var_name}: {e}")
            
            # === MÉTHODE 5: Détection spécifique macOS ===
            if not detected_lang and sys.platform == 'darwin':
                try:
                    import subprocess
                    result = subprocess.run(
                        ['defaults', 'read', '-g', 'AppleLocale'], 
                        capture_output=True, 
                        text=True, 
                        timeout=5
                    )
                    if result.returncode == 0:
                        apple_locale = result.stdout.strip()
                        logger.info(f"macOS AppleLocale: {apple_locale}")
                        
                        lang_code = apple_locale.split('_')[0].lower()
                        if self._is_supported_language(lang_code):
                            detected_lang = lang_code
                            detection_method = "macOS_AppleLocale"
                            logger.info(f"🍎 Langue détectée via AppleLocale macOS: {detected_lang}")
                            
                except Exception as e:
                    logger.debug(f"Erreur détection macOS: {e}")
            
        except Exception as e:
            logger.error(f"❌ Erreur critique lors de la détection de langue: {e}")
            logger.info(f"🔄 Utilisation de la langue par défaut: {self.current_language}")
            detected_lang = None  # Forcer l'utilisation du défaut en cas d'erreur critique

        # === RÉSULTAT FINAL (déplacé hors du try-except pour éviter la duplication) ===
        if detected_lang:
            self.current_language = detected_lang
            logger.info(f"🎯 LANGUE FINALE SÉLECTIONNÉE: {self.current_language} (méthode: {detection_method})")
        else:
            logger.warning(f"⚠️ Aucune langue supportée détectée, utilisation de la langue par défaut: {self.current_language}")
                
    
    def _is_supported_language(self, lang_code: str) -> bool:
        """Vérifier si une langue est supportée"""
        supported_languages = ['en', 'fr', 'es', 'de', 'it', 'nl', 'pt']
        is_supported = lang_code in supported_languages
        
        if is_supported:
            logger.debug(f"✅ Langue supportée: {lang_code}")
        else:
            logger.debug(f"❌ Langue non supportée: {lang_code} (supportées: {supported_languages})")
            
        return is_supported
    
    def load_translation(self, lang_code: str) -> Tuple[Dict[str, str], int]:
        """Charger une traduction depuis un fichier JSON avec compte des entrées"""
        translation_file = self.translations_dir / f"{lang_code}.json"
        
        if not translation_file.exists():
            logger.warning(f"📁 Fichier de traduction manquant: {translation_file}")
            return {}, 0
        
        try:
            with open(translation_file, 'r', encoding='utf-8') as f:
                translations = json.load(f)
            
            entry_count = len(translations)
            logger.info(f"✅ Traductions chargées avec succès pour: {lang_code} ({entry_count} entrées)")
            return translations, entry_count
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Erreur JSON dans {lang_code}.json: {e}")
            return {}, 0
        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement de {lang_code}.json: {e}")
            return {}, 0
    
    def load_all_translations(self):
        """Charger toutes les traductions disponibles avec logs détaillés"""
        logger.info("🔄 Début du chargement des traductions...")
        self.translations = {}
        
        # Langues supportées
        supported_languages = ['en', 'fr', 'es', 'de', 'it', 'nl', 'pt']
        logger.info(f"🌐 Langues supportées: {supported_languages}")
        
        loaded_count = 0
        total_entries = 0
        
        for lang in supported_languages:
            translations, entry_count = self.load_translation(lang)
            if translations:
                self.translations[lang] = translations
                loaded_count += 1
                total_entries += entry_count
        
        logger.info(f"📊 Résumé du chargement: {loaded_count}/{len(supported_languages)} langues chargées, {total_entries} entrées au total")
        logger.info("🔄 Fin du chargement des traductions.")
        
        # Vérifier si la langue courante est disponible
        if self.current_language in self.translations:
            entry_count = len(self.translations[self.current_language])
            logger.info(f"✅ Traductions disponibles pour la langue sélectionnée: {self.current_language} ({entry_count} entrées)")
        else:
            logger.warning(f"⚠️ Traductions manquantes pour la langue sélectionnée: {self.current_language}")
            
            # Vérifier la langue de secours
            if self.fallback_language in self.translations:
                entry_count = len(self.translations[self.fallback_language])
                logger.info(f"🔄 Langue de secours disponible: {self.fallback_language} ({entry_count} entrées)")
            else:
                logger.error(f"❌ Langue de secours indisponible: {self.fallback_language}")
        
        # Si aucune traduction n'est trouvée, créer les fichiers par défaut
        if not self.translations:
            logger.warning("🚨 Aucune traduction trouvée, création des fichiers par défaut...")
            self.create_default_translations()
    
    def create_default_translations(self):
        """Créer les fichiers de traduction par défaut avec logs"""
        logger.info("🔧 Création des traductions par défaut...")
        
        # Traductions par défaut (extraites de votre code actuel)
        default_translations = self.get_default_translations()
        
        created_count = 0
        for lang_code, translations in default_translations.items():
            success = self.save_translation(lang_code, translations)
            if success:
                self.translations[lang_code] = translations
                created_count += 1
        
        logger.info(f"✅ Fichiers de traduction créés: {created_count}/{len(default_translations)}")

    
    def get_default_translations(self) -> Dict[str, Dict[str, str]]:
        """Obtenir les traductions par défaut pour toutes les langues"""
        return {
            "fr": {
                # Interface principale
                "app_title": "FitUploader - MyWhoosh → Garmin Connect",
                "auth_section": "🔐 Authentification Garmin Connect",
                "email": "Email:",
                "password": "Mot de passe:",
                "remember_email": "Se souvenir de l'email",
                "login": "Se connecter",
                "logout": "Déconnecter",
                "connected": "✅ Connecté",
                "not_connected": "❌ Non connecté",
                
                # Configuration
                "config_section": "⚙️ Configuration",
                "backup_path": "Sauvegarde:",
                "sources": "Sources:",
                "sources_searching": "Recherche en cours...",
                
                # Fichiers
                "files_section": "📁 Fichiers FIT",
                "files_count": "fichiers",
                "file_name": "Nom du fichier",
                "date": "Date",
                "size": "Taille",
                "source": "Source",
                "status": "Statut",
                "processed": "Traité",
                "new": "Nouveau",
                "select_all": "Tout sélectionner",
                "deselect_all": "Tout désélectionner",
                "auto_select_new": "Sélectionner automatiquement les nouveaux fichiers",
                "files_selected": "fichier(s) sélectionné(s)",
                
                # Upload
                "upload_section": "🚀 Upload et Actions",
                "start_upload": "🚀 Démarrer l'upload",
                "stop_upload": "⏹️ Arrêter",
                "cleanup_list": "🧹 Nettoyer la liste",
                "ready": "Prêt",
                "upload_success": "Succès:",
                "upload_failed": "Échecs:",
                "upload_duplicates": "Doublons:",
                
                # Logs
                "logs_section": "📋 Journal des événements",
                "clear_logs": "Effacer les logs",
                
                # Messages
                "error": "Erreur",
                "success": "Succès",
                "warning": "Attention",
                "info": "Info",
                "login_required": "Veuillez vous connecter à Garmin Connect d'abord.",
                "no_files_selected": "Aucun fichier sélectionné.",
                "login_success": "Connecté à Garmin Connect!",
                "login_failed": "Échec de l'authentification. Vérifiez vos identifiants.",
                "upload_complete": "Upload terminé avec succès!",
                "upload_complete_errors": "Upload terminé avec {} échecs.",
                "processed_files_cleaned": "Liste des fichiers traités nettoyée.",
                
                # Tooltips
                "tooltip_browse": "Sélectionner le dossier de sauvegarde des fichiers traités",
                "tooltip_refresh": "Actualiser la détection des sources MyWhoosh",
                "tooltip_scan": "Scanner les fichiers FIT disponibles",
                "tooltip_auto_scan": "Scanner automatiquement toutes les 2 minutes",
                
                # Menu contextuel
                "mark_processed": "Marquer comme traité",
                "mark_new": "Marquer comme nouveau",
                
                # Statuts
                "authenticating": "Authentification en cours...",
                "scanning": "Scan en cours...",
                "scan_complete": "Scan terminé",
                "scan_error": "Erreur de scan",
                "uploading": "Upload en cours...",
                "upload_preparing": "Préparation de l'upload...",
                
                # Erreurs spécifiques
                "no_mywhoosh_detected": "Aucune source MyWhoosh détectée",
                "backup_folder_error": "Dossier non accessible en écriture.",
                "folder_selection_error": "Impossible de sélectionner le dossier."
            },
            
            "en": {
                # Main interface
                "app_title": "FitUploader Pro - MyWhoosh → Garmin Connect",
                "auth_section": "🔐 Garmin Connect Authentication",
                "email": "Email:",
                "password": "Password:",
                "remember_email": "Remember email",
                "login": "Login",
                "logout": "Logout",
                "connected": "✅ Connected",
                "not_connected": "❌ Not connected",
                
                # Configuration
                "config_section": "⚙️ Configuration",
                "backup_path": "Backup:",
                "sources": "Sources:",
                "sources_searching": "Searching...",
                
                # Files
                "files_section": "📁 FIT Files",
                "files_count": "files",
                "file_name": "File name",
                "date": "Date",
                "size": "Size",
                "source": "Source",
                "status": "Status",
                "processed": "Processed",
                "new": "New",
                "select_all": "Select all",
                "deselect_all": "Deselect all",
                "auto_select_new": "Automatically select new files",
                "files_selected": "file(s) selected",
                
                # Upload
                "upload_section": "🚀 Upload and Actions",
                "start_upload": "🚀 Start upload",
                "stop_upload": "⏹️ Stop",
                "cleanup_list": "🧹 Clean list",
                "ready": "Ready",
                "upload_success": "Success:",
                "upload_failed": "Failed:",
                "upload_duplicates": "Duplicates:",
                
                # Logs
                "logs_section": "📋 Event log",
                "clear_logs": "Clear logs",
                
                # Messages
                "error": "Error",
                "success": "Success",
                "warning": "Warning",
                "info": "Info",
                "login_required": "Please login to Garmin Connect first.",
                "no_files_selected": "No files selected.",
                "login_success": "Connected to Garmin Connect!",
                "login_failed": "Authentication failed. Check your credentials.",
                "upload_complete": "Upload completed successfully!",
                "upload_complete_errors": "Upload completed with {} failures.",
                "processed_files_cleaned": "Processed files list cleaned.",
                
                # Tooltips
                "tooltip_browse": "Select backup folder for processed files",
                "tooltip_refresh": "Refresh MyWhoosh sources detection",
                "tooltip_scan": "Scan available FIT files",
                "tooltip_auto_scan": "Automatically scan every 2 minutes",
                
                # Context menu
                "mark_processed": "Mark as processed",
                "mark_new": "Mark as new",
                
                # Status
                "authenticating": "Authenticating...",
                "scanning": "Scanning...",
                "scan_complete": "Scan complete",
                "scan_error": "Scan error",
                "uploading": "Uploading...",
                "upload_preparing": "Preparing upload...",
                
                # Specific errors
                "no_mywhoosh_detected": "No MyWhoosh source detected",
                "backup_folder_error": "Folder not writable.",
                "folder_selection_error": "Cannot select folder."
            },
            
            "es": {
                # Interfaz principal
                "app_title": "FitUploader Pro - MyWhoosh → Garmin Connect",
                "auth_section": "🔐 Autenticación Garmin Connect",
                "email": "Email:",
                "password": "Contraseña:",
                "remember_email": "Recordar email",
                "login": "Iniciar sesión",
                "logout": "Cerrar sesión",
                "connected": "✅ Conectado",
                "not_connected": "❌ No conectado",
                
                # Configuración
                "config_section": "⚙️ Configuración",
                "backup_path": "Copia de seguridad:",
                "sources": "Fuentes:",
                "sources_searching": "Buscando...",
                
                # Archivos
                "files_section": "📁 Archivos FIT",
                "files_count": "archivos",
                "file_name": "Nombre del archivo",
                "date": "Fecha",
                "size": "Tamaño",
                "source": "Fuente",
                "status": "Estado",
                "processed": "Procesado",
                "new": "Nuevo",
                "select_all": "Seleccionar todo",
                "deselect_all": "Deseleccionar todo",
                "auto_select_new": "Seleccionar automáticamente archivos nuevos",
                "files_selected": "archivo(s) seleccionado(s)",
                
                # Upload
                "upload_section": "🚀 Subida y Acciones",
                "start_upload": "🚀 Iniciar subida",
                "stop_upload": "⏹️ Detener",
                "cleanup_list": "🧹 Limpiar lista",
                "ready": "Listo",
                "upload_success": "Éxito:",
                "upload_failed": "Fallos:",
                "upload_duplicates": "Duplicados:",
                
                # Registros
                "logs_section": "📋 Registro de eventos",
                "clear_logs": "Limpiar registros",
                
                # Mensajes
                "error": "Error",
                "success": "Éxito",
                "warning": "Advertencia",
                "info": "Info",
                "login_required": "Por favor, inicia sesión en Garmin Connect primero.",
                "no_files_selected": "No hay archivos seleccionados.",
                "login_success": "¡Conectado a Garmin Connect!",
                "login_failed": "Error de autenticación. Verifica tus credenciales.",
                "upload_complete": "¡Subida completada con éxito!",
                "upload_complete_errors": "Subida completada con {} fallos.",
                "processed_files_cleaned": "Lista de archivos procesados limpiada."
            },
        "de": {
                # Hauptbenutzeroberfläche
                "app_title": "FitUploader Pro - MyWhoosh → Garmin Connect",
                "auth_section": "🔐 Garmin Connect Authentifizierung",
                "email": "E-Mail:",
                "password": "Passwort:",
                "remember_email": "E-Mail merken",
                "login": "Anmelden",
                "logout": "Abmelden",
                "connected": "✅ Verbunden",
                "not_connected": "❌ Nicht verbunden",
                
                # Konfiguration
                "config_section": "⚙️ Konfiguration",
                "backup_path": "Sicherung:",
                "sources": "Quellen:",
                "sources_searching": "Suche läuft...",
                
                # Dateien
                "files_section": "📂 FIT-Dateien",
                "files_count": "Dateien",
                "file_name": "Dateiname",
                "date": "Datum",
                "size": "Größe",
                "source": "Quelle",
                "status": "Status",
                "processed": "Verarbeitet",
                "new": "Neu",
                "select_all": "Alle auswählen",
                "deselect_all": "Alle abwählen",
                "auto_select_new": "Neue Dateien automatisch auswählen",
                "files_selected": "Datei(en) ausgewählt",
                
                # Upload
                "upload_section": "🚀 Upload und Aktionen",
                "start_upload": "🚀 Upload starten",
                "stop_upload": "⏹️ Stoppen",
                "cleanup_list": "🧹 Liste bereinigen",
                "ready": "Bereit",
                "upload_success": "Erfolg:",
                "upload_failed": "Fehlgeschlagen:",
                "upload_duplicates": "Duplikate:",
                
                # Protokolle
                "logs_section": "📋 Ereignisprotokoll",
                "clear_logs": "Protokolle löschen",
                
                # Nachrichten
                "error": "Fehler",
                "success": "Erfolg",
                "warning": "Warnung",
                "info": "Info",
                "login_required": "Bitte zuerst bei Garmin Connect anmelden.",
                "no_files_selected": "Keine Dateien ausgewählt.",
                "login_success": "Mit Garmin Connect verbunden!",
                "login_failed": "Authentifizierung fehlgeschlagen. Überprüfen Sie Ihre Anmeldedaten.",
                "upload_complete": "Upload erfolgreich abgeschlossen!",
                "upload_complete_errors": "Upload mit {} Fehlern abgeschlossen.",
                "processed_files_cleaned": "Liste der verarbeiteten Dateien bereinigt."
            },
            
            "it": {
                # Interfaccia principale
                "app_title": "FitUploader Pro - MyWhoosh → Garmin Connect",
                "auth_section": "🔐 Autenticazione Garmin Connect",
                "email": "Email:",
                "password": "Password:",
                "remember_email": "Ricorda email",
                "login": "Accedi",
                "logout": "Esci",
                "connected": "✅ Connesso",
                "not_connected": "❌ Non connesso",
                
                # Configurazione
                "config_section": "⚙️ Configurazione",
                "backup_path": "Backup:",
                "sources": "Fonti:",
                "sources_searching": "Ricerca in corso...",
                
                # File
                "files_section": "📂 File FIT",
                "files_count": "file",
                "file_name": "Nome file",
                "date": "Data",
                "size": "Dimensione",
                "source": "Fonte",
                "status": "Stato",
                "processed": "Elaborato",
                "new": "Nuovo",
                "select_all": "Seleziona tutto",
                "deselect_all": "Deseleziona tutto",
                "auto_select_new": "Seleziona automaticamente i nuovi file",
                "files_selected": "file selezionato/i",
                
                # Upload
                "upload_section": "🚀 Upload e Azioni",
                "start_upload": "🚀 Avvia upload",
                "stop_upload": "⏹️ Ferma",
                "cleanup_list": "🧹 Pulisci lista",
                "ready": "Pronto",
                "upload_success": "Successo:",
                "upload_failed": "Falliti:",
                "upload_duplicates": "Duplicati:",
                
                # Log
                "logs_section": "📋 Registro eventi",
                "clear_logs": "Pulisci log"
            },
            
            "nl": {
                # Hoofdinterface
                "app_title": "FitUploader Pro - MyWhoosh → Garmin Connect",
                "auth_section": "🔐 Garmin Connect Authenticatie",
                "email": "E-mail:",
                "password": "Wachtwoord:",
                "remember_email": "E-mail onthouden",
                "login": "Inloggen",
                "logout": "Uitloggen",
                "connected": "✅ Verbonden",
                "not_connected": "❌ Niet verbonden",
                
                # Configuratie
                "config_section": "⚙️ Configuratie",
                "backup_path": "Back-up:",
                "sources": "Bronnen:",
                "sources_searching": "Zoeken...",
                
                # Bestanden
                "files_section": "📂 FIT-bestanden",
                "files_count": "bestanden",
                "file_name": "Bestandsnaam",
                "date": "Datum",
                "size": "Grootte",
                "source": "Bron",
                "status": "Status",
                "processed": "Verwerkt",
                "new": "Nieuw",
                "select_all": "Alles selecteren",
                "deselect_all": "Alles deselecteren",
                "auto_select_new": "Nieuwe bestanden automatisch selecteren",
                "files_selected": "bestand(en) geselecteerd"
            }
        }
    
    def save_translation(self, lang_code: str, translations: Dict[str, str]):
        """Sauvegarder une traduction dans un fichier JSON"""
        translation_file = self.translations_dir / f"{lang_code}.json"
        
        try:
            with open(translation_file, 'w', encoding='utf-8') as f:
                json.dump(translations, f, indent=2, ensure_ascii=False)
            logger.info(f"Traduction sauvegardée: {lang_code}")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de {lang_code}: {e}")
    
    def get_available_languages(self) -> Dict[str, str]:
        """Obtenir la liste des langues disponibles"""
        return {
            'fr': 'Français',
            'en': 'English',
            'es': 'Español', 
            'de': 'Deutsch',
            'it': 'Italiano',
            'nl': 'Nederlands',
            'pt': 'Português'
        }
    
    def set_language(self, lang_code: str):
        """Changer la langue actuelle"""
        if lang_code in self.translations:
            self.current_language = lang_code
            logger.info(f"Langue changée vers: {lang_code}")
        else:
            logger.warning(f"Langue non disponible: {lang_code}")
    
    def translate(self, key: str, **kwargs) -> str:
        """Obtenir une traduction pour une clé donnée"""
        # Essayer avec la langue actuelle
        if self.current_language in self.translations:
            translation = self.translations[self.current_language].get(key)
            if translation:
                # Support pour les variables dans les traductions
                try:
                    return translation.format(**kwargs) if kwargs else translation
                except KeyError:
                    return translation
        
        # Essayer avec la langue de secours
        if self.fallback_language in self.translations:
            translation = self.translations[self.fallback_language].get(key)
            if translation:
                try:
                    return translation.format(**kwargs) if kwargs else translation
                except KeyError:
                    return translation
        
        # Retourner la clé si aucune traduction trouvée
        logger.debug(f"Traduction manquante pour la clé: {key}")
        return key
    
    def t(self, key: str, **kwargs) -> str:
        """Raccourci pour translate()"""
        return self.translate(key, **kwargs)


# =============================================================================
# Décorateur pour traduction automatique des widgets Tkinter
# =============================================================================

def translatable(translation_key: str):
    """Décorateur pour marquer les widgets comme traduisibles"""
    def decorator(widget_creation_func):
        def wrapper(*args, **kwargs):
            widget = widget_creation_func(*args, **kwargs)
            # Stocker la clé de traduction sur le widget
            if hasattr(widget, 'configure'):
                widget._translation_key = translation_key
            return widget
        return wrapper
    return decorator


# =============================================================================
# Classe pour l'intégration avec Tkinter
# =============================================================================

class TranslatableTkApp:
    """Mixin pour applications Tkinter avec support de traduction"""
    
    def __init__(self):
        self.translator = TranslationManager()
        self._translatable_widgets = []
    
    def register_translatable_widget(self, widget, text_key: str, text_type: str = "text"):
        """Enregistrer un widget pour les traductions automatiques"""
        self._translatable_widgets.append({
            'widget': widget,
            'text_key': text_key,
            'text_type': text_type  # 'text', 'title', 'tooltip', etc.
        })
    
    def update_translations(self):
        """Mettre à jour tous les widgets traduisibles"""
        for widget_info in self._translatable_widgets:
            widget = widget_info['widget']
            text_key = widget_info['text_key']
            text_type = widget_info['text_type']
            
            try:
                translated_text = self.translator.t(text_key)
                
                if text_type == "text":
                    if hasattr(widget, 'configure'):
                        widget.configure(text=translated_text)
                elif text_type == "title":
                    if hasattr(widget, 'title'):
                        widget.title(translated_text)
                elif text_type == "labelframe":
                    if hasattr(widget, 'configure'):
                        widget.configure(text=translated_text)
                        
            except Exception as e:
                logger.error(f"Erreur de traduction pour {text_key}: {e}")
    
    def change_language(self, lang_code: str):
        """Changer la langue de l'application"""
        self.translator.set_language(lang_code)
        self.update_translations()
        # Sauvegarder la préférence
        if hasattr(self, 'config_manager'):
            self.config_manager.set('language', lang_code)
    
    def t(self, key: str, **kwargs) -> str:
        """Raccourci pour accéder aux traductions"""
        return self.translator.t(key, **kwargs)


# =============================================================================
# Exemple d'utilisation dans votre application
# =============================================================================

"""
Exemple d'intégration dans FitUploaderApp:

class FitUploaderApp(tk.Tk, TranslatableTkApp):
    def __init__(self):
        tk.Tk.__init__(self)
        TranslatableTkApp.__init__(self)
        
        # Charger la langue sauvegardée
        saved_language = self.config_manager.get('language', 'fr')
        self.translator.set_language(saved_language)
        
        self.create_widgets()
        self.update_translations()
    
    def create_widgets(self):
        # Au lieu de:
        # ttk.Label(parent, text="Email:")
        
        # Utilisez:
        label = ttk.Label(parent)
        self.register_translatable_widget(label, "email", "text")
        
        # Ou créez une méthode helper:
        label = self.create_translatable_label(parent, "email")
    
    def create_translatable_label(self, parent, text_key, **kwargs):
        label = ttk.Label(parent, **kwargs)
        self.register_translatable_widget(label, text_key, "text")
        return label
    
    def create_language_menu(self):
        # Créer un menu de sélection de langue
        lang_menu = ttk.Combobox(
            parent, 
            values=list(self.translator.get_available_languages().values()),
            state="readonly"
        )
        lang_menu.bind('<<ComboboxSelected>>', self.on_language_change)
        return lang_menu
    
    def on_language_change(self, event):
        selected_lang = event.widget.get()
        # Trouver le code de langue
        for code, name in self.translator.get_available_languages().items():
            if name == selected_lang:
                self.change_language(code)
                break
"""
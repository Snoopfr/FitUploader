#!/usr/bin/env python3
"""
Application FitUploader
Usage: "python3 fituploader.py"
Description:
    - Interface graphique pour se connecter à Garmin Connect.
    - Recherche et traitement automatique des fichiers FIT provenant de deux sources :
         • MyWhoosh (détecté automatiquement selon l'OS)
         • TrainingPeaks Virtual (répertoire configurable)
    - Auto‑détection fiable de la source à utiliser en fonction des fichiers FIT.
    - Possibilité d'uploader plusieurs fichiers à la fois.
    - Sauvegarde des fichiers traités dans un même dossier de backup avec prefix selon la source (MW_ ou TPV_).
    - Sauvegarde de l'email et des chemins de configuration dans le répertoire personnel.
    - Interface modernisée (thème "clam", polices "Helvetica Neue", indicateurs visuels).
Crédits:
    Basé sur le script original myWhoosh2Garmin.py.
"""

import os
import json
import subprocess
import sys
import logging
import re
import threading
import time
from typing import List, Tuple, Optional, Dict
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import importlib.util

# --- Configuration globale et journalisation ---
SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "FitUploader.log"
# Le fichier de configuration est stocké dans le dossier personnel
CONFIG_FILE = Path.home() / ".fituploader_config.json"
TOKENS_PATH = SCRIPT_DIR / ".garth"
INSTALLED_PACKAGES_FILE = SCRIPT_DIR / "installed_packages.json"
FILE_DIALOG_TITLE = "FitUploader"

# Constants pour les préfixes de fichiers
MW_PREFIX = "MW_"
TPV_PREFIX = "TPV_"
MYWHOOSH_PREFIX_WINDOWS = "TheWhooshGame"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(LOG_FILE)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# --- Gestion de configuration ---
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erreur de lecture de config: {e}")
    return {}

def save_config(config: dict) -> None:
    try:
        with CONFIG_FILE.open("w") as f:
            json.dump(config, f)
    except Exception as e:
        logger.error(f"Erreur d'écriture de config: {e}")

config = load_config()

# --- Gestion de l'installation des packages requis ---
def load_installed_packages() -> set:
    if INSTALLED_PACKAGES_FILE.exists():
        with INSTALLED_PACKAGES_FILE.open("r") as f:
            return set(json.load(f))
    return set()

def save_installed_packages(installed_packages: set) -> None:
    with INSTALLED_PACKAGES_FILE.open("w") as f:
        json.dump(list(installed_packages), f)

def get_pip_command() -> Optional[list]:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return [sys.executable, "-m", "pip"]
    except subprocess.CalledProcessError:
        return None

def install_package(package: str) -> None:
    pip_command = get_pip_command()
    if pip_command:
        try:
            logger.info(f"Installation du package manquant: {package}.")
            subprocess.check_call(pip_command + ["install", package])
        except subprocess.CalledProcessError as e:
            logger.error(f"Erreur lors de l'installation de {package}: {e}.")
    else:
        logger.debug("pip n'est pas disponible.")

def ensure_packages() -> None:
    required_packages = ["garth", "fit_tool"]
    installed_packages = load_installed_packages()
    for package in required_packages:
        if package in installed_packages:
            logger.info(f"Le package {package} est déjà installé.")
            continue
        if not importlib.util.find_spec(package):
            logger.info(f"Le package {package} n'a pas été trouvé. Installation en cours...")
            install_package(package)
        try:
            __import__(package)
            logger.info(f"Importation de {package} réussie.")
            installed_packages.add(package)
        except ModuleNotFoundError:
            logger.error(f"Échec de l'importation de {package} après installation.")
    save_installed_packages(installed_packages)

ensure_packages()

# --- Import des modules tiers ---
try:
    import garth
    from garth.exc import GarthException, GarthHTTPError
    from fit_tool.fit_file import FitFile
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
    from fit_tool.profile.messages.record_message import RecordMessage, RecordTemperatureField
    from fit_tool.profile.messages.session_message import SessionMessage
    from fit_tool.profile.messages.lap_message import LapMessage
except ImportError as e:
    logger.error(f"Erreur d'importation des modules tiers: {e}")
    # Définir des variables globales pour éviter les erreurs NameError
    GarthException = Exception
    GarthHTTPError = Exception

# --- Fonctions utilitaires pour les fichiers FIT ---
def get_mywhoosh_directory() -> Path:
    """Retourne le chemin du répertoire MyWhoosh selon l'OS."""
    if os.name == "posix":  # macOS et Linux
        target = (Path.home() / "Library" / "Containers" / "com.whoosh.whooshgame" /
                  "Data" / "Library" / "Application Support" / "Epic" / "MyWhoosh" /
                  "Content" / "Data")
        if target.is_dir():
            return target
        else:
            logger.error(f"Le répertoire MyWhoosh {target} est introuvable.")
            return Path()
    elif os.name == "nt":  # Windows
        try:
            base = Path.home() / "AppData" / "Local" / "Packages"
            for directory in base.iterdir():
                if directory.is_dir() and directory.name.startswith(MYWHOOSH_PREFIX_WINDOWS):
                    target = directory / "LocalCache" / "Local" / "MyWhoosh" / "Content" / "Data"
                    if target.is_dir():
                        return target
            logger.error("Répertoire MyWhoosh introuvable.")
            return Path()
        except Exception as e:
            logger.error(str(e))
    else:
        logger.error("OS non supporté.")
        return Path()

def get_tp_directory() -> Optional[Path]:
    """
    Retourne le chemin du répertoire TrainingPeaks Virtual à partir de la config.
    S'il n'est pas défini, il est demandé à l'utilisateur.
    """
    path = config.get("tp_directory", "")
    if path and Path(path).is_dir():
        return Path(path)
    else:
        tp_path = filedialog.askdirectory(title="Sélectionnez le dossier TrainingPeaks Virtual")
        if tp_path:
            config["tp_directory"] = tp_path
            save_config(config)
            return Path(tp_path)
        else:
            return None

def get_backup_path() -> Path:
    """
    Retourne le chemin de sauvegarde pour les fichiers traités.
    S'il n'est pas défini, il est demandé à l'utilisateur.
    """
    path = config.get("backup_path", "")
    if path and Path(path).is_dir():
        return Path(path)
    else:
        backup = filedialog.askdirectory(title="Sélectionnez le dossier de sauvegarde")
        if backup:
            config["backup_path"] = backup
            save_config(config)
            return Path(backup)
        else:
            messagebox.showerror("Erreur", "Aucun dossier de sauvegarde sélectionné.")
            return Path()

def calculate_avg(values: iter) -> int:
    return sum(values) / len(values) if values else 0

def append_value(values: List[int], message: object, field_name: str) -> None:
    value = getattr(message, field_name, None)
    values.append(value if value else 0)

def reset_values() -> Tuple[List[int], List[int], List[int]]:
    return [], [], []

def cleanup_fit_file(fit_file_path: Path, new_file_path: Path) -> None:
    """
    Traite le fichier FIT : supprime la température, calcule les moyennes, et sauvegarde dans un nouveau fichier.
    """
    try:
        builder = FitFileBuilder()
        fit_file = FitFile.from_file(str(fit_file_path))
        cadence_values, power_values, heart_rate_values = reset_values()
        for record in fit_file.records:
            message = record.message
            if isinstance(message, LapMessage):
                continue
            if isinstance(message, RecordMessage):
                message.remove_field(RecordTemperatureField.ID)
                append_value(cadence_values, message, "cadence")
                append_value(power_values, message, "power")
                append_value(heart_rate_values, message, "heart_rate")
            if isinstance(message, SessionMessage):
                if not message.avg_cadence:
                    message.avg_cadence = calculate_avg(cadence_values)
                if not message.avg_power:
                    message.avg_power = calculate_avg(power_values)
                if not message.avg_heart_rate:
                    message.avg_heart_rate = calculate_avg(heart_rate_values)
                cadence_values, power_values, heart_rate_values = reset_values()
            builder.add(message)
        builder.build().to_file(str(new_file_path))
        logger.info(f"Fichier nettoyé sauvegardé sous {new_file_path.name}")
        return True
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage du fichier {fit_file_path.name}: {e}")
        return False

def get_fit_files(source_dir: Path) -> List[Path]:
    """Retourne la liste des fichiers FIT dans le répertoire source."""
    if not source_dir or not source_dir.is_dir():
        return []
    return sorted(list(source_dir.glob("MyNewActivity-*.fit")), 
                  key=lambda f: f.stat().st_mtime, reverse=True)

def detect_source_for_file(file_path: Path, myw_dir: Path, tp_dir: Path) -> str:
    """Détermine la source d'un fichier FIT par comparaison avec les répertoires sources."""
    if not file_path.exists():
        return ""
    
    # Convertir en absolus pour comparaison
    file_abs = file_path.resolve()
    myw_abs = myw_dir.resolve() if myw_dir and myw_dir.exists() else None
    tp_abs = tp_dir.resolve() if tp_dir and tp_dir.exists() else None
    
    # Vérifier si le fichier est dans un des répertoires
    if myw_abs and str(file_abs).startswith(str(myw_abs)):
        return "MyWhoosh"
    elif tp_abs and str(file_abs).startswith(str(tp_abs)):
        return "TrainingPeaks Virtual"
    
    # Si on n'a pas pu déterminer par le chemin, on essaie d'analyser le contenu
    try:
        fit_file = FitFile.from_file(str(file_path))
        for record in fit_file.records:
            message = record.message
            if isinstance(message, SessionMessage) and hasattr(message, "sub_sport"):
                # MyWhoosh utilise généralement des valeurs spécifiques pour sub_sport
                if message.sub_sport == 3:  # Virtual Activity
                    return "MyWhoosh"
        # Par défaut, si on a pas d'autre information
        return "TrainingPeaks Virtual"
    except Exception as e:
        logger.warning(f"Impossible d'analyser le fichier pour déterminer la source: {e}")
        # Si on ne peut pas analyser, on regarde la date de dernière modification
        if not myw_abs or not tp_abs:
            return "Source inconnue"
        
        # Récupérer les derniers fichiers de chaque source
        last_myw = get_most_recent_fit_time(myw_dir)
        last_tp = get_most_recent_fit_time(tp_dir)
        
        # Comparer avec la date du fichier
        file_time = file_path.stat().st_mtime
        myw_diff = abs(file_time - last_myw) if last_myw else float('inf')
        tp_diff = abs(file_time - last_tp) if last_tp else float('inf')
        
        if myw_diff < tp_diff:
            return "MyWhoosh"
        else:
            return "TrainingPeaks Virtual"

def get_most_recent_fit_time(source_dir: Path) -> float:
    """Retourne la date de dernière modification du fichier FIT le plus récent."""
    if not source_dir or not source_dir.is_dir():
        return 0
    
    files = get_fit_files(source_dir)
    if files:
        return files[0].stat().st_mtime
    return 0

def generate_new_filename(fit_file: Path, source: str) -> str:
    """Génère un nouveau nom de fichier avec préfixe selon la source et horodatage."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    prefix = MW_PREFIX if source == "MyWhoosh" else TPV_PREFIX
    
    # Extraction du numéro d'activité si possible
    match = re.search(r'MyNewActivity-(\d+)\.fit', fit_file.name)
    activity_num = f"_{match.group(1)}" if match else ""
    
    return f"{prefix}{timestamp}{activity_num}.fit"

def cleanup_and_save_fit_files(sources: Dict[str, Path], backup_dir: Path) -> List[Path]:
    """
    Trouve, traite et sauvegarde les fichiers FIT les plus récents de chaque source.
    Retourne la liste des nouveaux fichiers traités.
    """
    if not backup_dir.exists():
        logger.error(f"Le dossier de sauvegarde {backup_dir} n'existe pas.")
def cleanup_and_save_fit_files(sources: Dict[str, Path], backup_dir: Path) -> List[Path]:
    """
    Trouve, traite et sauvegarde les fichiers FIT les plus récents de chaque source.
    Retourne la liste des nouveaux fichiers traités.
    """
    if not backup_dir.exists():
        logger.error(f"Le dossier de sauvegarde {backup_dir} n'existe pas.")
        return []
    
    processed_files = []
    
    # Pour chaque source configurée
    for source_name, source_dir in sources.items():
        if not source_dir or not source_dir.is_dir():
            logger.debug(f"Source {source_name} non configurée ou invalide.")
            continue
        
        # Récupérer les fichiers FIT de la source
        fit_files = get_fit_files(source_dir)
        if not fit_files:
            logger.info(f"Aucun fichier FIT trouvé dans {source_name}.")
            continue
        
        # Traiter chaque fichier
        for fit_file in fit_files:
            # Vérifier si le fichier a déjà été traité
            is_already_processed = False
            for existing_file in backup_dir.glob(f"*_{fit_file.name.split('-')[-1]}"):
                logger.debug(f"Le fichier {fit_file.name} semble déjà avoir été traité.")
                is_already_processed = True
                break
                
            if is_already_processed:
                continue
            
            # Générer le nouveau nom avec préfixe selon la source
            new_filename = generate_new_filename(fit_file, source_name)
            new_file = backup_dir / new_filename
            
            # Traiter et sauvegarder le fichier
            logger.info(f"Traitement du fichier {fit_file.name} de {source_name}...")
            success = cleanup_fit_file(fit_file, new_file)
            
            if success:
                processed_files.append(new_file)
                logger.info(f"Fichier sauvegardé sous {new_file.name}")
            
    return processed_files

from typing import List, Dict
from pathlib import Path
import time
from garth.exc import GarthHTTPError
import logging

logger = logging.getLogger(__name__)

def upload_fit_files_to_garmin(files: List[Path]) -> Dict[Path, bool]:
    results = {}
    for file_path in files:
        try:
            if file_path.exists():
                logger.info(f"Envoi du fichier {file_path.name} vers Garmin Connect...")
                with open(file_path, "rb") as f:
                    response = garth.client.upload(f)
                    logger.debug(f"Réponse Garmin: {response}")
                results[file_path] = True
                logger.info(f"Upload réussi pour {file_path.name}")
                time.sleep(1)
            else:
                logger.info(f"Fichier invalide: {file_path}.")
                results[file_path] = False
        except GarthHTTPError as e:
            # Vérification du statut dans le message d'erreur si 'response' n'est pas disponible
            if "409 Client Error" in str(e):
                logger.info(f"Le fichier {file_path.name} est déjà présent sur Garmin Connect (conflit 409).")
                results[file_path] = True  # Succès, car le fichier est déjà sur le serveur
            else:
                logger.error(f"Erreur lors de l'upload de {file_path.name}: {e}")
                results[file_path] = False
        except Exception as e:
            logger.error(f"Erreur inattendue lors de l'upload de {file_path.name}: {e}")
            results[file_path] = False
    return results

def get_available_sources() -> Dict[str, Path]:
    """Retourne un dictionnaire des sources disponibles avec leur chemin."""
    sources = {}
    
    # MyWhoosh
    myw_dir = get_mywhoosh_directory()
    if myw_dir and myw_dir.is_dir() and get_fit_files(myw_dir):
        sources["MyWhoosh"] = myw_dir
    
    # TrainingPeaks Virtual
    tp_dir = get_tp_directory()
    if tp_dir and tp_dir.is_dir() and get_fit_files(tp_dir):
        sources["TrainingPeaks Virtual"] = tp_dir
    
    return sources

# --- Fonctions d'authentification ---
def authenticate_to_garmin_gui(email: str, password: str) -> bool:
    # Importer les modules nécessaires
    import garth
    from garth.exc import GarthHTTPError
    
    logger.info("Tentative d'authentification sur Garmin Connect...")
    try:
        garth.login(email, password)
        garth.save(TOKENS_PATH)
        logger.info(f"Authentification réussie pour {email}.")
        return True
    except GarthHTTPError as e:
        logger.error(f"Erreur d'authentification HTTP: {e}")
        return False
    except Exception as e:
        logger.error(f"Erreur d'authentification: {e}")
        return False

def try_token_auth() -> bool:
    """Tente d'authentifier avec un token existant."""
    # Importer les modules nécessaires
    import garth
    
    if TOKENS_PATH.exists():
        try:
            garth.resume(TOKENS_PATH)
            # Vérifier si le token est valide
            try:
                garth.client.username
                logger.info("Authentification par token réussie.")
                return True
            except:
                logger.info("Token expiré ou invalide.")
                return False
        except Exception as e:
            logger.error(f"Erreur lors de la reprise de session: {e}")
    return False

# --- Gestionnaire de log pour l'interface graphique ---
class TextHandler(logging.Handler):
    def __init__(self, widget: tk.Text):
        super().__init__()
        self.widget = widget

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.widget.configure(state='normal')
            self.widget.insert(tk.END, msg + "\n")
            self.widget.configure(state='disabled')
            self.widget.yview(tk.END)
        self.widget.after(0, append)
# --- Application Tkinter améliorée ---
class FitUploaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FitUploader")
        self.geometry("750x800")
        self.resizable(False, False)
        
        # Initialisation des chemins
        self.backup_dir = get_backup_path()
        
        # Configuration des sources
        self.sources = get_available_sources()
        self.setup_style()
        self.create_widgets()
        self.add_logging_handler()
        
        # Pré-remplir l'email si sauvegardé
        if config.get("username"):
            self.username_entry.insert(0, config["username"])
        
        # Tenter une authentification avec un token existant
        if try_token_auth():
            self.set_connection_status(True)
        else:
            self.set_connection_status(False)
        
        self.set_upload_status(False)
        self.update_source_display()

    def setup_style(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        base_font = ("Helvetica Neue", 12)
        bold_font = ("Helvetica Neue", 12, "bold")
        self.style.configure("TLabel", font=base_font, foreground="#333333")
        self.style.configure("TCheckbutton", font=base_font)
        self.style.configure("TEntry", font=base_font)
        self.style.configure("Red.TButton", font=bold_font, foreground="white", background="#d9534f", padding=6)
        self.style.map("Red.TButton", background=[("active", "#c9302c")])
        self.style.configure("Green.TButton", font=bold_font, foreground="white", background="#5cb85c", padding=6)
        self.style.map("Green.TButton", background=[("active", "#449d44")])
        self.style.configure("Blue.TButton", font=bold_font, foreground="white", background="#337ab7", padding=6)
        self.style.map("Blue.TButton", background=[("active", "#286090")])
        self.style.configure("Log.TText", font=("Helvetica Neue", 10))
    
    def create_widgets(self):
        # Cadre d'authentification
        auth_frame = ttk.LabelFrame(self, text="Authentification Garmin Connect")
        auth_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(auth_frame, text="Email:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.username_entry = ttk.Entry(auth_frame, width=30)
        self.username_entry.grid(row=0, column=1, padx=5, pady=5)
        self.remember_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(auth_frame, text="Se souvenir de mon email", variable=self.remember_var).grid(row=0, column=2, padx=5, pady=5)
        ttk.Label(auth_frame, text="Mot de passe:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.password_entry = ttk.Entry(auth_frame, width=30, show="*")
        self.password_entry.grid(row=1, column=1, padx=5, pady=5)
        self.login_button = ttk.Button(auth_frame, text="Se connecter", command=self.login, style="Blue.TButton")
        self.login_button.grid(row=2, column=0, columnspan=2, pady=10)
        self.conn_status_label = ttk.Label(auth_frame, text="Non connecté", foreground="red")
        self.conn_status_label.grid(row=2, column=2, padx=5, pady=10)
        
        # Cadre de configuration
        config_frame = ttk.LabelFrame(self, text="Configuration")
        config_frame.pack(fill="x", padx=10, pady=10)
        self.backup_label = ttk.Label(config_frame, text=f"Dossier de sauvegarde: {self.backup_dir}")
        self.backup_label.grid(row=0, column=0, padx=5, pady=5, sticky="w", columnspan=2)
        ttk.Button(config_frame, text="Modifier", command=self.change_backup_path).grid(row=0, column=2, padx=5, pady=5)
        
        # Affichage des sources
        self.sources_frame = ttk.LabelFrame(config_frame, text="Sources détectées")
        self.sources_frame.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        
        # Boutons pour rafraîchir les sources et configurer TrainingPeaks
        config_buttons_frame = ttk.Frame(config_frame)
        config_buttons_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        # Configuration des colonnes pour un redimensionnement adaptable
        config_buttons_frame.columnconfigure(0, weight=1)
        config_buttons_frame.columnconfigure(1, weight=1)

        # Placement des boutons
        ttk.Button(config_buttons_frame, text="Rafraîchir les sources", command=self.refresh_sources).grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ttk.Button(config_buttons_frame, text="Configurer TrainingPeaks", command=self.change_tp_path).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        # Cadre d'opérations
        op_frame = ttk.LabelFrame(self, text="Opérations")
        op_frame.pack(fill="x", padx=10, pady=10)
        
        # Options d'upload
        self.multi_upload_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(op_frame, text="Traiter tous les fichiers disponibles", variable=self.multi_upload_var).pack(anchor="w", padx=5, pady=5)
        
        self.upload_button = ttk.Button(op_frame, text="Envoyer sur Garmin Connect", command=self.upload_files, style="Red.TButton")
        self.upload_button.pack(pady=10)
        self.upload_status_label = ttk.Label(op_frame, text="Upload non effectué", foreground="red")
        self.upload_status_label.pack(pady=5)
        
        # Zone de log
        log_frame = ttk.LabelFrame(self, text="Journal (log)")
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, state="disabled", wrap="word", font=("Helvetica Neue", 10))
        self.log_text.pack(fill="both", expand=True)
        
        # Scrollbar pour la zone de log
        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def update_source_display(self):
        """Met à jour l'affichage des sources détectées."""
        # Nettoyer le frame existant
        for widget in self.sources_frame.winfo_children():
            widget.destroy()
        
        # Afficher les sources disponibles
        if not self.sources:
            ttk.Label(self.sources_frame, text="Aucune source avec des fichiers FIT détectée", foreground="red").pack(padx=5, pady=5)
        else:
            for idx, (name, path) in enumerate(self.sources.items()):
                ttk.Label(self.sources_frame, text=f"{name}: {path}", foreground="green").pack(anchor="w", padx=5, pady=2)
                # Afficher le nombre de fichiers FIT disponibles
                files = get_fit_files(path)
                ttk.Label(self.sources_frame, text=f"    {len(files)} fichier(s) FIT disponible(s)", foreground="blue").pack(anchor="w", padx=15, pady=1)

    def add_logging_handler(self):
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(formatter)
        logger.addHandler(text_handler)

    def set_connection_status(self, connected: bool):
        if connected:
            self.conn_status_label.config(text="Connecté", foreground="green")
            self.login_button.config(style="Green.TButton")
            self.upload_button.config(state="normal")
        else:
            self.conn_status_label.config(text="Non connecté", foreground="red")
            self.login_button.config(style="Blue.TButton")
            self.upload_button.config(state="disabled")
    
    def set_upload_status(self, success: bool):
        if success:
            self.upload_status_label.config(text="Upload réussi", foreground="green")
            self.upload_button.config(style="Green.TButton")
        else:
            self.upload_status_label.config(text="Upload non effectué", foreground="red")
            self.upload_button.config(style="Red.TButton")
    
    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        
        if not username or not password:
            messagebox.showerror("Erreur", "Veuillez entrer votre email et mot de passe.")
            return
        
        if self.remember_var.get():
            config["username"] = username
            save_config(config)
        
        self.login_button.config(text="Connexion en cours...", state="disabled")
        self.update()
        
        # Authentification dans un thread séparé pour ne pas bloquer l'interface
        def auth_thread():
            success = authenticate_to_garmin_gui(username, password)
            self.after(0, lambda: self.after_login(success))
        
        threading.Thread(target=auth_thread).start()
    
    def after_login(self, success: bool):
        self.login_button.config(text="Se connecter", state="normal")
        self.set_connection_status(success)
        
        if success:
            messagebox.showinfo("Succès", "Authentification réussie!")
        else:
            messagebox.showerror("Erreur", "Échec de l'authentification.\nVérifiez vos identifiants.")
    
    def change_backup_path(self):
        backup = filedialog.askdirectory(title="Sélectionnez le dossier de sauvegarde")
        if backup:
            self.backup_dir = Path(backup)
            config["backup_path"] = backup
            save_config(config)
            self.backup_label.config(text=f"Dossier de sauvegarde: {self.backup_dir}")
    
    def change_tp_path(self):
        tp_path = filedialog.askdirectory(title="Sélectionnez le dossier TrainingPeaks Virtual")
        if tp_path:
            config["tp_directory"] = tp_path
            save_config(config)
            self.refresh_sources()
    
    def refresh_sources(self):
        self.sources = get_available_sources()
        self.update_source_display()
    
    def upload_files(self):
        if not self.sources:
            messagebox.showerror("Erreur", "Aucune source disponible.")
            return
        
        self.upload_button.config(text="Traitement en cours...", state="disabled")
        self.update()
        
        def process_thread():
            # Traiter et sauvegarder les fichiers FIT
            processed_files = cleanup_and_save_fit_files(self.sources, self.backup_dir)
            
            if not processed_files:
                self.after(0, lambda: self.after_upload(False, "Aucun nouveau fichier à traiter."))
                return
            
            # Uploader les fichiers traités
            results = upload_fit_files_to_garmin(processed_files)
            
            # Déterminer le statut global
            all_success = all(results.values()) if results else False
            message = f"{sum(results.values())}/{len(results)} fichier(s) uploadé(s) avec succès." if results else "Aucun fichier traité."
            
            self.after(0, lambda: self.after_upload(all_success, message))
        
        threading.Thread(target=process_thread).start()
    
    def after_upload(self, success: bool, message: str):
        self.upload_button.config(text="Envoyer sur Garmin Connect", state="normal")
        self.set_upload_status(success)
        
        if success:
            messagebox.showinfo("Résultat", message)
        else:
            messagebox.showwarning("Résultat", message)
        
        # Rafraîchir les sources après l'upload
        self.refresh_sources()


# --- Point d'entrée principal ---
if __name__ == "__main__":
    app = FitUploaderApp()
    app.mainloop()
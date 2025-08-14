#!/usr/bin/env python3
import os
import json
import subprocess
import sys
import logging
import re
import threading
import time
import asyncio
from typing import List, Tuple, Optional, Dict, Set, Generator
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import importlib.util
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import weakref
from functools import lru_cache, wraps
import hashlib
from logging.handlers import RotatingFileHandler
from translations import TranslatableTkApp
import platform
from functools import lru_cache

class OSDetector:
    """Détection robuste du système d'exploitation"""
    
    @staticmethod
    @lru_cache(maxsize=1)
    def get_system():
        """Cache le résultat de détection du système"""
        return platform.system()
    
    @staticmethod
    def is_windows():
        return OSDetector.get_system() == 'Windows'
    
    @staticmethod
    def is_macos():
        return OSDetector.get_system() == 'Darwin'
    
    @staticmethod
    def is_linux():
        return OSDetector.get_system() == 'Linux'
    
    @staticmethod
    def get_os_info():
        """Informations détaillées sur l'OS"""
        return {
            'system': platform.system(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor()
        }

class AppConfig:
    SCRIPT_DIR = Path(__file__).resolve().parent
    LOG_FILE = SCRIPT_DIR / "FitUploader.log"
    CONFIG_FILE = Path.home() / ".fituploader_config.json"
    TOKENS_PATH = SCRIPT_DIR / ".garth"
    MW_PREFIX = "MW_"
    MYWHOOSH_PREFIXES_WINDOWS = [
        "TheWhooshGame",
        "MyWhoosh", 
        "Whoosh",
        "com.whoosh"
    ]
    MYWHOOSH_PATHS_LINUX = [
        Path.home() / ".local" / "share" / "MyWhoosh",
        Path.home() / "MyWhoosh",
        Path("/opt/MyWhoosh")
    ]
    SCAN_CACHE_DURATION = 30
    UPLOAD_TIMEOUT = 45
    MAX_RETRY_ATTEMPTS = 3
    MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 3
    MAX_CONCURRENT_UPLOADS = 2
    UI_UPDATE_INTERVAL = 100
    FILE_CHUNK_SIZE = 8192


class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class FileInfo:
    name: str
    path: Path
    size: str
    date: str
    source: str
    processed: bool
    modified_time: datetime
    file_hash: str = field(default="")
    size_bytes: int = field(default=0)

    def __post_init__(self):
        if not self.file_hash and self.path.exists():
            self.file_hash = self._calculate_hash()
        if not self.size_bytes:
            try:
                self.size_bytes = self.path.stat().st_size
            except (OSError, FileNotFoundError):
                self.size_bytes = 0

    def _calculate_hash(self) -> str:
        """Calculate SHA256 hash of file for integrity checking"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(self.path, "rb") as f:
                for chunk in iter(lambda: f.read(AppConfig.FILE_CHUNK_SIZE), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()[:16]  # First 16 chars for storage efficiency
        except Exception:
            return ""


class Colors:
    PRIMARY = '#2563eb'
    SUCCESS = '#10b981'
    WARNING = '#f59e0b'
    ERROR = '#ef4444'
    BACKGROUND = '#f8fafc'
    SURFACE = '#ffffff'
    TEXT = '#1e293b'
    TEXT_SECONDARY = '#64748b'
    ACCENT = '#8b5cf6'
    INFO = '#3b82f6'


def retry_on_exception(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Decorator for retrying functions on exception"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.debug(f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}")
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator


def setup_logger():
    """Enhanced logger setup with rotation"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    
    if not logger.handlers:
        # Rotating file handler
        file_handler = RotatingFileHandler(
            AppConfig.LOG_FILE, 
            maxBytes=AppConfig.MAX_LOG_SIZE,
            backupCount=AppConfig.LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(threadName)s] - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


logger = setup_logger()


class ConfigManager:
    """Enhanced configuration manager with validation and atomic operations"""
    
    def __init__(self):
        self._config = {}
        self._shutting_down = False
        self._lock = threading.RLock()
        self._dirty = False
        self._auto_save_timer = None
        self.load()

    def load(self) -> None:
        """Load configuration with validation"""
        with self._lock:
            if AppConfig.CONFIG_FILE.exists():
                try:
                    with AppConfig.CONFIG_FILE.open("r", encoding='utf-8') as f:
                        loaded_config = json.load(f)
                    self._config = self._validate_config(loaded_config)
                    logger.debug("Configuration chargée avec succès")
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Erreur de lecture de config: {e}")
                    self._config = self._get_default_config()
            else:
                self._config = self._get_default_config()

    def _validate_config(self, config: dict) -> dict:
        """Validate and sanitize configuration"""
        default_config = self._get_default_config()
        validated = default_config.copy()
        
        for key, value in config.items():
            if key in default_config:
                # Type validation
                expected_type = type(default_config[key])
                if isinstance(value, expected_type):
                    validated[key] = value
                else:
                    logger.warning(f"Config key '{key}' has wrong type, using default")
        
        return validated

    def _get_default_config(self) -> dict:
        """Get default configuration"""
        return {
            'username': '',
            'backup_path': '',
            'processed_files': {},
            'auto_select_new': True,
            'max_concurrent_uploads': AppConfig.MAX_CONCURRENT_UPLOADS,
            'auto_save_interval': 30,
            'ui_theme': 'default',
            'log_level': 'INFO'
        }

    def save(self, force: bool = False) -> None:
        """Save configuration atomically"""
        with self._lock:
            if not self._dirty and not force:
                return
                
            try:
                # Atomic write using temporary file
                temp_file = AppConfig.CONFIG_FILE.with_suffix('.tmp')
                AppConfig.CONFIG_FILE.parent.mkdir(exist_ok=True)
                
                with temp_file.open("w", encoding='utf-8') as f:
                    json.dump(self._config, f, indent=2, ensure_ascii=False)
                
                # Atomic move
                temp_file.replace(AppConfig.CONFIG_FILE)
                self._dirty = False
                logger.debug("Configuration sauvegardée")
                
            except Exception as e:
                logger.error(f"Erreur d'écriture de config: {e}")

    def get(self, key: str, default=None):
        """Get configuration value with thread safety"""
        with self._lock:
            return self._config.get(key, default)

    def set(self, key: str, value) -> None:
        """Set configuration value with auto-save scheduling"""
        with self._lock:
            if self._config.get(key) != value:
                self._config[key] = value
                self._dirty = True
                
                # Schedule auto-save for important keys
                if key in ['username', 'backup_path', 'processed_files']:
                    self._schedule_auto_save()

    def _schedule_auto_save(self):
        """Schedule automatic save with debouncing"""
        if self._auto_save_timer:
            self._auto_save_timer.cancel()
        
        self._auto_save_timer = threading.Timer(2.0, self.save)
        self._auto_save_timer.start()

    def __del__(self):
        try:
            if self._auto_save_timer:
                self._auto_save_timer.cancel()
            if hasattr(self, '_config'):
                self.save(force=True)
        except:
            pass


class PackageManager:
    """Enhanced package management with better error handling"""
    
    _package_cache = {}
    _lock = threading.Lock()
    
    @staticmethod
    @lru_cache(maxsize=1)
    def get_pip_command() -> Optional[List[str]]:
        """Get pip command with caching"""
        commands_to_try = [
            [sys.executable, "-m", "pip"],
            ["pip3"],
            ["pip"]
        ]
        
        for cmd in commands_to_try:
            try:
                result = subprocess.run(
                    cmd + ["--version"],
                    capture_output=True,
                    timeout=10,
                    check=True
                )
                if result.returncode == 0:
                    return cmd
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                continue
        
        return None

    @staticmethod
    @retry_on_exception(max_retries=2, delay=1.0)
    def install_package(package: str) -> bool:
        """Install package with retry logic"""
        pip_command = PackageManager.get_pip_command()
        if not pip_command:
            logger.error("pip n'est pas disponible")
            return False
        
        try:
            logger.info(f"Installation du package: {package}")
            result = subprocess.run(
                pip_command + ["install", "--user", package], 
                capture_output=True,
                timeout=180,
                text=True,
                check=True
            )
            logger.debug(f"Installation output: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Erreur lors de l'installation de {package}: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout lors de l'installation de {package}")
            return False

    @staticmethod
    def ensure_packages() -> bool:
        """Ensure required packages with caching"""
        with PackageManager._lock:
            required_packages = ["garth", "fit_tool"]
            
            for package in required_packages:
                # Check cache first
                if package in PackageManager._package_cache:
                    continue
                
                try:
                    __import__(package)
                    PackageManager._package_cache[package] = True
                    logger.debug(f"Package {package} déjà disponible")
                except ImportError:
                    logger.info(f"Installation du package manquant: {package}")
                    if not PackageManager.install_package(package):
                        return False
                    
                    try:
                        # Clear import cache and re-import
                        if package in sys.modules:
                            del sys.modules[package]
                        __import__(package)
                        PackageManager._package_cache[package] = True
                        logger.info(f"Package {package} installé avec succès")
                    except ImportError:
                        logger.error(f"Échec de l'importation de {package}")
                        return False
            
            return True


class FitFileManager:
    """Enhanced file management with caching and integrity checking"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self._cache = {}
        self._cache_time = None
        self._cache_lock = threading.RLock()
        self._sources_cache = None
        self._sources_cache_time = None

    @lru_cache(maxsize=10)
    def _get_mywhoosh_paths(self) -> List[Path]:
        """Get possible MyWhoosh directories with caching"""
        paths = []
        
        try:
            if os.name == "posix":  # macOS/Linux
                mac_path = (Path.home() / "Library" / "Containers" / "com.whoosh.whooshgame" /
                           "Data" / "Library" / "Application Support" / "Epic" / "MyWhoosh" /
                           "Content" / "Data")
                if mac_path.is_dir():
                    paths.append(mac_path)
                    
            elif os.name == "nt":  # Windows
                base = Path.home() / "AppData" / "Local" / "Packages"
                if base.exists():
                    for directory in base.iterdir():
                        if (directory.is_dir() and 
                            directory.name.startswith(AppConfig.MYWHOOSH_PREFIX_WINDOWS)):
                            target = (directory / "LocalCache" / "Local" / 
                                    "MyWhoosh" / "Content" / "Data")
                            if target.is_dir():
                                paths.append(target)
                                
        except Exception as e:
            logger.error(f"Erreur lors de la recherche des répertoires MyWhoosh: {e}")
        
        return paths

    def get_mywhoosh_directory(self) -> Optional[Path]:
        """Get first available MyWhoosh directory"""
        paths = self._get_mywhoosh_paths()
        return paths[0] if paths else None

    def get_backup_path(self) -> Optional[Path]:
        """Get backup path with validation"""
        path = self.config.get("backup_path", "")
        if path:
            backup_path = Path(path)
            if backup_path.is_dir() and os.access(backup_path, os.W_OK):
                return backup_path
        return None

    def get_available_sources(self) -> Dict[str, Path]:
        """Get available sources with caching"""
        now = datetime.now()
        if (self._sources_cache and self._sources_cache_time and
            (now - self._sources_cache_time).seconds < 60):
            return self._sources_cache
        
        sources = {}
        for i, path in enumerate(self._get_mywhoosh_paths()):
            source_name = f"MyWhoosh" if i == 0 else f"MyWhoosh_{i+1}"
            sources[source_name] = path
        
        self._sources_cache = sources
        self._sources_cache_time = now
        return sources

    def get_fit_files(self, source_dir: Path) -> Generator[Path, None, None]:
        """Get FIT files as generator for memory efficiency"""
        if not source_dir or not source_dir.is_dir():
            return
        
        try:
            pattern = "MyNewActivity-*.fit"
            for fit_file in source_dir.glob(pattern):
                if fit_file.is_file() and fit_file.stat().st_size > 0:
                    yield fit_file
        except Exception as e:
            logger.error(f"Erreur lors du scan de {source_dir}: {e}")

    def is_file_processed(self, file_info: FileInfo) -> bool:
        """Check if file is processed using hash for better accuracy"""
        processed_info = self.config.get("processed_files", {})
        
        # Check by hash first (more reliable)
        if file_info.file_hash:
            for key, data in processed_info.items():
                if isinstance(data, dict) and data.get('hash') == file_info.file_hash:
                    return True
        
        # Fallback to old method
        file_key = f"{file_info.name}_{file_info.size_bytes}"
        return file_key in processed_info

    def mark_file_processed(self, file_info: FileInfo) -> None:
        """Mark file as processed with enhanced metadata"""
        processed_info = self.config.get("processed_files", {})
        file_key = f"{file_info.name}_{file_info.size_bytes}"
        
        processed_info[file_key] = {
            'timestamp': datetime.now().isoformat(),
            'hash': file_info.file_hash,
            'size': file_info.size_bytes,
            'path': str(file_info.path)
        }
        
        self.config.set("processed_files", processed_info)

    def scan_files_async(self) -> List[FileInfo]:
        """Scan files with improved caching and threading"""
        with self._cache_lock:
            now = datetime.now()
            if (self._cache_time and 
                (now - self._cache_time).seconds < AppConfig.SCAN_CACHE_DURATION and
                self._cache):
                logger.debug("Utilisation du cache pour les fichiers")
                return list(self._cache.values())

        sources = self.get_available_sources()
        file_infos = []
        
        for source_name, source_dir in sources.items():
            fit_files = list(self.get_fit_files(source_dir))
            fit_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            
            for file_path in fit_files:
                try:
                    stat = file_path.stat()
                    modified_time = datetime.fromtimestamp(stat.st_mtime)
                    
                    file_info = FileInfo(
                        name=file_path.name,
                        path=file_path,
                        size=self._format_size(stat.st_size),
                        date=modified_time.strftime('%d/%m/%Y %H:%M'),
                        source=source_name,
                        processed=False,  # Will be set after creation
                        modified_time=modified_time,
                        size_bytes=stat.st_size
                    )
                    
                    # Set processed status after FileInfo creation
                    file_info.processed = self.is_file_processed(file_info)
                    file_infos.append(file_info)
                    
                except Exception as e:
                    logger.error(f"Erreur lors de l'analyse de {file_path}: {e}")

        with self._cache_lock:
            self._cache = {info.path: info for info in file_infos}
            self._cache_time = now
            
        return file_infos

    def _format_size(self, size_bytes: int) -> str:
        """Format file size with better precision"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}" if size_bytes != int(size_bytes) else f"{int(size_bytes)} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def generate_new_filename(self, fit_file: Path) -> str:
        """Generate new filename with collision avoidance"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        match = re.search(r'MyNewActivity-(\d+)\.fit', fit_file.name)
        activity_num = f"_{match.group(1)}" if match else ""
        
        base_name = f"{AppConfig.MW_PREFIX}{timestamp}{activity_num}"
        counter = 0
        
        backup_path = self.get_backup_path()
        if backup_path:
            while (backup_path / f"{base_name}{'_' + str(counter) if counter else ''}.fit").exists():
                counter += 1
            if counter:
                base_name += f"_{counter}"
        
        return f"{base_name}.fit"

    def cleanup_cache(self):
        """Clean up cached data"""
        with self._cache_lock:
            self._cache.clear()
            self._cache_time = None
        self._sources_cache = None
        self._sources_cache_time = None

class FitFileManagerPatched:
    """Version corrigée de FitFileManager avec détection OS robuste"""
    
    def __init__(self, config_manager):
        self.config = config_manager
        self._cache = {}
        self._cache_time = None
        self._cache_lock = threading.RLock()
        self._sources_cache = None
        self._sources_cache_time = None

    @lru_cache(maxsize=10)
    def _get_mywhoosh_paths(self) -> List[Path]:
        """Détection MyWhoosh multi-OS améliorée"""
        paths = []
        
        try:
            if OSDetector.is_macos():
                paths.extend(self._get_macos_mywhoosh_paths())
            elif OSDetector.is_windows():
                paths.extend(self._get_windows_mywhoosh_paths())
            elif OSDetector.is_linux():
                paths.extend(self._get_linux_mywhoosh_paths())
            else:
                logger.warning(f"OS non supporté: {platform.system()}")
                
        except Exception as e:
            logger.error(f"Erreur lors de la recherche des répertoires MyWhoosh: {e}")
        
        # Log des chemins trouvés pour debug
        if paths:
            logger.info(f"Chemins MyWhoosh détectés: {[str(p) for p in paths]}")
        else:
            logger.warning("Aucun répertoire MyWhoosh détecté")
            
        return paths

    def _get_macos_mywhoosh_paths(self) -> List[Path]:
        """Chemins MyWhoosh spécifiques macOS"""
        paths = []
        base_paths = [
            # Chemin principal (App Store/Containers)
            Path.home() / "Library" / "Containers" / "com.whoosh.whooshgame" / 
            "Data" / "Library" / "Application Support" / "Epic" / "MyWhoosh" / "Content" / "Data",
            
            # Chemins alternatifs
            Path.home() / "Library" / "Application Support" / "MyWhoosh" / "Content" / "Data",
            Path.home() / "Library" / "Application Support" / "Epic" / "MyWhoosh" / "Content" / "Data",
            
            # Installation directe (non App Store)
            Path.home() / "Applications" / "MyWhoosh.app" / "Contents" / "Resources" / "Data",
            
            # Dossiers utilisateur communs
            Path.home() / "Documents" / "MyWhoosh",
            Path.home() / "MyWhoosh",
        ]
        
        for path in base_paths:
            if path.exists() and path.is_dir():
                # Vérifier qu'il contient des fichiers FIT
                if self._contains_fit_files(path):
                    paths.append(path)
                    logger.debug(f"Chemin MyWhoosh macOS valide: {path}")
        
        return paths

    def _get_windows_mywhoosh_paths(self) -> List[Path]:
        """Chemins MyWhoosh spécifiques Windows"""
        paths = []
        
        # Packages Microsoft Store
        packages_base = Path.home() / "AppData" / "Local" / "Packages"
        if packages_base.exists():
            for directory in packages_base.iterdir():
                if directory.is_dir():
                    # Vérifier tous les préfixes possibles
                    for prefix in AppConfig.MYWHOOSH_PREFIXES_WINDOWS:
                        if directory.name.startswith(prefix):
                            potential_paths = [
                                directory / "LocalCache" / "Local" / "MyWhoosh" / "Content" / "Data",
                                directory / "LocalState" / "MyWhoosh" / "Data",
                                directory / "AC" / "INetCache" / "MyWhoosh" / "Data",
                            ]
                            
                            for path in potential_paths:
                                if path.exists() and path.is_dir() and self._contains_fit_files(path):
                                    paths.append(path)
                                    logger.debug(f"Chemin MyWhoosh Windows valide: {path}")
        
        # Installations classiques
        classic_paths = [
            Path.home() / "AppData" / "Local" / "MyWhoosh" / "Data",
            Path.home() / "AppData" / "Roaming" / "MyWhoosh" / "Data",
            Path.home() / "Documents" / "MyWhoosh",
            Path("C:") / "Program Files" / "MyWhoosh" / "Data",
            Path("C:") / "Program Files (x86)" / "MyWhoosh" / "Data",
        ]
        
        for path in classic_paths:
            if path.exists() and path.is_dir() and self._contains_fit_files(path):
                paths.append(path)
                logger.debug(f"Chemin MyWhoosh Windows classique: {path}")
        
        return paths

    def _get_linux_mywhoosh_paths(self) -> List[Path]:
        """Chemins MyWhoosh spécifiques Linux"""
        paths = []
        
        # Utiliser les chemins définis dans AppConfig
        for path in AppConfig.MYWHOOSH_PATHS_LINUX:
            if path.exists() and path.is_dir() and self._contains_fit_files(path):
                paths.append(path)
                logger.debug(f"Chemin MyWhoosh Linux valide: {path}")
        
        # Chemins supplémentaires Linux
        additional_paths = [
            Path.home() / ".config" / "MyWhoosh" / "Data",
            Path.home() / "snap" / "mywhoosh" / "common" / "Data",
            Path("/var/lib/snapd/snap/mywhoosh/common/Data"),
            Path("/usr/share/MyWhoosh/Data"),
        ]
        
        for path in additional_paths:
            if path.exists() and path.is_dir() and self._contains_fit_files(path):
                paths.append(path)
                logger.debug(f"Chemin MyWhoosh Linux supplémentaire: {path}")
        
        return paths

    def _contains_fit_files(self, directory: Path) -> bool:
        """Vérifier si un répertoire contient des fichiers FIT MyWhoosh"""
        try:
            # Rechercher des fichiers FIT avec le pattern MyWhoosh
            fit_pattern = "MyNewActivity-*.fit"
            fit_files = list(directory.glob(fit_pattern))
            
            # Aussi vérifier des patterns alternatifs
            if not fit_files:
                alternative_patterns = ["*.fit", "Activity-*.fit", "workout-*.fit"]
                for pattern in alternative_patterns:
                    fit_files = list(directory.glob(pattern))
                    if fit_files:
                        break
            
            return len(fit_files) > 0
            
        except (OSError, PermissionError) as e:
            logger.debug(f"Impossible de scanner {directory}: {e}")
            return False

    def get_available_sources(self) -> Dict[str, Path]:
        """Obtenir les sources disponibles avec nommage amélioré"""
        from datetime import datetime
        
        now = datetime.now()
        if (self._sources_cache and self._sources_cache_time and
            (now - self._sources_cache_time).seconds < 60):
            return self._sources_cache
        
        sources = {}
        paths = self._get_mywhoosh_paths()
        
        for i, path in enumerate(paths):
            # Nommage plus informatif selon l'OS
            if OSDetector.is_windows():
                if "Packages" in str(path):
                    source_name = f"MyWhoosh Store" if i == 0 else f"MyWhoosh Store {i+1}"
                else:
                    source_name = f"MyWhoosh" if i == 0 else f"MyWhoosh {i+1}"
            elif OSDetector.is_macos():
                if "Containers" in str(path):
                    source_name = f"MyWhoosh (App Store)" if i == 0 else f"MyWhoosh (App Store) {i+1}"
                else:
                    source_name = f"MyWhoosh" if i == 0 else f"MyWhoosh {i+1}"
            else:  # Linux
                source_name = f"MyWhoosh" if i == 0 else f"MyWhoosh {i+1}"
            
            sources[source_name] = path
            logger.info(f"Source détectée: {source_name} -> {path}")
        
        self._sources_cache = sources
        self._sources_cache_time = now
        return sources

    def get_mywhoosh_directory(self) -> Optional[Path]:
        """Obtenir le premier répertoire MyWhoosh disponible"""
        paths = self._get_mywhoosh_paths()
        if paths:
            logger.info(f"Répertoire MyWhoosh principal: {paths[0]}")
            return paths[0]
        else:
            logger.warning("Aucun répertoire MyWhoosh trouvé")
            return None

# Classe de style améliorée pour multi-OS
class StyleManagerPatched:
    """Gestionnaire de styles adapté à chaque OS"""
    
    def __init__(self, app):
        self.app = app
        self.style = app.style
        
    def setup_os_specific_fonts(self):
        """Configuration des polices selon l'OS"""
        if OSDetector.is_windows():
            return {
                'base_font': ("Segoe UI", 9),
                'heading_font': ("Segoe UI", 11, "bold"),
                'mono_font': ("Consolas", 9)
            }
        elif OSDetector.is_macos():
            return {
                'base_font': ("SF Pro Display", 9),
                'heading_font': ("SF Pro Display", 11, "bold"), 
                'mono_font': ("Monaco", 9)
            }
        else:  # Linux
            return {
                'base_font': ("DejaVu Sans", 9),
                'heading_font': ("DejaVu Sans", 11, "bold"),
                'mono_font': ("DejaVu Sans Mono", 9)
            }
    
    def get_os_theme(self):
        """Thème préféré selon l'OS"""
        if OSDetector.is_windows():
            preferred_themes = ['vista', 'xpnative', 'winnative', 'clam']
        elif OSDetector.is_macos():
            preferred_themes = ['aqua', 'clam', 'default']
        else:  # Linux
            preferred_themes = ['clam', 'alt', 'default']
        
        available_themes = self.style.theme_names()
        for theme in preferred_themes:
            if theme in available_themes:
                return theme
        
        return 'clam'  # Fallback

# Fonction utilitaire pour debug multi-OS
def debug_os_environment():
    """Fonction de debug pour analyser l'environnement OS"""
    info = {
        'os_detection': OSDetector.get_os_info(),
        'python_platform': platform.platform(),
        'home_directory': str(Path.home()),
        'current_directory': str(Path.cwd()),
        'environment_variables': {
            'PATH': os.environ.get('PATH', 'Non définie'),
            'HOME': os.environ.get('HOME', 'Non définie'),
            'USERPROFILE': os.environ.get('USERPROFILE', 'Non définie'),
            'APPDATA': os.environ.get('APPDATA', 'Non définie'),
        }
    }
    
    logger.info("=== DEBUG ENVIRONNEMENT OS ===")
    for key, value in info.items():
        logger.info(f"{key}: {value}")
    logger.info("=== FIN DEBUG ===")
    
    return info

# Test de détection MyWhoosh
def test_mywhoosh_detection():
    """Tester la détection MyWhoosh sur le système actuel"""
    logger.info("=== TEST DÉTECTION MYWHOOSH ===")
    
    # Debug environnement
    debug_os_environment()
    
    # Test détection
    file_manager = FitFileManagerPatched(None)
    paths = file_manager._get_mywhoosh_paths()
    
    logger.info(f"Système détecté: {OSDetector.get_system()}")
    logger.info(f"Nombre de chemins MyWhoosh trouvés: {len(paths)}")
    
    for i, path in enumerate(paths):
        logger.info(f"  {i+1}. {path}")
        if path.exists():
            try:
                files = list(path.glob("*.fit"))
                logger.info(f"     Fichiers FIT: {len(files)}")
            except Exception as e:
                logger.warning(f"     Erreur lecture: {e}")
        else:
            logger.warning(f"     Chemin inexistant!")
    
    sources = file_manager.get_available_sources()
    logger.info(f"Sources configurées: {list(sources.keys())}")
    logger.info("=== FIN TEST ===")
    
    return paths, sources

if __name__ == "__main__":
    # Test de compatibilité
    logging.basicConfig(level=logging.INFO)
    test_mywhoosh_detection()

class FitFileProcessor:
    """Enhanced FIT file processing with better error handling"""
    
    @staticmethod
    @retry_on_exception(max_retries=2)
    def cleanup_fit_file(fit_file_path: Path, new_file_path: Path) -> bool:
        """Clean up FIT file with enhanced error handling"""
        try:
            from fit_tool.fit_file import FitFile
            from fit_tool.fit_file_builder import FitFileBuilder
            from fit_tool.profile.messages.record_message import RecordMessage, RecordTemperatureField
            from fit_tool.profile.messages.session_message import SessionMessage
            from fit_tool.profile.messages.lap_message import LapMessage
            
            if not fit_file_path.exists():
                logger.error(f"Fichier source inexistant: {fit_file_path}")
                return False
            
            if not os.access(fit_file_path, os.R_OK):
                logger.error(f"Pas de permission de lecture: {fit_file_path}")
                return False
            
            # Create backup directory if needed
            new_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Verify write permissions on destination
            if not os.access(new_file_path.parent, os.W_OK):
                logger.error(f"Pas de permission d'écriture: {new_file_path.parent}")
                return False
            
            # Process file
            builder = FitFileBuilder()
            fit_file = FitFile.from_file(str(fit_file_path))
            
            cadence_values, power_values, heart_rate_values = [], [], []
            
            for record in fit_file.records:
                message = record.message
                
                if isinstance(message, LapMessage):
                    continue
                    
                if isinstance(message, RecordMessage):
                    # Remove temperature field if present
                    try:
                        message.remove_field(RecordTemperatureField.ID)
                    except (AttributeError, KeyError):
                        pass  # Field might not exist
                    
                    FitFileProcessor._append_value(cadence_values, message, "cadence")
                    FitFileProcessor._append_value(power_values, message, "power")
                    FitFileProcessor._append_value(heart_rate_values, message, "heart_rate")
                
                elif isinstance(message, SessionMessage):
                    # Update averages if missing
                    if not message.avg_cadence and cadence_values:
                        message.avg_cadence = FitFileProcessor._calculate_avg(cadence_values)
                    if not message.avg_power and power_values:
                        message.avg_power = FitFileProcessor._calculate_avg(power_values)
                    if not message.avg_heart_rate and heart_rate_values:
                        message.avg_heart_rate = FitFileProcessor._calculate_avg(heart_rate_values)
                    
                    cadence_values, power_values, heart_rate_values = [], [], []
                
                builder.add(message)
            
            # Write cleaned file
            try:
                fit_data = builder.build()
                fit_data.to_file(str(new_file_path))
                logger.info(f"Fichier nettoyé sauvegardé: {new_file_path.name}")
                return True
            except Exception as e:
                logger.error(f"Erreur lors de l'écriture du fichier nettoyé: {e}")
                # Clean up partial file
                if new_file_path.exists():
                    try:
                        new_file_path.unlink()
                    except:
                        pass
                return False
                
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage du fichier {fit_file_path.name}: {e}")
            return False

    @staticmethod
    def _calculate_avg(values: List[int]) -> int:
        """Calculate average with null check"""
        valid_values = [v for v in values if v is not None and v > 0]
        return int(sum(valid_values) / len(valid_values)) if valid_values else 0

    @staticmethod
    def _append_value(values: List[int], message: object, field_name: str) -> None:
        """Append value with better error handling"""
        try:
            value = getattr(message, field_name, None)
            values.append(value if value is not None else 0)
        except AttributeError:
            values.append(0)


class GarminAuthManager:
    """Enhanced authentication manager with session management"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self._is_connected = False
        self._lock = threading.RLock()
        self._session_check_timer = None
        self._last_activity = datetime.now()

    @property
    def is_connected(self) -> bool:
        """Thread-safe connection status"""
        with self._lock:
            return self._is_connected

    @retry_on_exception(max_retries=2)
    def try_token_auth(self) -> bool:
        """Try token authentication with retry"""
        if not AppConfig.TOKENS_PATH.exists():
            return False
        
        try:
            import garth
            garth.resume(AppConfig.TOKENS_PATH)
            
            # Verify session is valid
            username = garth.client.username
            if username:
                with self._lock:
                    self._is_connected = True
                    self._last_activity = datetime.now()
                logger.info(f"Authentification par token réussie pour {username}")
                self._start_session_monitoring()
                return True
            else:
                self._cleanup_token()
                return False
                
        except Exception as e:
            logger.debug(f"Token invalide ou expiré: {e}")
            self._cleanup_token()
            return False

    def authenticate(self, email: str, password: str) -> bool:
        """Authenticate with enhanced error handling"""
        try:
            import garth
            from garth.exc import GarthHTTPError
            
            logger.info("Tentative d'authentification sur Garmin Connect...")
            
            # Clear any existing session
            self.disconnect()
            
            # Authenticate
            garth.login(email, password)
            garth.save(AppConfig.TOKENS_PATH)
            
            with self._lock:
                self._is_connected = True
                self._last_activity = datetime.now()
            
            self.config.set("last_auth", datetime.now().isoformat())
            logger.info(f"Authentification réussie pour {email}")
            
            self._start_session_monitoring()
            return True
            
        except Exception as e:
            error_msg = str(e).lower()
            if "401" in error_msg or "unauthorized" in error_msg:
                logger.error("Erreur d'authentification: identifiants incorrects")
            elif "429" in error_msg or "rate" in error_msg:
                logger.error("Erreur d'authentification: trop de tentatives, réessayez plus tard")
            else:
                logger.error(f"Erreur d'authentification: {e}")
            
            with self._lock:
                self._is_connected = False
            return False

    def disconnect(self) -> None:
        """Enhanced disconnect with cleanup"""
        with self._lock:
            self._is_connected = False
        
        self._stop_session_monitoring()
        self._cleanup_token()
        logger.info("Déconnecté de Garmin Connect")

    def _cleanup_token(self) -> None:
        """Clean up token files"""
        try:
            if AppConfig.TOKENS_PATH.exists():
                AppConfig.TOKENS_PATH.unlink()
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du token: {e}")

    def refresh_session(self) -> bool:
        """Refresh session with validation"""
        with self._lock:
            if not self._is_connected:
                return False
                
            if self._is_session_valid():
                self._last_activity = datetime.now()
                return True
            else:
                logger.info("Session expirée, tentative de reconnexion...")
                return self.try_token_auth()

    def _is_session_valid(self) -> bool:
        """Check if current session is valid"""
        try:
            import garth
            # Try a simple API call to validate session
            garth.client.username
            return True
        except Exception:
            return False

    def _start_session_monitoring(self):
        """Start monitoring session validity"""
        self._stop_session_monitoring()
        self._session_check_timer = threading.Timer(300, self._check_session)  # Check every 5 minutes
        self._session_check_timer.daemon = True
        self._session_check_timer.start()

    def _stop_session_monitoring(self):
        """Stop session monitoring"""
        if self._session_check_timer:
            self._session_check_timer.cancel()
            self._session_check_timer = None

    def _check_session(self):
        """Periodic session validation"""
        if self._is_connected:
            if not self._is_session_valid():
                logger.warning("Session Garmin expirée")
                with self._lock:
                    self._is_connected = False
            else:
                # Schedule next check
                self._start_session_monitoring()

    def __del__(self):
        """Cleanup on destruction"""
        self._stop_session_monitoring()


class GarminUploader:
    """Enhanced uploader with concurrent processing and better progress tracking"""
    
    def __init__(self, auth_manager: GarminAuthManager, file_manager: FitFileManager):
        self.auth_manager = auth_manager
        self.file_manager = file_manager
        self.max_workers = min(AppConfig.MAX_CONCURRENT_UPLOADS, (os.cpu_count() or 1))
        self._upload_stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'duplicates': 0
        }

    def upload_files(self, files: List[Path], progress_callback=None) -> Dict[Path, bool]:
        """Upload files with concurrent processing"""
        if not files:
            return {}

        self._upload_stats = {'total': len(files), 'success': 0, 'failed': 0, 'duplicates': 0}
        results = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers, 
                               thread_name_prefix="FitUploader") as executor:
            # Submit all upload tasks
            future_to_file = {
                executor.submit(self._upload_file_with_retry, file_path): file_path
                for file_path in files
            }
            
            # Process completed uploads
            for i, future in enumerate(as_completed(future_to_file, timeout=None)):
                file_path = future_to_file[future]
                
                if progress_callback:
                    progress = (i + 1) / len(files) * 100
                    progress_callback(progress, f"Upload de {file_path.name}...")
                
                try:
                    success, is_duplicate = future.result()
                    results[file_path] = success
                    
                    if success:
                        if is_duplicate:
                            self._upload_stats['duplicates'] += 1
                            logger.info(f"Fichier déjà présent: {file_path.name}")
                        else:
                            self._upload_stats['success'] += 1
                            logger.info(f"Upload réussi: {file_path.name}")
                        
                        # Mark as processed only on successful upload
                        file_info = next((info for info in self.file_manager.scan_files_async() 
                                        if info.path == file_path), None)
                        if file_info:
                            self.file_manager.mark_file_processed(file_info)
                    else:
                        self._upload_stats['failed'] += 1
                        logger.error(f"Échec d'upload: {file_path.name}")
                        
                except Exception as e:
                    logger.error(f"Erreur lors du traitement de {file_path.name}: {e}")
                    results[file_path] = False
                    self._upload_stats['failed'] += 1
                
                # Small delay to prevent overwhelming the API
                time.sleep(0.1)
        
        self._log_upload_summary()
        return results

    def _upload_file_with_retry(self, file_path: Path, 
                                max_retries: int = AppConfig.MAX_RETRY_ATTEMPTS) -> Tuple[bool, bool]:
            """Upload file with retry logic and duplicate detection"""
            if not file_path.exists():
                logger.error(f"Fichier inexistant: {file_path}")
                return False, False
            
            # Vérifier les permissions de lecture
            if not os.access(file_path, os.R_OK):
                logger.error(f"Pas de permission de lecture: {file_path}")
                return False, False
            
            for attempt in range(max_retries):
                try:
                    if not self.auth_manager.refresh_session():
                        logger.error("Session Garmin expirée")
                        return False, False
                    
                    import garth
                    from garth.exc import GarthHTTPError
                    
                    logger.debug(f"Upload tentative {attempt + 1}/{max_retries}: {file_path.name}")
                    
                    # Sauvegarder le timeout original s'il existe
                    original_timeout = getattr(garth.client, 'timeout', None)
                    
                    with open(file_path, "rb") as f:
                        # Appliquer un timeout personnalisé si supporté
                        if hasattr(garth.client, 'timeout'):
                            garth.client.timeout = AppConfig.UPLOAD_TIMEOUT
                        
                        response = garth.client.upload(f)
                        logger.debug(f"Réponse Garmin pour {file_path.name}: {response}")
                        
                        # Restaurer le timeout original
                        if original_timeout is not None and hasattr(garth.client, 'timeout'):
                            garth.client.timeout = original_timeout
                    
                    return True, False  # Success, not duplicate
                    
                except Exception as e:
                    # Restaurer le timeout en cas d'erreur
                    if 'original_timeout' in locals() and original_timeout is not None:
                        if hasattr(garth.client, 'timeout'):
                            garth.client.timeout = original_timeout
                    
                    error_msg = str(e).lower()
                    
                    # Handle known error types
                    if "409" in error_msg or "duplicate" in error_msg:
                        logger.info(f"Fichier déjà présent sur Garmin: {file_path.name}")
                        return True, True  # Success (duplicate), is duplicate
                    
                    if "401" in error_msg or "unauthorized" in error_msg:
                        logger.error("Session expirée pendant l'upload")
                        self.auth_manager._is_connected = False
                        return False, False
                    
                    if "429" in error_msg or "rate limit" in error_msg:
                        wait_time = min(2 ** attempt * 2, 60)  # Cap à 60 secondes max
                        logger.warning(f"Rate limit atteint, attente {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    
                    # Erreurs de réseau/timeout
                    if any(keyword in error_msg for keyword in ['timeout', 'connection', 'network']):
                        if attempt < max_retries - 1:
                            wait_time = min(2 ** attempt, 30)  # Backoff exponentiel limité
                            logger.warning(f"Erreur réseau, nouvelle tentative dans {wait_time}s: {e}")
                            time.sleep(wait_time)
                            continue
                    
                    logger.warning(f"Tentative {attempt + 1} échouée pour {file_path.name}: {e}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        logger.error(f"Échec définitif après {max_retries} tentatives: {file_path.name}")
            
            return False, False

    def _log_upload_summary(self):
        """Log upload session summary"""
        stats = self._upload_stats
        logger.info(f"Résumé d'upload - Total: {stats['total']}, "
                   f"Réussis: {stats['success']}, Doublons: {stats['duplicates']}, "
                   f"Échecs: {stats['failed']}")

    def get_upload_stats(self) -> dict:
        """Get current upload statistics"""
        return self._upload_stats.copy()


class TextHandler(logging.Handler):
    """Enhanced text handler with better performance"""
    
    def __init__(self, widget: tk.Text, max_lines: int = 1000):
        super().__init__()
        self.widget = weakref.ref(widget)
        self.max_lines = max_lines
        # Nouveau formatter avec timestamp simplifié
        self.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
        self._update_queue = queue.Queue(maxsize=100)
        self._processing = False

    def emit(self, record):
        """Queue log records for batch processing"""
        widget = self.widget()
        if not widget:
            return
        
        msg = self.format(record)
        
        # Formatage du message selon le niveau
        if record.levelno >= logging.ERROR:
            formatted_msg = f"[{datetime.now().strftime('%H:%M:%S')}] - ERROR - {record.getMessage()}"
            tag = "error"
        elif record.levelno >= logging.WARNING:
            formatted_msg = f"[{datetime.now().strftime('%H:%M:%S')}]- WARNING - {record.getMessage()}"
            tag = "warning"
        elif record.levelno >= logging.INFO:
            # Pour les messages INFO, on garde le format simple ou avec préfixe selon le contenu
            msg_text = record.getMessage()
            if any(keyword in msg_text.lower() for keyword in ['démarré', 'succès', 'terminé', 'connecté']):
                formatted_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {msg_text}"
            else:
                formatted_msg = f"[{datetime.now().strftime('%H:%M:%S')}] - INFO - {msg_text}"
            tag = "info"
        else:
            formatted_msg = f"[{datetime.now().strftime('%H:%M:%S')}] - DEBUG - {record.getMessage()}"
            tag = "debug"
        
        try:
            self._update_queue.put_nowait((formatted_msg, tag))
            if not self._processing:
                self._processing = True
                widget.after_idle(self._process_queued_updates)
        except queue.Full:
            pass

    def _get_tag_for_level(self, levelno: int) -> str:
        """Get tag name for log level"""
        if levelno >= logging.ERROR:
            return "error"
        elif levelno >= logging.WARNING:
            return "warning"
        elif levelno >= logging.INFO:
            return "info"
        else:
            return "debug"

    def _process_queued_updates(self):
        """Process queued log updates in batches"""
        widget = self.widget()
        if not widget:
            self._processing = False
            return
        
        try:
            if not widget.winfo_exists():
                self._processing = False
                return
            
            widget.configure(state='normal')
            
            # Process up to 10 messages at once
            messages_processed = 0
            while messages_processed < 10 and not self._update_queue.empty():
                try:
                    msg, tag = self._update_queue.get_nowait()
                    widget.insert(tk.END, msg + "\n", tag)
                    messages_processed += 1
                except queue.Empty:
                    break
            
            # Trim lines if necessary
            lines = widget.get("1.0", tk.END).split('\n')
            if len(lines) > self.max_lines:
                lines_to_delete = len(lines) - int(self.max_lines * 0.8)
                widget.delete("1.0", f"{lines_to_delete}.0")
            
            widget.configure(state='disabled')
            widget.yview(tk.END)
            
            # Schedule next processing if more messages are queued
            if not self._update_queue.empty():
                widget.after_idle(self._process_queued_updates)
            else:
                self._processing = False
                
        except tk.TclError:
            self._processing = False


def create_tooltip(widget, text):
    """Enhanced tooltip with better positioning"""
    tooltip = None
    
    def show_tooltip(event):
        nonlocal tooltip
        if tooltip:
            return
        
        # Better positioning calculation
        x = widget.winfo_rootx() + 20
        y = widget.winfo_rooty() + widget.winfo_height() + 5
        
        # Ensure tooltip stays on screen
        screen_width = widget.winfo_screenwidth()
        screen_height = widget.winfo_screenheight()
        
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
        
        # Create label first to measure size
        label = tk.Label(
            tooltip, 
            text=text, 
            background='#2d3748',
            foreground='white',
            relief="solid", 
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=8, 
            pady=4,
            wraplength=300
        )
        label.pack()
        
        # Update to get actual size
        tooltip.update_idletasks()
        tooltip_width = tooltip.winfo_reqwidth()
        tooltip_height = tooltip.winfo_reqheight()
        
        # Adjust position if tooltip would go off screen
        if x + tooltip_width > screen_width:
            x = screen_width - tooltip_width - 10
        if y + tooltip_height > screen_height:
            y = widget.winfo_rooty() - tooltip_height - 5
        
        tooltip.wm_geometry(f"+{x}+{y}")
        
        # Auto-hide after 8 seconds
        widget.after(8000, hide_tooltip)

    def hide_tooltip(event=None):
        nonlocal tooltip
        if tooltip:
            try:
                tooltip.destroy()
            except:
                pass
            tooltip = None
            
    widget.bind("<Enter>", show_tooltip)
    widget.bind("<Leave>", hide_tooltip)


class FitUploaderApp(tk.Tk, TranslatableTkApp): 
    """Enhanced main application with improved UI and performance"""
    
    def __init__(self):
        super().__init__()
        logger.info("🚀 Démarrage de FitUploaderApp...")
        TranslatableTkApp.__init__(self)
        logger.info("🌍 TranslatableTkApp initialisé")

        # Initialize managers
        self.config_manager = ConfigManager()
        logger.info("⚙️ ConfigManager initialisé")
        self.file_manager = FitFileManager(self.config_manager)
        self.auth_manager = GarminAuthManager(self.config_manager)
        self.uploader = GarminUploader(self.auth_manager, self.file_manager)
        
        # State variables
        self.is_processing = False
        self.selected_files: Set[str] = set()
        self.file_infos: List[FileInfo] = []
        self.ui_queue = queue.Queue()
        self._auto_scan_timer = None
        self._status_update_timer = None
        saved_language = self.config_manager.get('language', 'en')
        logger.info(f"💾 Langue sauvegardée: {saved_language}")
        self.translator.set_language(saved_language)
        logger.info(f"🌐 Langue définie sur: {self.translator.current_language}")
        # UI setup
        self.setup_window()
        self.setup_style()
        self.create_widgets()
        self.setup_logging()
        self.update_translations()
        self.load_saved_settings()
        
        # Start background tasks
        self.auto_authenticate()
        self.after(AppConfig.UI_UPDATE_INTERVAL, self.periodic_check_queue)
        self._schedule_auto_scan()

    def on_language_change(self, event):
        """Gérer le changement de langue via le menu déroulant"""
        try:
            selected_lang_name = self.language_var.get()
            
            # Trouver le code de langue correspondant au nom sélectionné
            available_languages = self.translator.get_available_languages()
            selected_lang_code = None
            
            for code, name in available_languages.items():
                if name == selected_lang_name:
                    selected_lang_code = code
                    break
            
            if selected_lang_code and selected_lang_code != self.translator.current_language:
                # Changer la langue
                self.translator.set_language(selected_lang_code)
                self.config_manager.set('language', selected_lang_code)
                
                # Mettre à jour le titre de la fenêtre
                self.title(self.t("app_title"))
                
                # Mettre à jour tous les widgets traduisibles
                self.update_translations()
                
                # Mettre à jour les éléments qui ne sont pas dans le système de widgets traduisibles
                self.refresh_ui_after_language_change()
                
                logger.info(f"🌐 Langue changée vers: {selected_lang_name} ({selected_lang_code})")
                
        except Exception as e:
            logger.error(f"Erreur lors du changement de langue: {e}")

    def refresh_ui_after_language_change(self):
        """Rafraîchir les éléments d'interface après un changement de langue"""
        try:
            # Mettre à jour les éléments spécifiques qui ne sont pas automatiquement traduits
            
            # Mettre à jour le texte des colonnes du treeview
            if hasattr(self, 'files_tree'):
                self.files_tree.heading('name', text=self.t('file_name'))
                self.files_tree.heading('date', text=self.t('date'))
                self.files_tree.heading('size', text=self.t('size'))
                self.files_tree.heading('source', text=self.t('source'))
                self.files_tree.heading('status', text=self.t('status'))
            
            # Mettre à jour les compteurs avec la nouvelle langue
            file_count = len(self.file_infos) if hasattr(self, 'file_infos') else 0
            if hasattr(self, 'files_count_label'):
                self.files_count_label.configure(text=f"{file_count} {self.t('files_count')}")
            
            # Mettre à jour les informations de sélection
            if hasattr(self, 'files_tree') and hasattr(self, 'selection_info_label'):
                selection_count = len(self.files_tree.selection())
                self.selection_info_label.configure(text=f"{selection_count} {self.t('files_selected')}")
            
            # Mettre à jour les statuts dans le treeview
            if hasattr(self, 'files_tree'):
                for item in self.files_tree.get_children():
                    values = list(self.files_tree.item(item, "values"))
                    if len(values) >= 5:
                        # Traduire le statut
                        current_status = values[4]
                        if "Traité" in current_status or "Processed" in current_status:
                            values[4] = self.t("processed")
                        elif "Nouveau" in current_status or "New" in current_status:
                            values[4] = self.t("new")
                        self.files_tree.item(item, values=values)
            
            # Mettre à jour la barre de statut
            if hasattr(self, 'status_var'):
                self.status_var.set(self.t("ready"))
            
            # Mettre à jour le label de progression
            if hasattr(self, 'progress_label'):
                self.progress_label.configure(text=self.t("ready"))
            
            # Mettre à jour les stats d'upload
            if hasattr(self, 'upload_stats_label'):
                stats = self.uploader.get_upload_stats() if hasattr(self, 'uploader') else {'success': 0, 'failed': 0, 'duplicates': 0}
                self.upload_stats_label.configure(
                    text=f"{self.t('upload_success')}: {stats['success']} | {self.t('upload_failed')}: {stats['failed']} | {self.t('upload_duplicates')}: {stats['duplicates']}"
                )
            
            # Mettre à jour les sources (texte dynamique)
            if hasattr(self, 'sources_label'):
                self.refresh_sources()
            
            # Forcer la mise à jour du statut d'authentification
            self.update_auth_status()
            
            logger.info(f"🌍 Interface mise à jour pour la langue: {self.translator.current_language}")
            
        except Exception as e:
            logger.error(f"Erreur lors du rafraîchissement de l'UI: {e}")

    def setup_window(self):
        """Enhanced window setup"""
        self.title(self.t("app_title"))
        self.geometry("1400x900")
        self.minsize(1200, 700)
        self.configure(bg=Colors.BACKGROUND)
        
        # Set application icon
        self.setup_icon()
        
        # Commenter ou supprimer cette ligne pour éviter le centrage forcé
        # self.center_window()
        
        # Ajouter cette ligne pour maximiser la fenêtre (cross-platform)
        self.wm_state('zoomed')  # Pour Windows/Linux ; sur macOS, cela peut nécessiter self.attributes('-fullscreen', True) si besoin de vrai plein écran
        
        # Handle window close event
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_icon(self):
        """Setup application icon with fallback"""
        try:
            if os.name == "nt":
                icon_path = AppConfig.SCRIPT_DIR / "FitUploader.ico"
                if icon_path.exists():
                    self.iconbitmap(str(icon_path))
            else:
                icon_path = AppConfig.SCRIPT_DIR / "FitUploader.png"
                if icon_path.exists():
                    icon_img = tk.PhotoImage(file=str(icon_path))
                    self.iconphoto(True, icon_img)
        except Exception as e:
            logger.debug(f"Impossible de charger l'icône: {e}")

    def center_window(self):
        """Center window on screen"""
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        pos_x = (self.winfo_screenwidth() // 2) - (width // 2)
        pos_y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{pos_x}+{pos_y}")

    def setup_style(self):
        """Enhanced style configuration with OS detection"""
        self.style = ttk.Style(self)
        
        # OS-specific theme selection
        if OSDetector.is_windows():
            preferred_themes = ['vista', 'xpnative', 'winnative', 'clam']
        elif OSDetector.is_macos():
            preferred_themes = ['aqua', 'clam', 'default']
        else:  # Linux
            preferred_themes = ['clam', 'alt', 'default']
        
        available_themes = self.style.theme_names()
        for theme in preferred_themes:
            if theme in available_themes:
                self.style.theme_use(theme)
                break
        
        # OS-specific fonts
        if OSDetector.is_windows():
            base_font = ("Segoe UI", 9)
            heading_font = ("Segoe UI", 11, "bold")
            mono_font = ("Consolas", 9)
        elif OSDetector.is_macos():
            base_font = ("SF Pro Display", 9)
            heading_font = ("SF Pro Display", 11, "bold")
            mono_font = ("Monaco", 9)
        else:  # Linux
            base_font = ("DejaVu Sans", 9)
            heading_font = ("DejaVu Sans", 11, "bold")
            mono_font = ("DejaVu Sans Mono", 9)
        
        # Try to use a modern theme
        try:
            available_themes = self.style.theme_names()
            preferred_themes = ['vista', 'xpnative', 'winnative', 'clam']
            for theme in preferred_themes:
                if theme in available_themes:
                    self.style.theme_use(theme)
                    break
        except:
            self.style.theme_use("clam")
        
        # Font configuration
        if os.name == "nt":
            base_font = ("Segoe UI", 9)
            heading_font = ("Segoe UI", 11, "bold")
            mono_font = ("Consolas", 9)
        else:
            base_font = ("SF Pro Display", 9) if os.name == "posix" else ("DejaVu Sans", 9)
            heading_font = ("SF Pro Display", 11, "bold") if os.name == "posix" else ("DejaVu Sans", 11, "bold")
            mono_font = ("Monaco", 9) if os.name == "posix" else ("DejaVu Sans Mono", 9)
        
        # Style definitions (removed background for labels to make them transparent)
        styles = {
            "Title.TLabel": {
                "font": heading_font, 
                "foreground": Colors.TEXT
            },
            "Subtitle.TLabel": {
                "font": base_font, 
                "foreground": Colors.TEXT_SECONDARY
            },
            "Success.TLabel": {
                "font": base_font, 
                "foreground": Colors.SUCCESS
            },
            "Error.TLabel": {
                "font": base_font, 
                "foreground": Colors.ERROR
            },
            "Warning.TLabel": {
                "font": base_font, 
                "foreground": Colors.WARNING
            },
            "Info.TLabel": {
                "font": base_font, 
                "foreground": Colors.INFO
            },
            "Primary.TButton": {
                "font": base_font,
                "padding": (12, 8)
            },
            "Success.TButton": {
                "font": base_font,
                "padding": (12, 8)
            },
            "Danger.TButton": {
                "font": base_font,
                "padding": (12, 8)
            },
            "TEntry": {
                "fieldbackground": Colors.BACKGROUND
            }
        }
        
        for style_name, config in styles.items():
            self.style.configure(style_name, **config)
        
        # Button hover effects
        button_styles = {
            "Primary.TButton": (Colors.PRIMARY, "#1d4ed8", "#9ca3af"),
            "Success.TButton": (Colors.SUCCESS, "#059669", "#9ca3af"),
            "Danger.TButton": (Colors.ERROR, "#dc2626", "#9ca3af")
        }
        
        for style_name, (normal, active, disabled) in button_styles.items():
            self.style.map(style_name,
                          background=[("active", active), ("pressed", normal), ("disabled", disabled)],
                          foreground=[("disabled", "#6b7280")])

    def create_widgets(self):
        """Create main UI widgets with improved layout"""
        # Main container
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill="both", expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Authentication section (full width)
        self.create_auth_section(main_frame)
        
        # Content area
        content_frame = ttk.Frame(main_frame)
        content_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(20, 0))
        content_frame.columnconfigure(0, weight=2)
        content_frame.columnconfigure(1, weight=3)
        content_frame.rowconfigure(0, weight=1)
        
        # Left panel (configuration and files)
        self.create_left_panel(content_frame)
        
        # Right panel (upload and logs)
        self.create_right_panel(content_frame)
        
        # Status bar
        self.create_status_bar(main_frame)
        
        # Initial UI state update
        self.update_ui_state()

    def create_auth_section(self, parent):
        """Create authentication section with language selector"""
        auth_frame = ttk.LabelFrame(
            parent, 
            text=self.t("auth_section"), 
            padding=10
        )
        auth_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        auth_frame.columnconfigure(1, weight=1)
        auth_frame.columnconfigure(3, weight=1)
        
        # === AJOUT DU MENU LANGUE EN HAUT À DROITE ===
        # Frame pour le titre et le sélecteur de langue
        header_frame = ttk.Frame(auth_frame)
        header_frame.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 10))
        header_frame.columnconfigure(0, weight=1)  # Pour pousser le menu à droite
        
        # Sélecteur de langue à droite
        lang_frame = ttk.Frame(header_frame)
        lang_frame.grid(row=0, column=1, sticky="e")
        
        ttk.Label(lang_frame, text="🌐", font=("Segoe UI", 12)).pack(side="left", padx=(0, 5))
        
        self.language_var = tk.StringVar()
        self.language_combo = ttk.Combobox(
            lang_frame,
            textvariable=self.language_var,
            values=list(self.translator.get_available_languages().values()),
            state="readonly",
            width=12,
            font=("Segoe UI", 9)
        )
        self.language_combo.pack(side="left")
        self.language_combo.bind('<<ComboboxSelected>>', self.on_language_change)
        
        # Définir la langue actuelle dans le combo
        current_lang_name = self.translator.get_available_languages().get(
            self.translator.current_language, 'Français'
        )
        self.language_var.set(current_lang_name)
        
        create_tooltip(self.language_combo, "Changer la langue de l'interface")
        
        # === FIN AJOUT MENU LANGUE ===
        
        # Email field (ligne décalée vers le bas)
        email_label = ttk.Label(auth_frame, style="Title.TLabel")
        self.register_translatable_widget(email_label, "email", "text")
        email_label.grid(row=1, column=0, sticky="e", padx=(0, 5), pady=5)
        
        self.email_var = tk.StringVar()
        self.email_entry = ttk.Entry(auth_frame, textvariable=self.email_var, width=30)
        self.email_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=5)
        
        # Remember email checkbox on the same line as email
        self.remember_email_var = tk.BooleanVar(value=True)
        remember_check = ttk.Checkbutton(auth_frame, variable=self.remember_email_var)
        self.register_translatable_widget(remember_check, "remember_email", "text")
        remember_check.grid(row=1, column=2, sticky="w", pady=5, padx=(0, 10))
        
        # Password field (shifted right)
        password_label = ttk.Label(auth_frame, style="Title.TLabel")
        self.register_translatable_widget(password_label, "password", "text")
        password_label.grid(row=1, column=3, sticky="e", padx=(0, 5), pady=5)
        
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(auth_frame, textvariable=self.password_var, 
                                    show="*", width=30)
        self.password_entry.grid(row=1, column=4, sticky="ew", pady=5)
        
        # Controls row (reduced pady)
        controls_frame = ttk.Frame(auth_frame)
        controls_frame.grid(row=2, column=0, columnspan=5, pady=(5, 0))
        
        # Status label (center)
        self.auth_status_label = ttk.Label(
            controls_frame, 
            style="Error.TLabel"
        )
        self.register_translatable_widget(self.auth_status_label, "not_connected", "text")
        self.auth_status_label.pack(expand=True)
        
        # Login button
        self.login_button = ttk.Button(
            controls_frame, 
            command=self.handle_login,
            style="Primary.TButton"
        )
        self.register_translatable_widget(self.login_button, "login", "text")
        self.login_button.pack(side="right")
        
        # Bind Enter key to login
        self.email_entry.bind('<Return>', lambda e: self.handle_login())
        self.password_entry.bind('<Return>', lambda e: self.handle_login())

    def create_left_panel(self, parent):
        """Create left panel with configuration and files"""
        left_frame = ttk.Frame(parent)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        left_frame.rowconfigure(1, weight=1)
        
        # Configuration section
        self.create_config_section(left_frame)
        
        # Files section
        self.create_files_section(left_frame)

    def create_config_section(self, parent):
        """Create configuration section"""
        config_frame = ttk.LabelFrame(
            parent, 
            padding=15
        )
        # Enregistrer le LabelFrame pour traduction
        self.register_translatable_widget(config_frame, "config_section", "text")
        config_frame.pack(fill="x", pady=(0, 15))
        config_frame.columnconfigure(1, weight=1)
        
        # Backup path
        backup_label = ttk.Label(config_frame, style="Title.TLabel")
        self.register_translatable_widget(backup_label, "backup_path", "text")
        backup_label.grid(row=0, column=0, sticky="nw", padx=(0, 10), pady=(5, 10))
        
        backup_frame = ttk.Frame(config_frame)
        backup_frame.grid(row=0, column=1, sticky="ew", pady=(5, 10))
        backup_frame.columnconfigure(0, weight=1)
        
        self.backup_path_var = tk.StringVar()
        backup_entry = ttk.Entry(backup_frame, textvariable=self.backup_path_var)
        backup_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        browse_button = ttk.Button(
            backup_frame, 
            text="📁", 
            command=self.browse_backup_folder, 
            width=4
        )
        browse_button.grid(row=0, column=1)
        create_tooltip(browse_button, self.t("tooltip_browse"))
        
        # Sources info
        sources_label = ttk.Label(config_frame, style="Title.TLabel")
        self.register_translatable_widget(sources_label, "sources", "text")
        sources_label.grid(row=1, column=0, sticky="nw", padx=(0, 10), pady=(5, 0))
        
        sources_frame = ttk.Frame(config_frame)
        sources_frame.grid(row=1, column=1, sticky="ew", pady=(5, 0))
        sources_frame.columnconfigure(0, weight=1)
        
        self.sources_label = ttk.Label(
            sources_frame, 
            style="Subtitle.TLabel",
            anchor="w"
        )
        # Pas de traduction directe ici car le texte est dynamique
        self.sources_label.grid(row=0, column=0, sticky="ew")
        
        refresh_sources_button = ttk.Button(
            sources_frame, 
            text="🔄", 
            command=self.refresh_sources,
            width=4
        )
        refresh_sources_button.grid(row=0, column=1, sticky="e")
        create_tooltip(refresh_sources_button, self.t("tooltip_refresh"))

    def create_files_section(self, parent):
        """Create files section with enhanced treeview"""
        files_frame = ttk.LabelFrame(
            parent, 
            padding=15
        )
        # Enregistrer pour traduction
        self.register_translatable_widget(files_frame, "files_section", "text")
        files_frame.pack(fill="both", expand=True)
        files_frame.rowconfigure(1, weight=1)
        
        # Header with controls
        header_frame = ttk.Frame(files_frame)
        header_frame.pack(fill="x", pady=(0, 10))
        header_frame.columnconfigure(1, weight=1)
        
        # File count (sera mis à jour dynamiquement)
        self.files_count_label = ttk.Label(
            header_frame, 
            style="Title.TLabel"
        )
        self.files_count_label.pack(side="left")
        
        # Control buttons
        controls_frame = ttk.Frame(header_frame)
        controls_frame.pack(side="right")
        
        # Scan button
        scan_button = ttk.Button(
            controls_frame, 
            text="🔍", 
            command=self.scan_files_async,
            width=4
        )
        scan_button.pack(side="left", padx=(0, 5))
        create_tooltip(scan_button, self.t("tooltip_scan"))
        
        # Auto-scan toggle
        self.auto_scan_var = tk.BooleanVar(value=True)
        auto_scan_check = ttk.Checkbutton(
            controls_frame, 
            text="Auto", 
            variable=self.auto_scan_var,
            command=self._toggle_auto_scan
        )
        auto_scan_check.pack(side="left", padx=5)
        create_tooltip(auto_scan_check, self.t("tooltip_auto_scan"))
        
        # Scan status indicator
        self.scan_status_label = ttk.Label(
            controls_frame, 
            text="", 
            style="Subtitle.TLabel",
            width=15
        )
        self.scan_status_label.pack(side="left", padx=(10, 0))
        
        # Files treeview
        self.create_files_treeview(files_frame)
        
        # Selection controls
        self.create_selection_controls(files_frame)

    def create_files_treeview(self, parent):
        """Create enhanced files treeview with reduced height"""
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Treeview with columns (reduced height)
        columns = ('name', 'date', 'size', 'source', 'status')
        self.files_tree = ttk.Treeview(
            tree_frame, 
            columns=columns, 
            show='tree headings', 
            height=8  # Reduced from 10 to 8
        )
        
        # Configure columns
        self.files_tree.heading('name', text=self.t('file_name'), anchor='w')
        self.files_tree.heading('date', text=self.t('date'), anchor='w')
        self.files_tree.heading('size', text=self.t('size'), anchor='e')
        self.files_tree.heading('source', text=self.t('source'), anchor='w')
        self.files_tree.heading('status', text=self.t('status'), anchor='w')
        
        # Column widths
        self.files_tree.column('#0', width=30, minwidth=30, stretch=False)
        self.files_tree.column('name', width=250, minwidth=150)
        self.files_tree.column('date', width=120, minwidth=100)
        self.files_tree.column('size', width=80, minwidth=60)
        self.files_tree.column('source', width=90, minwidth=70)
        self.files_tree.column('status', width=100, minwidth=80)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.files_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.files_tree.xview)
        self.files_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Pack treeview and scrollbars
        self.files_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        
        # Bind events
        self.files_tree.bind('<Button-1>', self.on_tree_click)
        self.files_tree.bind('<Double-1>', self.on_tree_double_click)
        self.files_tree.bind('<Button-3>', self.on_tree_right_click)  # Right-click menu

    def create_selection_controls(self, parent):
        """Create selection controls"""
        selection_frame = ttk.Frame(parent)
        selection_frame.pack(fill="x", pady=(5, 0))
        
        # Selection buttons avec traduction
        select_all_btn = ttk.Button(
            selection_frame, 
            command=self.select_all_files,
            width=15
        )
        self.register_translatable_widget(select_all_btn, "select_all", "text")
        select_all_btn.pack(side="left", padx=(0, 5))
        
        deselect_all_btn = ttk.Button(
            selection_frame, 
            command=self.deselect_all_files,
            width=15
        )
        self.register_translatable_widget(deselect_all_btn, "deselect_all", "text")
        deselect_all_btn.pack(side="left", padx=(0, 10))
        
        # Selection options
        self.auto_select_new_var = tk.BooleanVar(value=True)
        auto_select_check = ttk.Checkbutton(
            selection_frame, 
            variable=self.auto_select_new_var
        )
        self.register_translatable_widget(auto_select_check, "auto_select_new", "text")
        auto_select_check.pack(side="right")
        
        # Selection info (sera mis à jour dynamiquement)
        self.selection_info_label = ttk.Label(
            selection_frame, 
            style="Subtitle.TLabel"
        )
        self.selection_info_label.pack(side="left", padx=(10, 0))

    def create_right_panel(self, parent):
        """Create right panel with upload and logs"""
        right_frame = ttk.Frame(parent)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.rowconfigure(1, weight=1)
        
        # Upload section
        self.create_upload_section(right_frame)
        
        # Logs section
        self.create_logs_section(right_frame)

    def create_upload_section(self, parent):
        """Create upload section with progress tracking"""
        upload_frame = ttk.LabelFrame(
            parent, 
            padding=15
        )
        # Enregistrer pour traduction
        self.register_translatable_widget(upload_frame, "upload_section", "text")
        upload_frame.pack(fill="x", pady=(0, 15))
        
        # Main action buttons
        actions_frame = ttk.Frame(upload_frame)
        actions_frame.pack(fill="x", pady=(0, 15))
        
        # Boutons avec traduction
        self.upload_button = ttk.Button(
            actions_frame, 
            command=self.start_upload,
        )
        self.register_translatable_widget(self.upload_button, "start_upload", "text")
        self.upload_button.pack(side="left", padx=(0, 10))
        
        self.cleanup_button = ttk.Button(
            actions_frame, 
            command=self.cleanup_processed_files
        )
        self.register_translatable_widget(self.cleanup_button, "cleanup_list", "text")
        self.cleanup_button.pack(side="left", padx=(0, 10))
        
        self.stop_button = ttk.Button(
            actions_frame, 
            command=self.stop_upload,
        )
        self.register_translatable_widget(self.stop_button, "stop_upload", "text")
        self.stop_button.pack(side="right")
        
        # Progress section
        progress_frame = ttk.Frame(upload_frame)
        progress_frame.pack(fill="x", pady=(0, 10))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            progress_frame, 
            variable=self.progress_var, 
            maximum=100,
            length=400
        )
        self.progress_bar.pack(fill="x", pady=(0, 5))
        
        self.progress_label = ttk.Label(
            progress_frame, 
            style="Subtitle.TLabel"
        )
        # Le texte sera mis à jour dynamiquement
        self.progress_label.pack(fill="x")

        # Upload stats (sera mis à jour dynamiquement)
        self.upload_stats_label = ttk.Label(
            upload_frame, 
            style="Info.TLabel"
        )
        self.upload_stats_label.pack(fill="x", pady=(5, 0))

    def create_logs_section(self, parent):
        """Create logs section with enhanced text widget"""
        logs_frame = ttk.LabelFrame(
            parent, 
            padding=15
        )
        # Enregistrer pour traduction
        self.register_translatable_widget(logs_frame, "logs_section", "text")
        logs_frame.pack(fill="both", expand=True)
        logs_frame.rowconfigure(0, weight=1)
        
        # Logs text widget
        self.logs_text = tk.Text(
            logs_frame, 
            height=15, 
            wrap="word", 
            state="disabled",
            font=("Consolas", 9) if os.name == "nt" else ("Monaco", 9),
            bg="#f3f4f6",
            fg=Colors.TEXT,
            borderwidth=0
        )
        self.logs_text.pack(fill="both", expand=True, pady=(0, 10))
        
        # Configure tags for colored logging
        self.logs_text.tag_configure("info", foreground=Colors.INFO)
        self.logs_text.tag_configure("success", foreground=Colors.SUCCESS)
        self.logs_text.tag_configure("warning", foreground=Colors.WARNING)
        self.logs_text.tag_configure("error", foreground=Colors.ERROR)
        self.logs_text.tag_configure("debug", foreground=Colors.TEXT_SECONDARY)
        
        # Scrollbar
        logs_scrollbar = ttk.Scrollbar(logs_frame, orient="vertical", command=self.logs_text.yview)
        self.logs_text.configure(yscrollcommand=logs_scrollbar.set)
        logs_scrollbar.pack(side="right", fill="y")
        
        # Controls
        logs_controls = ttk.Frame(logs_frame)
        logs_controls.pack(fill="x")
        
        clear_logs_button = ttk.Button(
            logs_controls, 
            command=self.clear_logs
        )
        self.register_translatable_widget(clear_logs_button, "clear_logs", "text")
        clear_logs_button.pack(side="left")

    def create_status_bar(self, parent):
        """Create status bar for global messages"""
        status_frame = ttk.Frame(parent, padding=(10, 5), relief="sunken")
        status_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(20, 0))
        
        self.status_var = tk.StringVar(value=self.t("ready"))
        status_label = ttk.Label(
            status_frame, 
            textvariable=self.status_var, 
            style="Subtitle.TLabel",
            anchor="center"
        )
        status_label.pack(fill="x")

    def create_language_menu(self):
        """Create language selection menu"""
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        
        language_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Language", menu=language_menu)
        
        for code, name in self.translator.get_available_languages().items():
            language_menu.add_command(
                label=name, 
                command=lambda c=code: self.change_language(c)
            )

    def change_language(self, lang_code):
        """Change application language"""
        self.translator.set_language(lang_code)
        self.config_manager.set('language', lang_code)
        
        # Update window title
        self.title(self.t("app_title"))
        
        # Refresh UI elements
        self.refresh_translations()

    def refresh_translations(self):
        """Refresh all translatable UI elements"""
        # This would need to be called after language change
        # You could either restart or update all widgets individually
        messagebox.showinfo("Info", "Redémarrez l'application pour appliquer la nouvelle langue.")

    def setup_logging(self):
        """Configure logging to UI and console"""
        logger.handlers.clear()
        
        # File handler
        file_handler = logging.handlers.RotatingFileHandler(
            AppConfig.LOG_FILE, 
            maxBytes=AppConfig.MAX_LOG_SIZE,
            backupCount=AppConfig.LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(threadName)s] - %(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(file_formatter)
        logger.addHandler(console_handler)

        # UI handler - CORRECTION ICI : self.logs_text au lieu de self.log_text
        ui_handler = TextHandler(self.logs_text)
        logger.addHandler(ui_handler)
        
        # Définir le niveau de log à INFO par défaut
        logger.setLevel(logging.INFO)
        
        # Messages de démarrage
        logger.info("FitUploader démarré avec succès")
        
        # Check packages in a thread to not block UI
        threading.Thread(target=self._check_packages_and_log, daemon=True).start()

    def clear_logs(self):
        """Clear logs text widget"""
        self.logs_text.configure(state='normal')
        self.logs_text.delete("1.0", tk.END)
        self.logs_text.configure(state='disabled')

    def load_saved_settings(self):
        """Load saved settings with validation"""
        try:
            email = self.config_manager.get('email', '')
            if email:
                self.email_var.set(email)
                logger.info(f"Email sauvegardé chargé: {email}")
            
            backup_path = self.config_manager.get('backup_path', '')
            if backup_path:
                self.backup_path_var.set(backup_path)
                logger.info(f"Chemin de sauvegarde chargé: {backup_path}")
            
            self.auto_select_new_var.set(self.config_manager.get('auto_select_new', True))
            
            self.refresh_sources()
            self.scan_files_async()
        except Exception as e:
            logger.error(f"Erreur lors du chargement des settings: {e}")

    def _check_packages_and_log(self):
        """Check packages and log startup info"""
        try:
            # Vérifier les packages
            if PackageManager.ensure_packages():
                logger.info("Toutes les dépendances sont disponibles")
            else:
                logger.error("Certaines dépendances sont manquantes")
            
            # Vérifier la session sauvegardée
            if AppConfig.TOKENS_PATH.exists():
                logger.info("Session sauvegardée trouvée")
            else:
                logger.info("Aucune session sauvegardée trouvée")
                
            logger.info("Paramètres sauvegardés chargés")
            logger.info("Démarrage de FitUploader")
            
        except Exception as e:
            logger.error(f"Erreur lors de la vérification: {e}")

    def auto_authenticate(self):
        """Attempt automatic authentication"""
        try:
            if self.auth_manager.try_token_auth():
                self.update_auth_status()
        except Exception as e:
            logger.debug(f"Auto-auth failed: {e}")

    def periodic_check_queue(self):
        """Process UI update queue"""
        try:
            while not self.ui_queue.empty():
                task = self.ui_queue.get_nowait()
                task()
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"UI queue error: {e}")
        finally:
            self.after(AppConfig.UI_UPDATE_INTERVAL, self.periodic_check_queue)

    def _schedule_auto_scan(self):
        """Schedule automatic file scan"""
        if self._auto_scan_timer:
            self._auto_scan_timer.cancel()
        
        if self.auto_scan_var.get():
            self._auto_scan_timer = threading.Timer(120, self._auto_scan_wrapper)
            self._auto_scan_timer.daemon = True
            self._auto_scan_timer.start()

    def _auto_scan_wrapper(self):
        """Wrapper for auto scan with UI update"""
        self.ui_queue.put(self.scan_files_async)
        self._schedule_auto_scan()

    def _toggle_auto_scan(self):
        """Toggle auto scan feature"""
        if self.auto_scan_var.get():
            self._schedule_auto_scan()
        else:
            if self._auto_scan_timer:
                self._auto_scan_timer.cancel()

    def handle_login(self):
        """Handle login with validation"""
        email = self.email_var.get().strip()
        password = self.password_var.get().strip()
        
        if not email or not password:
            messagebox.showerror(self.t("error"), "Veuillez entrer votre email et mot de passe.")
            return
        
        self.set_status(self.t("authenticating"))
        threading.Thread(target=self._login_thread, args=(email, password), daemon=True).start()

    def _login_thread(self, email, password):
        """Login in background thread"""
        try:
            success = self.auth_manager.authenticate(email, password)
            self.ui_queue.put(lambda: self._post_login(success, email))
        except Exception as e:
            logger.error(f"Login thread error: {e}")
            self.ui_queue.put(lambda: self._post_login(False, email))

    def _post_login(self, success, email):
        """Post-login UI updates"""
        if success:
            if self.remember_email_var.get():
                self.config_manager.set('email', email)
            messagebox.showinfo(self.t("success"), self.t("login_success"))
        else:
            messagebox.showerror(self.t("error"), self.t("login_failed"))
        
        self.update_auth_status()
        self.set_status("Prêt")

    def browse_backup_folder(self):
        """Browse for backup folder with validation"""
        try:
            folder = filedialog.askdirectory(title="Sélectionner le dossier de sauvegarde")
            if folder:
                path = Path(folder)
                if path.is_dir() and os.access(path, os.W_OK):
                    self.backup_path_var.set(str(path))
                    self.config_manager.set('backup_path', str(path))
                else:
                    messagebox.showerror(self.t("error"), self.t("backup_folder_error"))
        except Exception as e:
            logger.error(f"Backup folder selection error: {e}")
            messagebox.showerror(self.t("error"), self.t("folder_selection_error"))

    def refresh_sources(self):
        """Refresh available sources avec traductions"""
        try:
            sources = self.file_manager.get_available_sources()
            if sources:
                sources_text = "\n".join([f"{name}: {path}" for name, path in sources.items()])
                self.sources_label.configure(text=sources_text)
            else:
                self.sources_label.configure(text=self.t("no_mywhoosh_detected"), style="Warning.TLabel")
        except Exception as e:
            logger.error(f"Sources refresh error: {e}")
            self.sources_label.configure(text=self.t("error_detected"), style="Error.TLabel")

    def create_tooltip(widget, text_key_or_text):
        """Enhanced tooltip with translation support"""
        tooltip = None
        
        def show_tooltip(event):
            nonlocal tooltip
            if tooltip:
                return
            
            # Better positioning calculation
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 5
            
            # Ensure tooltip stays on screen
            screen_width = widget.winfo_screenwidth()
            screen_height = widget.winfo_screenheight()
            
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            
            # Get text - support both direct text and translation keys
            try:
                # Try to get translation if it's a key
                if hasattr(widget.winfo_toplevel(), 't'):
                    display_text = widget.winfo_toplevel().t(text_key_or_text)
                else:
                    display_text = text_key_or_text
            except:
                display_text = text_key_or_text
            
            # Create label first to measure size
            label = tk.Label(
                tooltip, 
                text=display_text, 
                background='#2d3748',
                foreground='white',
                relief="solid", 
                borderwidth=1,
                font=("Segoe UI", 9),
                padx=8, 
                pady=4,
                wraplength=300
            )
            label.pack()
            
            # Update to get actual size
            tooltip.update_idletasks()
            tooltip_width = tooltip.winfo_reqwidth()
            tooltip_height = tooltip.winfo_reqheight()
            
            # Adjust position if tooltip would go off screen
            if x + tooltip_width > screen_width:
                x = screen_width - tooltip_width - 10
            if y + tooltip_height > screen_height:
                y = widget.winfo_rooty() - tooltip_height - 5
            
            tooltip.wm_geometry(f"+{x}+{y}")
            
            # Auto-hide after 8 seconds
            widget.after(8000, hide_tooltip)

        def hide_tooltip(event=None):
            nonlocal tooltip
            if tooltip:
                try:
                    tooltip.destroy()
                except:
                    pass
                tooltip = None
                
        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def scan_files_async(self):
        """Scan files asynchronously"""
        self.set_scan_status(self.t("scanning"))
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        """Scan files in background"""
        try:
            self.file_infos = self.file_manager.scan_files_async()
            self.ui_queue.put(self._update_files_ui)
        except Exception as e:
            logger.error(f"Scan thread error: {e}")
            self.ui_queue.put(lambda: self.set_scan_status(self.t("scan_error"), "error"))

    def _update_files_ui(self):
        """Update files treeview avec traductions"""
        try:
            # Clear existing items
            for item in self.files_tree.get_children():
                self.files_tree.delete(item)
            
            auto_select = self.auto_select_new_var.get()
            new_selections = set()
            
            for info in sorted(self.file_infos, key=lambda x: x.modified_time, reverse=True):
                # Utiliser les traductions pour le statut
                status = self.t("processed") if info.processed else self.t("new")
                tags = ("processed" if info.processed else "new",)
                
                iid = self.files_tree.insert('', 'end', text=' ', values=(
                    info.name, info.date, info.size, info.source, status
                ), tags=tags)
                
                if not info.processed and auto_select:
                    new_selections.add(iid)
            
            # Configure tags
            self.files_tree.tag_configure("processed", foreground=Colors.TEXT_SECONDARY)
            self.files_tree.tag_configure("new", foreground=Colors.TEXT)
            
            # Utiliser la traduction pour le compteur
            self.files_count_label.configure(text=f"{len(self.file_infos)} {self.t('files_count')}")
            
            # Auto-select new files
            if auto_select and new_selections:
                for iid in new_selections:
                    self.files_tree.selection_add(iid)
                self.update_selection_info()
            
            self.set_scan_status(self.t("scan_complete"), "success")
        except Exception as e:
            logger.error(f"Files UI update error: {e}")
            self.set_scan_status(self.t("scan_error"), "error")

    def on_tree_click(self, event):
        """Handle treeview single click - Leave selection to Tkinter, just update info"""
        try:
            # Laisser Tkinter gérer la sélection naturellement
            # Juste mettre à jour les informations de sélection après le clic
            self.after_idle(self.update_selection_info)
        except Exception as e:
            logger.debug(f"Erreur lors du clic sur l'arbre: {e}")

    def on_tree_double_click(self, event):
        """Handle treeview double click - preview file info"""
        try:
            item = self.files_tree.identify_row(event.y)
            if item:
                values = self.files_tree.item(item, "values")
                message = f"Nom: {values[0]}\nDate: {values[1]}\nTaille: {values[2]}\nSource: {values[3]}\nStatut: {values[4]}"
                messagebox.showinfo("Détails du fichier", message)
        except Exception as e:
            logger.debug(f"Tree double click error: {e}")

    def on_tree_right_click(self, event):
        """Handle right-click menu on treeview"""
        try:
            item = self.files_tree.identify_row(event.y)
            if item:
                self.files_tree.selection_set(item)
                menu = tk.Menu(self, tearoff=0)
                menu.add_command(label=self.t("mark_processed"), command=lambda: self.mark_as_processed(item))
                menu.add_command(label=self.t("mark_new"), command=lambda: self.mark_as_new(item))
                menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            logger.debug(f"Tree right click error: {e}")

    def mark_as_processed(self, item):
        """Mark file as processed"""
        try:
            values = self.files_tree.item(item, "values")
            if not values or len(values) < 1:
                logger.error("Impossible de récupérer les informations du fichier")
                return
            
            filename = values[0]
            info = next((f for f in self.file_infos if f.name == filename), None)
            
            if not info:
                logger.error(f"Fichier non trouvé dans la liste: {filename}")
                return
            
            # Marquer comme traité
            info.processed = True
            self.file_manager.mark_file_processed(info)
            
            # Mettre à jour l'affichage avec traduction
            self.files_tree.set(item, "status", self.t("processed") if hasattr(self, 't') else "Traité")
            self.files_tree.item(item, tags=("processed",))
            
            logger.info(f"Fichier marqué comme traité: {filename}")
            
        except Exception as e:
            logger.error(f"Erreur lors du marquage comme traité: {e}")

    def mark_as_new(self, item):
        """Mark file as new"""
        try:
            values = self.files_tree.item(item, "values")
            if not values or len(values) < 1:
                logger.error("Impossible de récupérer les informations du fichier")
                return
            
            filename = values[0]
            info = next((f for f in self.file_infos if f.name == filename), None)
            
            if not info:
                logger.error(f"Fichier non trouvé dans la liste: {filename}")
                return
            
            # Marquer comme nouveau
            info.processed = False
            
            # Supprimer de la liste des fichiers traités
            processed_files = self.config_manager.get("processed_files", {})
            
            # Chercher et supprimer par nom ET par hash si disponible
            keys_to_remove = []
            for key, data in processed_files.items():
                if isinstance(data, dict):
                    if (data.get('hash') == info.file_hash and info.file_hash) or \
                    filename in key:
                        keys_to_remove.append(key)
                elif filename in key:  # Format ancien
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                processed_files.pop(key, None)
            
            self.config_manager.set("processed_files", processed_files)
            
            # Mettre à jour l'affichage avec traduction
            self.files_tree.set(item, "status", self.t("new") if hasattr(self, 't') else "Nouveau")
            self.files_tree.item(item, tags=("new",))
            
            logger.info(f"Fichier marqué comme nouveau: {filename}")
            
        except Exception as e:
            logger.error(f"Erreur lors du marquage comme nouveau: {e}")

    def select_all_files(self):
        """Select all files"""
        try:
            self.files_tree.selection_set(self.files_tree.get_children())
            self.update_selection_info()
        except Exception as e:
            logger.debug(f"Select all error: {e}")

    def deselect_all_files(self):
        """Deselect all files"""
        try:
            self.files_tree.selection_remove(self.files_tree.get_children())
            self.update_selection_info()
        except Exception as e:
            logger.debug(f"Deselect all error: {e}")

    def update_selection_info(self):
        """Update selection count avec traduction"""
        if hasattr(self, 'files_tree') and hasattr(self, 'selection_info_label'):
            count = len(self.files_tree.selection())
            self.selection_info_label.configure(text=f"{count} {self.t('files_selected')}")

    def debug_os_compatibility(self):
        """Test de compatibilité OS"""
        logger.info("=== TEST COMPATIBILITÉ OS ===")
        logger.info(f"OS détecté: {OSDetector.get_system()}")
        
        sources = self.file_manager.get_available_sources()
        logger.info(f"Sources MyWhoosh: {list(sources.keys())}")
        
        for name, path in sources.items():
            fit_files = list(path.glob("MyNewActivity-*.fit"))
            logger.info(f"{name}: {len(fit_files)} fichiers FIT")

    def start_upload(self):
        """Start upload process"""
        if self.is_processing:
            return
        
        if not self.auth_manager.is_connected:
            messagebox.showerror(self.t("error"), self.t("login_required"))
            return
        
        selected_items = self.files_tree.selection()
        if not selected_items:
            messagebox.showwarning(self.t("warning"), self.t("no_files_selected"))
            return
        
        self.is_processing = True
        self.update_ui_state()
        self.set_status(self.t("upload_preparing"))
        
        selected_files = []
        for item in selected_items:
            index = self.files_tree.index(item)
            selected_files.append(self.file_infos[index].path)
        
        threading.Thread(target=self._upload_thread, args=(selected_files,), daemon=True).start()

    def _upload_thread(self, files):
        """Upload in background with progress"""
        try:
            def progress_callback(progress, message):
                self.ui_queue.put(lambda: self._update_progress(progress, message))
            
            backup_path = self.file_manager.get_backup_path()
            processed_files = []
            
            for file_path in files:
                if backup_path:
                    new_name = self.file_manager.generate_new_filename(file_path)
                    new_path = backup_path / new_name
                    if FitFileProcessor.cleanup_fit_file(file_path, new_path):
                        processed_files.append(new_path)
                    else:
                        logger.error(f"Nettoyage échoué pour {file_path.name}")
                        continue
                else:
                    processed_files.append(file_path)
            
            results = self.uploader.upload_files(processed_files, progress_callback)
            
            self.ui_queue.put(lambda: self._post_upload(results))
        except Exception as e:
            logger.error(f"Upload thread error: {e}")
            self.ui_queue.put(lambda: self._post_upload({}))

    def _update_progress(self, progress, message):
        """Update progress UI"""
        self.progress_var.set(progress)
        self.progress_label.configure(text=message)

    def _post_upload(self, results):
        """Post-upload UI updates avec traductions"""
        self.is_processing = False
        self.update_ui_state()
        self.progress_var.set(0)
        self.progress_label.configure(text=self.t("upload_complete"))
        
        stats = self.uploader.get_upload_stats()
        self.upload_stats_label.configure(
            text=f"{self.t('upload_success')}: {stats['success']} | {self.t('upload_failed')}: {stats['failed']} | {self.t('upload_duplicates')}: {stats['duplicates']}"
        )

        if stats['success'] + stats['duplicates'] == stats['total']:
            messagebox.showinfo(self.t("success"), self.t("upload_complete"))
        else:
            messagebox.showwarning(self.t("warning"), self.t("upload_complete_errors").format(stats['failed']))
        
        self.scan_files_async()
        self.set_status(self.t("ready")) 

    def stop_upload(self):
        """Stop upload (placeholder - implement if needed)"""
        messagebox.showinfo("Info", "Arrêt non implémenté dans cette version.")

    def cleanup_processed_files(self):
        """Cleanup processed files from list"""
        try:
            self.config_manager.set('processed_files', {})
            self.scan_files_async()
            messagebox.showinfo(self.t("success"), self.t("processed_files_cleaned"))
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    def update_ui_state(self):
        """Update UI based on state"""
        state = "disabled" if self.is_processing else "normal"
        self.upload_button.configure(state=state)
        self.login_button.configure(state=state)
        self.cleanup_button.configure(state=state)
        
        if self.auth_manager.is_connected:
            self.auth_status_label.configure(text=self.t("connected"), style="Success.TLabel")
            self.login_button.configure(text=self.t("logout"), command=self.handle_logout)
        else:
            self.auth_status_label.configure(text=self.t("not_connected"), style="Error.TLabel")
            self.login_button.configure(text=self.t("login"), command=self.handle_login)

    def handle_logout(self):
        """Handle logout"""
        self.auth_manager.disconnect()
        self.update_auth_status()

    def update_auth_status(self):
        """Update authentication status"""
        self.update_ui_state()

    def set_status(self, message, style="Subtitle.TLabel"):
        """Set status bar message"""
        self.status_var.set(message)
        # Note: style not directly applicable to status_label, but can add if needed

    def set_scan_status(self, message, level="info"):
        """Set scan status with color et traductions"""
        styles = {
            "success": "Success.TLabel",
            "error": "Error.TLabel", 
            "warning": "Warning.TLabel"
        }
        if hasattr(self, 'scan_status_label'):
            self.scan_status_label.configure(text=message, style=styles.get(level, "Info.TLabel"))
            self.after(5000, lambda: self.scan_status_label.configure(text=""))

    def on_closing(self):
        """Handle window closing"""
        try:
            # Signal aux threads de s'arrêter
            self._shutting_down = True
            
            # Annuler les timers actifs
            if hasattr(self, '_auto_scan_timer') and self._auto_scan_timer:
                self._auto_scan_timer.cancel()
            if hasattr(self, '_status_update_timer') and self._status_update_timer:
                self._status_update_timer.cancel()
            
            # Petite pause pour laisser les threads se terminer proprement
            time.sleep(0.5)
            
            # Sauvegarder la configuration
            if hasattr(self, 'config_manager'):
                self.config_manager.save(force=True)
            
            # Nettoyer les caches
            if hasattr(self, 'file_manager'):
                self.file_manager.cleanup_cache()
            
            # Déconnecter l'auth manager
            if hasattr(self, 'auth_manager'):
                self.auth_manager.disconnect()
            
            logger.info("Application fermée proprement")
            
        except Exception as e:
            logger.error(f"Erreur lors de la fermeture: {e}")
        finally:
            # Forcer la fermeture même en cas d'erreur
            try:
                self.destroy()
            except:
                pass

if __name__ == "__main__":
    if not PackageManager.ensure_packages():
        sys.exit(1)
    app = FitUploaderApp()
    app.mainloop()
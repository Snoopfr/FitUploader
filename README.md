# FitUploader
Upload de fichier FIT de MyWhoosh et TraningPeaks Virtual vers Garmin Connect


Application FitUploader
Usage: "python3 FitUploader.py"
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

"""Sistema de complementos (add-ons) do nvda-linux.

API pública para autores de add-ons: ver ``docs/semantics/ADDONS.md``.
"""

from nvda_linux.addons.addonHandler import Addon, AddonError, AddonManager, default_addons_dir
from nvda_linux.addons.manifest import AddonManifest, ManifestError, read_manifest

__all__ = [
    "Addon",
    "AddonError",
    "AddonManager",
    "AddonManifest",
    "ManifestError",
    "default_addons_dir",
    "read_manifest",
]

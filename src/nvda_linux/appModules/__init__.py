"""appModules do nvda-linux. Add-ons importam a base daqui::

    from nvda_linux.appModules import AppModule
"""

from nvda_linux.appModules.appModuleHandler import AppModule, AppModuleManager, normalize_app_name

__all__ = ["AppModule", "AppModuleManager", "normalize_app_name"]

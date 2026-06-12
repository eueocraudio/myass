"""Cliente — Parte I (Painel do administrador).

``admin`` é a camada lógica (sobre o canal Noise, papel publicador); ``admin_gui``
é a apresentação em PySide6. A Parte II (web pública PHP) vive em ``client/web/``.
"""

from .admin import AdminClient, AdminError

__all__ = ["AdminClient", "AdminError"]

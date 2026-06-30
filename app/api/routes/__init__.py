
# app/api/routes/__init__.py

from app.api.routes.upload  import router as upload_router
from app.api.routes.extract import router as extract_router
from app.api.routes.export  import router as export_router

__all__ = [
    "upload_router",
    "extract_router",
    "export_router",
]

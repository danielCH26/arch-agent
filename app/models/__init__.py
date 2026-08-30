# Registrar todos los modelos al importar el paquete app.models
# para que Base.metadata los conozca (necesario para create_all y migraciones).
from app.models.user import User  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.session import UserSession  # noqa: F401
from app.models.uploaded_document import UploadedDocument, DocumentChunk  # noqa: F401
from app.models.pattern import ArchitectPattern  # noqa: F401
# Registrar todos los modelos al importar el paquete app.models
# para que Base.metadata los conozca (necesario para create_all y migraciones).
#
# Nota: NO se importa ArchitectPattern aquí -- ese modelo vive en el PR del
# seed (F03), que todavía no está mergeado a esta rama. Cuando F03 se
# mergee, esa línea se agrega de nuevo (probablemente sin conflicto real,
# ya que ambos PRs solo agregan una línea nueva cada uno a este archivo).

from app.models.user import User  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.session import UserSession  # noqa: F401
from app.models.uploaded_document import UploadedDocument, DocumentChunk  # noqa: F401
from app.models.approval import Approval  # noqa: F401

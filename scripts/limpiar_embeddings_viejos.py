"""
Borra los patrones y documentos de prueba que se cargaron ANTES del fix de
prefijos e5 ("query: "/"passage: "), para que se puedan regenerar limpios.

Correr una sola vez, y después:
    python scripts/seed_patterns.py   (o scripts/seed.py)
    (y volver a subir cualquier documento de prueba desde el chat)
"""
from sqlalchemy import text
from app.core.database import engine

with engine.connect() as conn:
    result_patterns = conn.execute(text("DELETE FROM architect_patterns"))
    result_chunks = conn.execute(text("DELETE FROM document_chunks"))
    result_docs = conn.execute(text("DELETE FROM uploaded_documents"))
    conn.commit()

print(f"Patrones borrados: {result_patterns.rowcount}")
print(f"Chunks borrados: {result_chunks.rowcount}")
print(f"Documentos borrados: {result_docs.rowcount}")
print("Listo. Ahora corre: python scripts/seed_patterns.py")

"""
Utilidades compartidas para los scripts de seed.

Re-exporta scripts/_db_utils.py (compartido también con scripts/init_db.py)
en vez de duplicar log()/connect_db()/DATABASE_URL — ver comentario A2 en
la revisión del PR de "Caso de ejemplo (seed)".
"""

from _db_utils import DATABASE_URL, connect_db, log  # noqa: F401
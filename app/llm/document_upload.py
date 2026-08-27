"""
UI Chainlit para subir documentos al RAG (HU13).

Issue: #8 - HU13 Subir archivos PDF/MD al RAG

Flujo:
1. Usuario hace clic en "📄 Subir documento" en el menú
2. Aparece cl.AskFileMessage (acepta .pdf, .md)
3. Si NO es duplicado → procesar y guardar v1
4. Si ES duplicado → popup con 3 opciones (state machine):
   - Crear nueva versión (v+1)
   - Sobrescribir (delete v_actual + recreate)
   - Cancelar
5. Resultado: mensaje de éxito/error
"""

import os
import tempfile
from typing import Optional

import chainlit as cl
from langchain_core.documents import Document

from app.core.document_processing import (
    validate_file_extension,
    validate_file_size,
    process_file,
    DocumentProcessingError,
)
from app.core.document_storage import (
    check_duplicate,
    save_document,
    delete_document,
    overwrite_document,
    get_user_documents,
    DocumentStorageError,
)


# =============================================================================
# State machine en cl.user_session (para el popup de duplicados)
# =============================================================================


def get_upload_state() -> dict:
    """Obtiene el estado actual del upload."""
    state = cl.user_session.get("doc_upload_state")
    if state is None:
        state = {
            "step": None,  # None | "awaiting_file" | "awaiting_duplicate_action"
            "file_bytes": None,
            "file_name": None,
            "existing_version": None,
        }
        cl.user_session.set("doc_upload_state", state)
    return state


def set_upload_state(**kwargs):
    state = get_upload_state()
    state.update(kwargs)
    cl.user_session.set("doc_upload_state", state)


def clear_upload_state():
    cl.user_session.set("doc_upload_state", None)


# =============================================================================
# Menu items (HU13)
# =============================================================================


MENU_UPLOAD = ("menu_upload_document", "📄 Subir documento", "Subir PDF/MD al RAG")
MENU_LIST = ("menu_list_documents", "📋 Mis documentos", "Ver mis documentos subidos")


def get_menu_items():
    return [MENU_UPLOAD, MENU_LIST]


# =============================================================================
# Step 1: Upload - muestra el AskFileMessage
# =============================================================================


@cl.action_callback("menu_upload_document")
async def on_menu_upload_document(action: cl.Action):
    """Handler cuando el usuario hace clic en 'Subir documento'."""
    set_upload_state(step="awaiting_file")

    await cl.Message(
        content=(
            "## 📄 Subir documento al RAG\n\n"
            "**Formatos aceptados:** PDF y Markdown\n"
            "**Tamaño máximo:** 10MB\n\n"
            "Seleccioná tu archivo:"
        )
    ).send()

    files = await cl.AskFileMessage(
        content="📎 Selecciona el archivo:",
        accept=["application/pdf", "text/markdown", ".pdf", ".md"],
        max_size_mb=10,
        timeout=300,
    ).send()

    if not files:
        await cl.Message(content="❌ No se seleccionó ningún archivo.").send()
        clear_upload_state()
        return

    file = files[0]
    await _process_upload(file)


# =============================================================================
# Step 2: Validar + detectar duplicado
# =============================================================================


async def _process_upload(file):
    """Procesa el archivo subido: valida, chunkifica, indexa."""
    filename = file.name
    file_bytes = _get_file_bytes(file)

    # Validar extensión
    if not validate_file_extension(filename):
        await cl.Message(
            content=(
                f"❌ **Formato no soportado:** `{filename}`\n\n"
                "Solo se aceptan archivos **.pdf** y **.md**"
            )
        ).send()
        clear_upload_state()
        return

    # Validar tamaño
    if not validate_file_size(file_bytes):
        size_mb = file_bytes / (1024 * 1024)
        await cl.Message(
            content=(
                f"❌ **Archivo demasiado grande:** {size_mb:.2f}MB\n\n"
                f"Límite máximo: 10MB"
            )
        ).send()
        clear_upload_state()
        return

    # Detectar duplicado
    user_id = cl.user_session.get("user").metadata["user_id"]
    existing_version = check_duplicate(user_id, filename)

    if existing_version is not None:
        # Duplicado → guardar file en session y mostrar popup
        _save_pending_file(file)
        set_upload_state(
            step="awaiting_duplicate_action",
            file_bytes=file_bytes,
            file_name=filename,
            existing_version=existing_version,
        )
        await _show_duplicate_popup(filename, existing_version)
        return

    # No es duplicado → procesar directamente
    await _save_new_version(file, filename, file_bytes, version=1)


# =============================================================================
# Popup de duplicado (3 opciones)
# =============================================================================


async def _show_duplicate_popup(filename: str, existing_version: int):
    """Muestra popup con 3 acciones: crear v2, sobrescribir, cancelar."""
    actions = [
        cl.Action(
            name="doc_duplicate_action",
            payload={"action": "create_v2", "filename": filename},
            label=f"📝 Crear v{existing_version + 1}",
            description=f"Crear nueva versión (mantener v{existing_version} como respaldo)",
        ),
        cl.Action(
            name="doc_duplicate_action",
            payload={"action": "overwrite", "filename": filename},
            label="🔄 Sobrescribir",
            description=f"Borrar v{existing_version} y reemplazarla con el nuevo contenido",
        ),
        cl.Action(
            name="doc_duplicate_action",
            payload={"action": "cancel", "filename": filename},
            label="❌ Cancelar",
            description="No hacer nada",
        ),
    ]
    await cl.Message(
        content=(
            f"⚠️ **`{filename}` v{existing_version}** ya existe.\n\n"
            "¿Qué querés hacer?"
        ),
        actions=actions,
    ).send()


@cl.action_callback("doc_duplicate_action")
async def on_duplicate_action(action: cl.Action):
    """Handler del popup de duplicado."""
    action_type = action.payload.get("action")
    filename = action.payload.get("filename")
    state = get_upload_state()

    if action_type == "cancel":
        await cl.Message(content=f"❌ Carga de `{filename}` cancelada.").send()
        clear_upload_state()
        return

    # Para create_v2 y overwrite: necesitamos el file de session
    file = _get_pending_file()
    if not file:
        await cl.Message(
            content="❌ Sesión expirada. Volvé a subir el archivo."
        ).send()
        clear_upload_state()
        return

    user_id = cl.user_session.get("user").metadata["user_id"]
    existing_version = state.get("existing_version", 1)
    file_bytes = state.get("file_bytes", 0)

    # Procesar archivo
    try:
        chunks = _process_file(file, filename)
    except DocumentProcessingError as e:
        await cl.Message(content=f"❌ Error al procesar: {e}").send()
        clear_upload_state()
        return

    # Generar embeddings
    try:
        from app.core.embeddings import get_embeddings
        embeddings = get_embeddings().embed_documents(
            [chunk.page_content for chunk in chunks]
        )
    except Exception as e:
        await cl.Message(content=f"❌ Error al generar embeddings: {e}").send()
        clear_upload_state()
        return

    # Guardar según la acción elegida
    file_type = filename.split(".")[-1].lower()
    try:
        if action_type == "create_v2":
            doc_id = save_document(
                user_id=user_id,
                filename=filename,
                file_type=file_type,
                file_size_bytes=file_bytes,
                chunks=chunks,
                embeddings=embeddings,
            )
            await cl.Message(
                content=(
                    f"✅ **`{filename}` v{existing_version + 1}** creado\n\n"
                    f"- Chunks: {len(chunks)}\n"
                    f"- Versión anterior (v{existing_version}) preservada"
                )
            ).send()

        elif action_type == "overwrite":
            doc_id = overwrite_document(
                user_id=user_id,
                filename=filename,
                file_type=file_type,
                file_size_bytes=file_bytes,
                chunks=chunks,
                embeddings=embeddings,
            )
            await cl.Message(
                content=(
                    f"✅ **`{filename}` sobrescrito**\n\n"
                    f"- v{existing_version} reemplazada con nuevo contenido\n"
                    f"- Chunks: {len(chunks)}"
                )
            ).send()
    except DocumentStorageError as e:
        await cl.Message(content=f"❌ Error al guardar: {e}").send()

    clear_upload_state()


# =============================================================================
# Step 3: Guardar nueva versión (cuando no es duplicado)
# =============================================================================


async def _save_new_version(file, filename: str, file_bytes: int, version: int):
    """Procesa y guarda un nuevo documento."""
    user_id = cl.user_session.get("user").metadata["user_id"]

    await cl.Message(content=f"⏳ Procesando `{filename}`...").send()

    try:
        chunks = _process_file(file, filename)
    except DocumentProcessingError as e:
        await cl.Message(content=f"❌ Error al procesar: {e}").send()
        clear_upload_state()
        return

    try:
        from app.core.embeddings import get_embeddings
        embeddings = get_embeddings().embed_documents(
            [chunk.page_content for chunk in chunks]
        )
    except Exception as e:
        await cl.Message(content=f"❌ Error al generar embeddings: {e}").send()
        clear_upload_state()
        return

    file_type = filename.split(".")[-1].lower()
    try:
        doc_id = save_document(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size_bytes=file_bytes,
            chunks=chunks,
            embeddings=embeddings,
        )
        await cl.Message(
            content=(
                f"✅ **`{filename}` v{version}** creado\n\n"
                f"- Chunks: {len(chunks)}\n"
                f"- ID: {doc_id}"
            )
        ).send()
    except DocumentStorageError as e:
        await cl.Message(content=f"❌ Error al guardar: {e}").send()

    clear_upload_state()


# =============================================================================
# List documents
# =============================================================================


@cl.action_callback("menu_list_documents")
async def on_menu_list_documents(action: cl.Action):
    """Handler cuando el usuario hace clic en 'Mis documentos'."""
    user_id = cl.user_session.get("user").metadata["user_id"]
    docs = get_user_documents(user_id, limit=50)

    if not docs:
        await cl.Message(
            content="📋 **No has subido documentos todavía.**\n\n"
                   "Hacé clic en **📄 Subir documento** para empezar."
        ).send()
        return

    lines = [f"## 📋 Tus documentos ({len(docs)})\n"]
    for doc in docs:
        size_kb = (doc.file_size_bytes or 0) / 1024
        lines.append(
            f"- **{doc.filename}** v{doc.version} "
            f"({doc.file_type or '?'}, {size_kb:.1f}KB, "
            f"{doc.chunk_count or 0} chunks)"
        )

    # Botones de borrar por documento (max 10 visibles)
    actions = []
    for doc in docs[:10]:
        actions.append(
            cl.Action(
                name="delete_document",
                payload={"document_id": doc.id, "filename": doc.filename},
                label=f"🗑️ {doc.filename} v{doc.version}",
                description="Borrar este documento",
            )
        )

    await cl.Message(content="\n".join(lines), actions=actions).send()


@cl.action_callback("delete_document")
async def on_delete_document(action: cl.Action):
    """Borra un documento."""
    doc_id = action.payload.get("document_id")
    filename = action.payload.get("filename")

    user_id = cl.user_session.get("user").metadata["user_id"]
    ok = delete_document(user_id, doc_id)

    if ok:
        await cl.Message(content=f"🗑️ `{filename}` borrado correctamente.").send()
    else:
        await cl.Message(content=f"❌ No se pudo borrar `{filename}`.").send()


# =============================================================================
# Helpers
# =============================================================================


def _get_file_bytes(file) -> int:
    """Obtiene el tamaño en bytes de un archivo subido."""
    if hasattr(file, "content") and file.content:
        return len(file.content)
    if hasattr(file, "size"):
        return file.size
    return 0


def _process_file(file, filename: str) -> list[Document]:
    """
    Procesa el archivo: lo guarda a temp y llama a process_file().
    """
    from pathlib import Path

    # Si el file tiene path directo (caso común), usarlo
    if hasattr(file, "path") and file.path:
        return process_file(file.path)

    # Si solo tiene content, escribir a temp
    if hasattr(file, "content") and file.content:
        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file.content)
            tmp_path = tmp.name
        try:
            return process_file(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    raise DocumentProcessingError("No se pudo acceder al contenido del archivo")


def _save_pending_file(file):
    """Guarda el file object en session para el popup de duplicados."""
    # Convertir a dict serializable
    file_data = {
        "name": file.name,
        "content": getattr(file, "content", None),
        "path": getattr(file, "path", None),
        "size": getattr(file, "size", 0),
    }
    cl.user_session.set("pending_file", file_data)


def _get_pending_file():
    """Recupera el file de session para procesarlo en el popup."""
    file_data = cl.user_session.get("pending_file")
    if not file_data:
        return None

    # Recrear un objeto simple con los atributos necesarios
    class FakeFile:
        def __init__(self, data):
            self.name = data["name"]
            self.content = data["content"]
            self.path = data["path"]
            self.size = data["size"]

    return FakeFile(file_data)

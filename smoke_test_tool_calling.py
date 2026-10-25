"""
Smoke test de tool calling contra un proveedor OpenAI-compatible.

Uso:
    export LLM_BASE_URL="https://api.tu-proveedor.com/v1"
    export LLM_API_KEY="tu-api-key"
    export LLM_MODEL="minimax-m2"   # o el nombre exacto que use el proveedor

    python test_tool_calling.py

Qué hace:
    Envía un prompt que DEBERÍA disparar la tool ``puppeteer_screenshot``
    (mismo nombre/schema que usa tu agente real) y revisa si el modelo
    devuelve un `tool_calls` bien formado en la respuesta. Así confirmas
    si el proveedor traduce el tool calling nativo del modelo al formato
    OpenAI estándar ANTES de tocar tu código de producción.

No depende de LangChain ni de tu stack — solo del SDK de OpenAI, para
aislar el problema (¿es el modelo/proveedor, o es algo en tu wrapper?).
"""
import json
import os
import sys

from openai import OpenAI

BASE_URL = os.getenv("LLM_BASE_URL")
API_KEY = os.getenv("LLM_API_KEY")
MODEL = os.getenv("LLM_MODEL")

if not BASE_URL or not API_KEY or not MODEL:
    print("Faltan variables de entorno: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL")
    sys.exit(1)

# Mismo schema (simplificado) que expone tu allow-list de Puppeteer MCP.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "puppeteer_screenshot",
            "description": "Renderiza un diagrama Mermaid a PNG y lo captura como screenshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mermaid_code": {
                        "type": "string",
                        "description": "Bloque de código Mermaid a renderizar.",
                    },
                    "selector": {
                        "type": ["string", "null"],
                        "description": "Selector CSS opcional del elemento a capturar.",
                    },
                },
                "required": ["mermaid_code"],
            },
        },
    }
]

# Prompt diseñado para que SOLO tenga sentido si el modelo llama la tool.
PROMPT = (
    "Genera un diagrama Mermaid tipo flowchart con 3 nodos (A -> B -> C) "
    "y renderízalo usando la herramienta puppeteer_screenshot con el "
    "bloque mermaid completo."
)


def main() -> None:
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    print(f"Probando modelo={MODEL} en base_url={BASE_URL}\n")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT}],
        tools=TOOLS,
        tool_choice="auto",
    )

    choice = response.choices[0]
    message = choice.message
    tool_calls = getattr(message, "tool_calls", None) or []

    print("--- Respuesta cruda del modelo ---")
    print(f"finish_reason: {choice.finish_reason}")
    print(f"content: {message.content!r}")
    print(f"tool_calls detectados: {len(tool_calls)}")

    if not tool_calls:
        print(
            "\n[FALLO] El modelo NO emitió tool_calls. "
            "Mismo síntoma que gpt-oss-120b (tool_calls_missing). "
            "Este proveedor/modelo no es una mejora para tu caso de uso."
        )
        sys.exit(1)

    for i, call in enumerate(tool_calls, start=1):
        print(f"\ntool_call #{i}:")
        print(f"  name: {call.function.name}")
        try:
            args = json.loads(call.function.arguments)
            print(f"  arguments (parseados OK): {json.dumps(args, ensure_ascii=False, indent=2)}")
        except json.JSONDecodeError as e:
            print(f"  [FALLO] arguments NO son JSON válido: {call.function.arguments!r} ({e})")
            sys.exit(1)

    print(
        "\n[OK] El modelo llamó la tool correctamente y los argumentos "
        "parsean como JSON válido. Es un candidato viable para tu agente."
    )


if __name__ == "__main__":
    main()

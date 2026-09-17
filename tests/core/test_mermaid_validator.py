from app.core.mermaid_validator import extract_mermaid_block


def test_extract_mermaid_block_from_explicit_mermaid_fence():
    text = "```mermaid\nflowchart TD\nA-->B\n```"

    assert extract_mermaid_block(text) == "flowchart TD\nA-->B"


def test_extract_mermaid_block_from_plain_fence_when_content_is_mermaid():
    text = "```text\nflowchart TD\nA[Cliente]-->B[API]\n```"

    assert extract_mermaid_block(text) == "flowchart TD\nA[Cliente]-->B[API]"


def test_extract_mermaid_block_ignores_non_diagram_plain_code():
    text = "```python\nprint('hola')\n```"

    assert extract_mermaid_block(text) is None

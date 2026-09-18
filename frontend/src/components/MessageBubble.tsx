import type React from 'react'
import { useState } from 'react'
import { createPortal } from 'react-dom'
import type { Message } from '../stores/chatStore'
import { submitDiagramDecision } from '../api/diagrams'

interface MessageBubbleProps {
  message: Message
  projectId?: number
  onSendMessage?: (text: string, displayText?: string) => void
}

type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'code'; value: string }
  | { type: 'strong'; value: string }

const markdownTableSeparatorPattern = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/
const htmlTablePattern = /<table[\s\S]*?<\/table>/gi
const explicitMermaidFencePattern = /```mermaid\s*\n([\s\S]*?)```/i
const anyCodeFencePattern = /```[^\n]*\n([\s\S]*?)```/g
const mermaidFirstLinePattern = /^(flowchart|graph|sequenceDiagram|classDiagram)\b/

function splitTableRow(row: string) {
  return row
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function parseInline(content: string): InlineToken[] {
  const tokens: InlineToken[] = []
  const pattern = /(`([^`]+)`)|(\*\*([^*]+)\*\*)/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > cursor) {
      tokens.push({ type: 'text', value: content.slice(cursor, match.index) })
    }

    if (match[2]) {
      tokens.push({ type: 'code', value: match[2] })
    } else if (match[4]) {
      tokens.push({ type: 'strong', value: match[4] })
    }

    cursor = match.index + match[0].length
  }

  if (cursor < content.length) {
    tokens.push({ type: 'text', value: content.slice(cursor) })
  }

  return tokens
}

function renderInline(content: string) {
  return parseInline(content).map((token, index) => {
    if (token.type === 'strong') {
      return <strong key={index}>{token.value}</strong>
    }

    if (token.type === 'code') {
      return (
        <code key={index} className="rounded bg-black/10 px-1 py-0.5 text-[0.9em]">
          {token.value}
        </code>
      )
    }

    return <span key={index}>{token.value}</span>
  })
}

function extractMermaidFromMessage(content: string): string | null {
  const explicitMatch = content.match(explicitMermaidFencePattern)
  if (explicitMatch?.[1]?.trim()) {
    return explicitMatch[1].trim()
  }

  let match: RegExpExecArray | null
  anyCodeFencePattern.lastIndex = 0
  while ((match = anyCodeFencePattern.exec(content)) !== null) {
    const code = match[1].trim()
    const firstLine = code.split(/\r?\n/)[0] ?? ''
    if (mermaidFirstLinePattern.test(firstLine)) {
      return code
    }
  }

  return null
}

function buildDiagramAdjustmentPrompt(feedback: string, previousMermaid: string | null): string {
  if (!previousMermaid) return feedback

  return [
    'Modifica el siguiente diagrama Mermaid usando mi solicitud de cambio.',
    'Reglas importantes:',
    '- Responde UNICAMENTE con un bloque ```mermaid``` que contenga el diagrama completo actualizado.',
    '- No agregues explicaciones, tablas, leyendas, listas, resumen, recomendaciones ni proximos pasos fuera del bloque Mermaid.',
    '- Conserva todos los nodos, capas, componentes, relaciones, estilos y subgraphs existentes, salvo que mi cambio pida quitarlos explicitamente.',
    '- No simplifiques ni reescribas el diagrama desde cero.',
    '- Aplica solo el cambio solicitado.',
    '- Usa sintaxis Mermaid robusta: IDs sin espacios, labels complejos entre comillas, y evita HTML o caracteres innecesarios en las etiquetas.',
    '',
    'Solicitud de cambio:',
    feedback,
    '',
    'Diagrama Mermaid base:',
    '```mermaid',
    previousMermaid,
    '```',
  ].join('\n')
}

function parseHtmlTable(tableMarkup: string) {
  const parser = new DOMParser()
  const document = parser.parseFromString(tableMarkup, 'text/html')
  const rows = Array.from(document.querySelectorAll('tr')).map((row) =>
    Array.from(row.children)
      .filter((cell) => ['TH', 'TD'].includes(cell.tagName))
      .map((cell) => ({
        tag: cell.tagName.toLowerCase(),
        text: cell.textContent?.trim() ?? '',
      })),
  )

  return rows.filter((row) => row.length > 0)
}

function renderTable(rows: string[][], keyPrefix: string) {
  if (rows.length === 0) return null

  const [headers, ...bodyRows] = rows

  return (
    <div key={keyPrefix} className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th key={index} className="border border-gray-300 bg-gray-200 px-3 py-2 font-semibold">
                {renderInline(header)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bodyRows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-gray-50">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="border border-gray-300 px-3 py-2 align-top">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderHtmlTable(tableMarkup: string, keyPrefix: string) {
  const rows = parseHtmlTable(tableMarkup)
  if (rows.length === 0) return null

  return (
    <div key={keyPrefix} className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-gray-50">
              {row.map((cell, cellIndex) => {
                const Cell = cell.tag === 'th' ? 'th' : 'td'

                return (
                  <Cell
                    key={cellIndex}
                    className={`border border-gray-300 px-3 py-2 align-top ${
                      Cell === 'th' ? 'bg-gray-200 font-semibold' : ''
                    }`}
                  >
                    {renderInline(cell.text)}
                  </Cell>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// A veces el LLM envuelve la respuesta ENTERA en un solo bloque ```...```
// (comun cuando la respuesta mezcla tablas + texto + diagramas). Si lo
// dejamos pasar tal cual, el parser lo trata como codigo literal y el
// usuario ve markdown crudo (headers, **negritas**, | tablas |, todo sin
// renderizar). Esta funcion detecta ESE caso puntual -un unico par de
// fences que envuelve todo el mensaje- y lo desenvuelve antes de parsear.
// No toca bloques de codigo legitimos (fences que aparecen en medio de
// texto normal, o mensajes que son *solo* codigo sin pinta de markdown).
const outerFencePattern = /^```[^\n]*\n([\s\S]*?)\n```\s*$/

function stripFullMessageCodeFence(content: string): string {
  const trimmed = content.trim()
  const match = trimmed.match(outerFencePattern)
  if (!match) return content

  // Debe ser exactamente UN par de fences (apertura + cierre), no varios
  // bloques de codigo sueltos dentro de una respuesta normal.
  const fenceCount = (trimmed.match(/```/g) ?? []).length
  if (fenceCount !== 2) return content

  const inner = match[1]
  const looksLikeStructuredMarkdown =
    /^#{1,6}\s+/m.test(inner) ||
    /\*\*[^*]+\*\*/.test(inner) ||
    /^\s*\|.*\|\s*$/m.test(inner)

  // Si no hay señales de markdown estructurado adentro, es probable que
  // sea un snippet de codigo real -> lo dejamos como bloque de codigo.
  return looksLikeStructuredMarkdown ? inner : content
}

function renderMarkdownBlocks(content: string) {
  const normalizedContent = stripFullMessageCodeFence(content).replace(/<br\s*\/?>/gi, '\n')
  const parts = normalizedContent.split(htmlTablePattern)
  const htmlTables = normalizedContent.match(htmlTablePattern) ?? []
  const blocks: React.ReactNode[] = []

  parts.forEach((part, partIndex) => {
    const lines = part.split(/\r?\n/)
    let index = 0

    while (index < lines.length) {
      const line = lines[index]

      if (!line.trim()) {
        index += 1
        continue
      }

      const heading = line.match(/^(#{1,6})\s+(.+)$/)
      if (heading) {
        const Heading = `h${Math.min(heading[1].length + 2, 6)}` as keyof JSX.IntrinsicElements
        blocks.push(
          <Heading key={`heading-${partIndex}-${index}`} className="mb-2 mt-3 font-semibold leading-snug">
            {renderInline(heading[2])}
          </Heading>,
        )
        index += 1
        continue
      }

      if (/^\s*---+\s*$/.test(line)) {
        blocks.push(<hr key={`hr-${partIndex}-${index}`} className="my-4 border-gray-300" />)
        index += 1
        continue
      }

      if (line.trim().startsWith('```')) {
        const codeLines: string[] = []
        index += 1

        while (index < lines.length && !lines[index].trim().startsWith('```')) {
          codeLines.push(lines[index])
          index += 1
        }

        blocks.push(
          <pre key={`code-${partIndex}-${index}`} className="my-3 overflow-x-auto rounded bg-gray-900 p-3 text-gray-50">
            <code>{codeLines.join('\n')}</code>
          </pre>,
        )
        index += 1
        continue
      }

      if (line.includes('|') && markdownTableSeparatorPattern.test(lines[index + 1] ?? '')) {
        const tableRows = [splitTableRow(line)]
        index += 2

        while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
          tableRows.push(splitTableRow(lines[index]))
          index += 1
        }

        blocks.push(renderTable(tableRows, `table-${partIndex}-${index}`))
        continue
      }

      if (/^\s*(-|\d+\.)\s+/.test(line)) {
        const items: string[] = []
        const ordered = /^\s*\d+\.\s+/.test(line)

        while (index < lines.length && /^\s*(-|\d+\.)\s+/.test(lines[index])) {
          items.push(lines[index].replace(/^\s*(-|\d+\.)\s+/, ''))
          index += 1
        }

        const List = ordered ? 'ol' : 'ul'
        blocks.push(
          <List
            key={`list-${partIndex}-${index}`}
            className={`my-2 pl-5 ${ordered ? 'list-decimal' : 'list-disc'}`}
          >
            {items.map((item, itemIndex) => (
              <li key={itemIndex}>{renderInline(item)}</li>
            ))}
          </List>,
        )
        continue
      }

      const paragraphLines = [line.trim()]
      index += 1

      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^(#{1,6})\s+/.test(lines[index]) &&
        !/^\s*(-|\d+\.)\s+/.test(lines[index]) &&
        !markdownTableSeparatorPattern.test(lines[index])
      ) {
        paragraphLines.push(lines[index].trim())
        index += 1
      }

      blocks.push(
        <p key={`paragraph-${partIndex}-${index}`} className="my-2 leading-relaxed">
          {renderInline(paragraphLines.join(' '))}
        </p>,
      )
    }

    if (partIndex < htmlTables.length) {
      blocks.push(renderHtmlTable(htmlTables[partIndex], `html-table-${partIndex}`))
    }
  })

  return blocks
}

function renderSources(sources: Message['sources']) {
  // undefined = todavia no llego el evento 'sources' (o el mensaje es
  // viejo y nunca lo tuvo) -> no mostramos nada.
  if (sources === undefined) return null

  if (sources.length === 0) {
    return (
      <p className="mt-2 text-xs italic text-gray-400">
        Sin contexto recuperado de la base vectorial — respuesta basada en conocimiento general del modelo.
      </p>
    )
  }

  return (
    <div className="mt-2 border-t border-gray-200 pt-2 text-xs text-gray-500">
      <span className="font-semibold">Fuentes (PGVector):</span>
      <ul className="mt-1 space-y-0.5">
        {sources.map((source, index) => (
          <li key={index}>
            {source.name ?? source.source_type ?? 'desconocida'}
            {source.similarity != null && ` — similitud ${(source.similarity * 100).toFixed(0)}%`}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function MessageBubble({ message, projectId, onSendMessage }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[70%] px-4 py-2 rounded-lg break-words ${
          isUser
            ? 'whitespace-pre-wrap bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-900'
        }`}
      >
        {isUser ? message.content : renderMarkdownBlocks(message.content)}
        {!isUser && (
          <DiagramAttachments
            attachments={message.attachments}
            assistantContent={message.content}
            projectId={projectId}
            onSendMessage={onSendMessage}
          />
        )}
        {!isUser && renderSources(message.sources)}
      </div>
    </div>
  )
}

// F13 (REQ-PMCP-1 / REQ-ATT-3): renders the inline screenshot(s) the agent
// emitted via `` event: attachment``. Only fires for assistant messages —
// user messages never carry attachments. No download button in v1 (see
// design §8 Q-NEW-DOWNLOAD-PNG). The URL already carries the signed
// token, so no Authorization header is needed.
//
// HU6 (F09): mismo patron que el companero implemento para la fase de
// requerimientos en ChatWindow.tsx (ver handleDecision + showModify de
// HU5) pero a nivel de attachment individual:
//   - "Aprobar" no necesita texto libre -> se registra la decision y se
//     manda un mensaje de confirmacion fijo al chat (igual que antes).
//   - "Solicitar cambios" YA NO manda un mensaje a medio escribir apenas
//     se hace click. Abre un textarea inline (como el de HU5) para que
//     la persona escriba QUE hay que cambiar; solo al confirmar se
//     registra la decision (con ese feedback) y se envia ese texto real
//     al chat para que el agente regenere el diagrama.
//
// Zoom del diagrama (pedido de Laura): click en la miniatura abre un
// overlay fullscreen con la imagen en grande; click en cualquier parte
// del overlay lo cierra. Estado local `expandedUrl` guarda la URL del
// attachment actualmente ampliado (null = cerrado).
function DiagramAttachments({
  attachments,
  assistantContent,
  projectId,
  onSendMessage,
}: {
  attachments: Message['attachments']
  assistantContent: string
  projectId?: number
  onSendMessage?: (text: string, displayText?: string) => void
}) {
  const [openFeedbackFor, setOpenFeedbackFor] = useState<number | null>(null)
  const [feedback, setFeedback] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [decidedFor, setDecidedFor] = useState<Record<number, string>>({})
  const [expandedUrl, setExpandedUrl] = useState<string | null>(null)
  const [diagramZoom, setDiagramZoom] = useState(2)

  if (!attachments || attachments.length === 0) return null

  const handleApprove = async (index: number) => {
    setDecisionError('')
    if (projectId) {
      try {
        await submitDiagramDecision(projectId, 'approve')
      } catch (err) {
        // HU6: antes el error del backend se perdia (void + sin catch) y la
        // burbuja marcaba "Diagrama aprobado." aunque el POST hubiera fallado.
        setDecisionError(err instanceof Error ? err.message : 'No se pudo registrar la decision.')
        return
      }
    }
    setDecidedFor((prev) => ({ ...prev, [index]: 'Diagrama aprobado.' }))
    onSendMessage?.('Apruebo el diagrama, continuemos.')
  }

  // HU6: el boton "Rechazar" existia solo en DiagramHistoryPanel, asi que
  // desde el chat no habia forma de rechazar un diagrama. Mismo endpoint
  // (POST /api/diagrams/decision, phase="diagram"), decision="reject".
  // A diferencia de "Solicitar cambios", no manda ningun mensaje al chat:
  // rechazar corta el flujo, no pide una nueva iteracion.
  const handleReject = async (index: number) => {
    setDecisionError('')
    if (projectId) {
      try {
        await submitDiagramDecision(projectId, 'reject', feedback.trim() || undefined)
      } catch (err) {
        setDecisionError(err instanceof Error ? err.message : 'No se pudo registrar la decision.')
        return
      }
    }
    setDecidedFor((prev) => ({ ...prev, [index]: 'Diagrama rechazado.' }))
    setOpenFeedbackFor(null)
    setFeedback('')
  }

  const handleSendAdjustment = async (index: number) => {
    const trimmed = feedback.trim()
    if (!trimmed) {
      setDecisionError('Describe el cambio que necesitas antes de enviarlo.')
      return
    }
    setDecisionError('')
    if (projectId) {
      try {
        await submitDiagramDecision(projectId, 'modify', trimmed)
      } catch (err) {
        setDecisionError(err instanceof Error ? err.message : 'No se pudo registrar la decision.')
        return
      }
    }
    setDecidedFor((prev) => ({ ...prev, [index]: 'Se registró tu solicitud de cambios.' }))
    // El prompt completo (con instrucciones + Mermaid anterior) es lo que
    // necesita el agente para regenerar el diagrama, pero el usuario solo
    // escribió su feedback -- eso es lo que debe verse en su propia
    // burbuja, no el prompt entero (ver nota en chatStore.sendMessage).
    onSendMessage?.(
      buildDiagramAdjustmentPrompt(trimmed, extractMermaidFromMessage(assistantContent)),
      trimmed,
    )
    setOpenFeedbackFor(null)
    setFeedback('')
    setDecisionError('')
  }

  const openExpandedDiagram = (url: string) => {
    setDiagramZoom(2)
    setExpandedUrl(url)
  }

  return (
    <div className="mt-2 space-y-2">
      {attachments.map((attachment, index) => (
        <div key={`${attachment.url}-${index}`}>
          <img
            src={attachment.url}
            alt={attachment.filename}
            className="my-2 max-h-[70vh] w-full max-w-3xl rounded-lg object-contain cursor-zoom-in"
            loading="lazy"
            title="Click para ampliar"
            onClick={() => openExpandedDiagram(attachment.url)}
          />
          {onSendMessage && !decidedFor[index] && (
            <>
              <div className="flex gap-2 mt-1">
                <button
                  type="button"
                  onClick={() => void handleApprove(index)}
                  className="text-xs px-2 py-1 rounded bg-green-600 text-white hover:bg-green-700"
                >
                  ✅ Aprobar
                </button>
                <button
                  type="button"
                  onClick={() => void handleReject(index)}
                  className="text-xs px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700"
                >
                  ❌ Rechazar
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setOpenFeedbackFor(index)
                    setFeedback('')
                    setDecisionError('')
                  }}
                  className="text-xs px-2 py-1 rounded bg-gray-300 text-gray-800 hover:bg-gray-400"
                >
                  ✏️ Solicitar cambios
                </button>
              </div>
              {openFeedbackFor === index && (
                <div className="mt-2 space-y-2">
                  <label className="block text-xs font-medium text-gray-700" htmlFor={`diagram-feedback-${index}`}>
                    ¿Qué debe ajustarse en el diagrama?
                  </label>
                  <textarea
                    id={`diagram-feedback-${index}`}
                    value={feedback}
                    onChange={(event) => setFeedback(event.target.value)}
                    rows={3}
                    className="w-full rounded border border-gray-300 p-2 text-sm text-gray-900"
                    placeholder="Describe los cambios que necesitas en el diagrama..."
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleSendAdjustment(index)}
                      className="text-xs px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-700"
                    >
                      Enviar ajuste
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setOpenFeedbackFor(null)
                        setFeedback('')
                        setDecisionError('')
                      }}
                      className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-700 hover:bg-gray-100"
                    >
                      Cancelar
                    </button>
                  </div>
                  {decisionError && <p className="text-xs text-red-700">{decisionError}</p>}
                </div>
              )}
              {openFeedbackFor !== index && decisionError && (
                <p className="mt-1 text-xs text-red-700">{decisionError}</p>
              )}
            </>
          )}
          {decidedFor[index] && (
            <p className="mt-1 text-xs text-green-700">{decidedFor[index]}</p>
          )}
        </div>
      ))}
      {expandedUrl &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Visor de diagrama ampliado"
            className="fixed inset-0 z-[9999] bg-black/90"
          >
            <div className="fixed bottom-4 left-1/2 z-10 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-2 rounded border border-gray-700 bg-white p-2 text-sm shadow-2xl">
              <span className="px-2 font-semibold text-gray-800">Controles</span>
              <button
                type="button"
                onClick={() => setDiagramZoom((zoom) => Math.max(1, zoom - 0.5))}
                className="rounded border border-gray-300 px-3 py-1 font-semibold text-gray-800 hover:bg-gray-100"
                aria-label="Alejar diagrama"
              >
                -
              </button>
              <span
                className="min-w-14 text-center font-medium text-gray-700"
                role="status"
                aria-label={`Zoom actual ${Math.round(diagramZoom * 100)}%`}
              >
                {Math.round(diagramZoom * 100)}%
              </span>
              <button
                type="button"
                onClick={() => setDiagramZoom((zoom) => Math.min(6, zoom + 0.5))}
                className="rounded border border-gray-300 px-3 py-1 font-semibold text-gray-800 hover:bg-gray-100"
                aria-label="Acercar diagrama"
              >
                +
              </button>
              <button
                type="button"
                onClick={() => setDiagramZoom(2)}
                className="rounded border border-gray-300 px-3 py-1 text-gray-800 hover:bg-gray-100"
              >
                200%
              </button>
              <a
                href={expandedUrl}
                target="_blank"
                rel="noreferrer"
                className="rounded border border-gray-300 px-3 py-1 text-gray-800 hover:bg-gray-100"
              >
                Abrir original
              </a>
              <button
                type="button"
                onClick={() => setExpandedUrl(null)}
                className="rounded bg-gray-900 px-3 py-1 text-white hover:bg-gray-700"
                aria-label="Cerrar visor de diagrama"
              >
                Cerrar
              </button>
            </div>
            <div className="h-full w-full overflow-auto px-6 pb-24 pt-6">
              <div className="flex min-h-full min-w-full items-start justify-center">
                <img
                  src={expandedUrl}
                  alt="Diagrama ampliado"
                  className="h-auto max-w-none rounded bg-white shadow-2xl"
                  style={{ width: `${diagramZoom * 100}%` }}
                />
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}
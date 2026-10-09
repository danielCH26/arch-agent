import { useState } from 'react'
import type React from 'react'
import { submitDiagramDecision, type DiagramDecision } from '../api/diagrams'
import { useDialog } from '../hooks/useDialog'
import type { Message } from '../stores/chatStore'
import robotAvatar from '../assets/robot-avatar.webp'

// Devuelve false (o una promesa que resuelve false) si no se pudo enviar.
type SendMessage = (text: string, displayText?: string) => unknown

interface MessageBubbleProps {
  message: Message
  projectId?: number
  onSendMessage?: SendMessage
  // Hay una respuesta del agente en curso: no se envían mensajes nuevos.
  busy?: boolean
}

type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'code'; value: string }
  | { type: 'strong'; value: string }
  | { type: 'em'; value: string }
  | { type: 'link'; value: string; href: string }

// Viñetas (-, *, +) y numeradas (1. o 1)). El marcador debe ir seguido de un
// espacio, así "**negrita**" al inicio de línea no se toma como lista.
const listItemPattern = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/
const horizontalRulePattern = /^\s*([-*_])(\s*\1){2,}\s*$/
// Solo se enlazan URLs seguras; el resto se muestra como texto.
const safeLinkPattern = /^(https?:\/\/|mailto:)/i

const markdownTableSeparatorPattern = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/
const htmlTablePattern = /<table[\s\S]*?<\/table>/gi

const explicitMermaidFencePattern = /```mermaid\s*\n([\s\S]*?)```/i
const anyCodeFencePattern = /```[^\n]*\n([\s\S]*?)```/g
const mermaidFirstLinePattern = /^(flowchart|graph|sequenceDiagram|classDiagram)\b/

function extractMermaidBlocks(content: string): string[] {
  const explicit = [...content.matchAll(new RegExp(explicitMermaidFencePattern.source, 'gi'))]
    .map((match) => match[1].trim())
    .filter(Boolean)
  if (explicit.length > 0) return explicit

  return [...content.matchAll(anyCodeFencePattern)]
    .map((match) => match[1].trim())
    .filter((code) => mermaidFirstLinePattern.test(code.split(/\r?\n/)[0] ?? ''))
}

/**
 * Bloque Mermaid del diagrama `index` de la respuesta. Si la cantidad de
 * bloques no coincide con la de adjuntos, se usa el último (el más reciente).
 */
function mermaidForAttachment(content: string, index: number, attachmentCount: number): string | null {
  const blocks = extractMermaidBlocks(content)
  if (blocks.length === 0) return null
  return blocks.length === attachmentCount ? blocks[index] : blocks[blocks.length - 1]
}

// Prompt que recibe el agente al pedir cambios sobre un diagrama. El usuario
// solo ve su feedback (se envía como `display_message`).
function buildDiagramAdjustmentPrompt(feedback: string, previousMermaid: string | null): string {
  if (!previousMermaid) return `Solicito estos ajustes en el diagrama: ${feedback}`

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

function splitTableRow(row: string) {
  return row
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

export function parseInline(content: string): InlineToken[] {
  const tokens: InlineToken[] = []
  // Orden: código, negrita (** o __), enlace, cursiva (* o _). La cursiva con
  // _ exige bordes de palabra para no partir identificadores como mi_variable.
  const pattern =
    /(`([^`]+)`)|(\*\*([^*]+)\*\*|__([^_]+)__)|(\[([^\]]+)\]\(([^)\s]+)\))|(\*([^*\s][^*]*?)\*|(?<![\w])_([^_\s][^_]*?)_(?![\w]))/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > cursor) {
      tokens.push({ type: 'text', value: content.slice(cursor, match.index) })
    }

    if (match[2]) {
      tokens.push({ type: 'code', value: match[2] })
    } else if (match[3]) {
      tokens.push({ type: 'strong', value: match[4] ?? match[5] })
    } else if (match[6]) {
      tokens.push(
        safeLinkPattern.test(match[8])
          ? { type: 'link', value: match[7], href: match[8] }
          : { type: 'text', value: match[7] },
      )
    } else if (match[9]) {
      tokens.push({ type: 'em', value: match[10] ?? match[11] })
    }

    cursor = match.index + match[0].length
  }

  if (cursor < content.length) {
    tokens.push({ type: 'text', value: content.slice(cursor) })
  }

  return tokens
}

function renderInline(content: string): React.ReactNode[] {
  return parseInline(content).map((token, index) => {
    if (token.type === 'strong') {
      return <strong key={index}>{renderInline(token.value)}</strong>
    }

    if (token.type === 'em') {
      return <em key={index}>{renderInline(token.value)}</em>
    }

    if (token.type === 'link') {
      return (
        <a key={index} href={token.href} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">
          {renderInline(token.value)}
        </a>
      )
    }

    if (token.type === 'code') {
      return (
        <code key={index} className="rounded bg-black/10 px-1 py-0.5 dark:bg-white/10 text-[0.9em]">
          {token.value}
        </code>
      )
    }

    // Texto plano como string: <strong>texto</strong> en vez de <strong><span>…
    return token.value
  })
}

interface ListNode {
  text: string
  ordered: boolean
  number: number
  children: ListNode[]
}

/**
 * Lee una lista desde `start` (anidada por sangría) y devuelve los ítems de
 * primer nivel y la línea siguiente a la lista. Las líneas sangradas que no
 * son ítems continúan el ítem anterior.
 */
function parseList(lines: string[], start: number): { items: ListNode[]; next: number } {
  const root: ListNode[] = []
  // Niveles abiertos, del más externo al más interno, con su sangría.
  const stack: { indent: number; items: ListNode[] }[] = []
  let index = start
  let lastItem: ListNode | null = null

  const indentOf = (raw: string) => raw.replace(/\t/g, '    ').length

  while (index < lines.length) {
    const line = lines[index]
    const item = line.match(listItemPattern)

    if (item && !horizontalRulePattern.test(line)) {
      const indent = indentOf(item[1])
      if (stack.length === 0) stack.push({ indent, items: root })
      // Menos sangría: se cierran las sublistas más internas.
      while (stack.length > 1 && indent < stack[stack.length - 1].indent) stack.pop()
      const top = stack[stack.length - 1]
      // Más sangría que su nivel: sublista del ítem anterior.
      if (indent > top.indent && top.items.length > 0) {
        stack.push({ indent, items: top.items[top.items.length - 1].children })
      }
      const level = stack[stack.length - 1]
      const marker = item[2]
      const node: ListNode = {
        text: item[3],
        ordered: /\d/.test(marker),
        number: /\d/.test(marker) ? parseInt(marker, 10) : 1,
        children: [],
      }
      level.items.push(node)
      lastItem = node
      index += 1
      continue
    }

    // Continuación sangrada del ítem anterior.
    if (lastItem && line.trim() && /^\s{2,}/.test(line)) {
      lastItem.text += ` ${line.trim()}`
      index += 1
      continue
    }

    break
  }

  return { items: root, next: index }
}

function renderList(items: ListNode[], key: string): React.ReactNode {
  const ordered = items[0]?.ordered ?? false
  const List = ordered ? 'ol' : 'ul'
  return (
    <List
      key={key}
      start={ordered && items[0].number !== 1 ? items[0].number : undefined}
      className={`my-2 space-y-1 pl-5 ${ordered ? 'list-decimal' : 'list-disc'}`}
    >
      {items.map((item, itemIndex) => (
        <li key={itemIndex}>
          {renderInline(item.text)}
          {item.children.length > 0 && renderList(item.children, `${key}-${itemIndex}`)}
        </li>
      ))}
    </List>
  )
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

export function renderMarkdownBlocks(content: string) {
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

      if (horizontalRulePattern.test(line)) {
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
          <pre key={`code-${partIndex}-${index}`} className="my-3 overflow-x-auto rounded bg-gray-900 p-3 text-gray-50 dark:bg-gray-100 dark:text-gray-900">
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

      if (listItemPattern.test(line)) {
        const { items, next } = parseList(lines, index)
        blocks.push(renderList(items, `list-${partIndex}-${index}`))
        index = next
        continue
      }

      const paragraphLines = [line.trim()]
      index += 1

      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^(#{1,6})\s+/.test(lines[index]) &&
        !listItemPattern.test(lines[index]) &&
        !horizontalRulePattern.test(lines[index]) &&
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
      <p className="mt-2 text-xs italic text-gray-500">
        Sin contexto recuperado de la base vectorial — respuesta basada en conocimiento general del modelo.
      </p>
    )
  }

  return (
    <div className="mt-2 border-t border-gray-200 pt-2 text-xs text-gray-500">
      <span className="font-semibold">Fuentes consultadas:</span>
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

export function MessageBubble({ message, projectId, onSendMessage, busy = false }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex items-start gap-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <img
          src={robotAvatar}
          alt=""
          aria-hidden="true"
          draggable={false}
          className="mt-1 h-9 w-auto shrink-0 select-none"
        />
      )}
      <div
        className={`max-w-[85%] px-4 py-2 break-words md:max-w-[70%] ${
          isUser
            ? 'whitespace-pre-wrap rounded-lg bg-blue-600 text-white dark:bg-blue-100'
            : 'rounded-2xl rounded-tl-sm border border-sky-200 bg-sky-50 text-gray-900 shadow-sm'
        }`}
      >
        {isUser ? message.content : renderMarkdownBlocks(message.content)}
        {!isUser && (
          <DiagramAttachments
            attachments={message.attachments}
            assistantContent={message.content}
            projectId={projectId}
            onSendMessage={onSendMessage}
            busy={busy}
          />
        )}
        {!isUser && message.notices?.map((notice, index) => (
          <p key={index} role="status" className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            ⚠️ {notice}
          </p>
        ))}
        {!isUser && renderSources(message.sources)}
      </div>
    </div>
  )
}

// Zoom inicial del visor de diagramas (1 = ancho de la ventana).
const DEFAULT_DIAGRAM_ZOOM = 2

const decisionLabels: Record<DiagramDecision, string> = {
  approve: 'Diagrama aprobado.',
  reject: 'Diagrama rechazado.',
  modify: 'Se registró tu solicitud de cambios.',
}

function DiagramAttachments({
  attachments,
  assistantContent,
  projectId,
  onSendMessage,
  busy,
}: {
  attachments: Message['attachments']
  assistantContent: string
  projectId?: number
  onSendMessage?: SendMessage
  busy: boolean
}) {
  const [feedbackIndex, setFeedbackIndex] = useState<number | null>(null)
  const [feedback, setFeedback] = useState('')
  const [status, setStatus] = useState<Record<number, string>>({})
  const [submitting, setSubmitting] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [expandedUrl, setExpandedUrl] = useState<string | null>(null)
  const [diagramZoom, setDiagramZoom] = useState(DEFAULT_DIAGRAM_ZOOM)
  // Ajustes ya registrados en esta sesión, para reenviarlos si la respuesta
  // del agente falló.
  const [sentAdjustments, setSentAdjustments] = useState<Record<number, { prompt: string; display: string }>>({})
  const lightboxRef = useDialog({ open: expandedUrl !== null, onClose: () => setExpandedUrl(null) })

  if (!attachments?.length) return null

  // Envía el mensaje al chat; false si no se pudo (hay otra respuesta en curso).
  const send = async (text: string, displayText?: string) => {
    if (!onSendMessage) return false
    const result = displayText === undefined ? onSendMessage(text) : onSendMessage(text, displayText)
    if ((await result) === false) {
      setError('Hay una respuesta en curso. Inténtalo de nuevo cuando termine.')
      return false
    }
    return true
  }

  const recordDecision = async (index: number, decision: DiagramDecision, comment?: string) => {
    const attachment = attachments[index]
    if (!projectId) {
      setError('No se puede registrar la decisión sin un proyecto activo.')
      return false
    }

    setSubmitting(index)
    setError('')
    try {
      await submitDiagramDecision(projectId, decision, comment, attachment.id)
      setStatus((current) => ({ ...current, [index]: decisionLabels[decision] }))
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo registrar la decisión.')
      return false
    } finally {
      setSubmitting(null)
    }
  }

  const requestChanges = async (index: number) => {
    const trimmedFeedback = feedback.trim()
    if (!trimmedFeedback) {
      setError('Describe los cambios que necesitas antes de enviarlos.')
      return
    }
    if (await recordDecision(index, 'modify', trimmedFeedback)) {
      setFeedbackIndex(null)
      setFeedback('')
      const prompt = buildDiagramAdjustmentPrompt(
        trimmedFeedback,
        mermaidForAttachment(assistantContent, index, attachments.length),
      )
      setSentAdjustments((current) => ({ ...current, [index]: { prompt, display: trimmedFeedback } }))
      await send(prompt, trimmedFeedback)
    }
  }

  return (
    <div className="mt-3 space-y-3 border-t border-sky-200 pt-3">
      {attachments.map((attachment, index) => {
        const decided = status[index] ?? (attachment.decision ? decisionLabels[attachment.decision] : null)
        const isSubmitting = submitting === index

        return (
          <div key={`${attachment.id ?? attachment.url}-${index}`} className="rounded-xl border border-sky-200 bg-white/70 p-2">
            <button
              type="button"
              onClick={() => {
                setDiagramZoom(DEFAULT_DIAGRAM_ZOOM)
                setExpandedUrl(attachment.url)
              }}
              className="block w-full cursor-zoom-in rounded-lg"
              aria-label={`Ampliar ${attachment.filename || 'diagrama'}`}
            >
              <img
                src={attachment.url}
                alt={attachment.filename || 'Diagrama generado'}
                title="Click para ampliar"
                className="max-h-[420px] w-full rounded-lg bg-white object-contain"
                loading="lazy"
              />
            </button>

            {decided ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <p className="text-xs font-medium text-gray-600">{decided}</p>
                {sentAdjustments[index] && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void send(sentAdjustments[index].prompt, sentAdjustments[index].display)}
                    className="text-xs font-medium text-blue-700 underline disabled:opacity-50"
                  >
                    Volver a enviar el ajuste
                  </button>
                )}
              </div>
            ) : onSendMessage ? (
              <div className="mt-2">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={isSubmitting || busy}
                    onClick={async () => {
                      if (await recordDecision(index, 'approve')) await send('Apruebo el diagrama, continuemos.')
                    }}
                    className="rounded-md bg-solid-emerald-700 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-solid-emerald-800 disabled:opacity-50"
                  >
                    ✅ Aprobar
                  </button>
                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={() => void recordDecision(index, 'reject')}
                    className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"
                  >
                    ❌ Rechazar
                  </button>
                  <button
                    type="button"
                    disabled={isSubmitting || busy}
                    onClick={() => { setFeedbackIndex(index); setFeedback(''); setError('') }}
                    className="rounded-md border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-xs font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50"
                  >
                    ✏️ Solicitar cambios
                  </button>
                </div>

                {feedbackIndex === index && (
                  <div className="mt-3 space-y-2">
                    <label htmlFor={`diagram-feedback-${index}`} className="block text-xs font-medium text-gray-700">¿Qué debe ajustarse en el diagrama?</label>
                    <textarea
                      id={`diagram-feedback-${index}`}
                      value={feedback}
                      onChange={(event) => setFeedback(event.target.value)}
                      rows={3}
                      className="w-full rounded-lg border border-sky-200 bg-white p-2 text-sm text-gray-900 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/40"
                      placeholder="Describe los cambios que necesitas en el diagrama..."
                    />
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={isSubmitting || busy} onClick={() => void requestChanges(index)} className="rounded-md bg-blue-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:opacity-50">Enviar ajuste</button>
                      <button type="button" disabled={isSubmitting} onClick={() => { setFeedbackIndex(null); setFeedback(''); setError('') }} className="rounded-md px-2.5 py-1.5 text-xs text-gray-600 hover:bg-gray-100">Cancelar</button>
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )
      })}

      {error && <p role="alert" className="rounded-lg bg-red-50 p-2 text-xs text-red-700">{error}</p>}

      {expandedUrl && (
        <div
          ref={lightboxRef}
          role="dialog"
          aria-modal="true"
          aria-label="Visor de diagrama ampliado"
          className="fixed inset-0 z-50 bg-slate-950/90"
        >
          {/* Controles de zoom (Esc también cierra). */}
          <div className="fixed bottom-4 left-1/2 z-10 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white p-2 text-sm shadow-2xl">
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
              onClick={() => setDiagramZoom(DEFAULT_DIAGRAM_ZOOM)}
              className="rounded border border-gray-300 px-3 py-1 text-gray-800 hover:bg-gray-100"
            >
              {DEFAULT_DIAGRAM_ZOOM * 100}%
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
              className="rounded bg-solid-blue-700 px-3 py-1 font-medium text-white hover:bg-solid-blue-800"
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
        </div>
      )}
    </div>
  )
}

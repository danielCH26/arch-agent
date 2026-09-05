import type React from 'react'
import type { Message } from '../stores/chatStore'

interface MessageBubbleProps {
  message: Message
}

type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'code'; value: string }
  | { type: 'strong'; value: string }

const markdownTableSeparatorPattern = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/
const htmlTablePattern = /<table[\s\S]*?<\/table>/gi

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

export function MessageBubble({ message }: MessageBubbleProps) {
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
        {!isUser && renderSources(message.sources)}
      </div>
    </div>
  )
}
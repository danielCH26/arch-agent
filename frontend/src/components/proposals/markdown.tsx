/**
 * Proposal-specific markdown renderer.
 *
 * Proposals (per REQ-1 + the generator's prompt) are produced with a fixed
 * shape: three `## <Section>` headings followed by bullet lists, plus a
 * possible paragraph or two of context. We deliberately keep this renderer
 * narrower than `MessageBubble`'s full markdown so we don't have to lift
 * 150+ LoC of table-parsing logic out of MessageBubble (which is slice-1
 * territory and OUT of scope here).
 *
 * If a future proposal stream starts producing tables / HTML blocks /
 * nested ordered lists, we'll migrate to importing MessageBubble's
 * `renderMarkdownBlocks` (extract it into `frontend/src/lib/markdown.ts`
 * first, then update both call sites).
 */

import type React from 'react'

type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'code'; value: string }
  | { type: 'strong'; value: string }

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

function renderInline(content: string): React.ReactNode {
  return parseInline(content).map((token, index) => {
    if (token.type === 'strong') {
      return <strong key={index}>{token.value}</strong>
    }
    if (token.type === 'code') {
      return (
        <code
          key={index}
          className="rounded bg-black/10 px-1 py-0.5 text-[0.9em]"
        >
          {token.value}
        </code>
      )
    }
    return <span key={index}>{token.value}</span>
  })
}

/**
 * Render the proposal markdown into React nodes. Streaming-friendly: each
 * call is idempotent and cheap, so a new token simply re-renders the whole
 * card (the markdown stays small -- 1-3 KB even for verbose proposals).
 */
export function renderProposalMarkdown(content: string): React.ReactNode {
  if (!content) return null

  const lines = content.split(/\r?\n/)
  const blocks: React.ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6) // shift h2 -> h4
      const Heading = `h${level}` as keyof JSX.IntrinsicElements
      blocks.push(
        <Heading
          key={`heading-${index}`}
          className="mb-2 mt-3 text-base font-semibold leading-snug text-gray-900"
        >
          {renderInline(heading[2])}
        </Heading>,
      )
      index += 1
      continue
    }

    if (/^\s*---+\s*$/.test(line)) {
      blocks.push(
        <hr key={`hr-${index}`} className="my-4 border-gray-300" />,
      )
      index += 1
      continue
    }

    if (/^\s*(-|\d+\.)\s+/.test(line)) {
      const items: string[] = []
      const ordered = /^\s*\d+\.\s+/.test(line)
      while (
        index < lines.length &&
        /^\s*(-|\d+\.)\s+/.test(lines[index])
      ) {
        items.push(lines[index].replace(/^\s*(-|\d+\.)\s+/, ''))
        index += 1
      }
      const List = ordered ? 'ol' : 'ul'
      blocks.push(
        <List
          key={`list-${index}`}
          className={`my-2 pl-5 ${ordered ? 'list-decimal' : 'list-disc'} text-sm`}
        >
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item)}</li>
          ))}
        </List>,
      )
      continue
    }

    // Paragraph: collect contiguous non-empty, non-block-starting lines.
    const paragraphLines = [line.trim()]
    index += 1
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,6})\s+/.test(lines[index]) &&
      !/^\s*(-|\d+\.)\s+/.test(lines[index]) &&
      !/^\s*---+\s*$/.test(lines[index])
    ) {
      paragraphLines.push(lines[index].trim())
      index += 1
    }
    blocks.push(
      <p key={`paragraph-${index}`} className="my-2 text-sm leading-relaxed">
        {renderInline(paragraphLines.join(' '))}
      </p>,
    )
  }

  return blocks
}
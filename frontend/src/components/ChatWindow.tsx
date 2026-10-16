import { useEffect, useRef, useState } from 'react'
import { fetchDiagramHistory } from '../api/diagrams'
import { chatStore, HISTORY_LIMIT } from '../stores/chatStore'
import { projectsStore } from '../stores/projectsStore'
import { proposalsStore } from '../stores/proposalsStore'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ProposalCard } from './ProposalCard'
import { ChatHistorySkeleton } from './Skeleton'
import robotAvatar from '../assets/robot-avatar.webp'

// Texto plano para el lector de pantalla: sin bloques de código ni marcas
// de markdown.
function toSpokenText(markdown: string): string {
  return markdown
    .replace(/```mermaid[\s\S]*?```/gi, ' (diagrama) ')
    .replace(/```[\s\S]*?```/g, ' (bloque de código) ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/[#*_`>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

// Fase en la que se genera y refina el diagrama. "diagram"/"diagrama" son
// nombres heredados que todavía pueden existir en proyectos viejos.
const REFINEMENT_PHASES = new Set(['refinamiento', 'diagram', 'diagrama'])

export function isRefinementPhase(phase: string | null | undefined): boolean {
  return REFINEMENT_PHASES.has((phase ?? '').toLowerCase())
}

// Mensaje que se manda solo al entrar a Refinamiento si el proyecto todavía no
// tiene diagramas: el usuario no tiene que pedirlo a mano. Es el mismo texto
// que antes se escribía en el chat.
export const AUTO_DIAGRAM_PROMPT = 'genera el diagrama de la propuesta aprobada'

const HISTORY_WAIT_MS = 5000

// loadHistory reemplaza los mensajes de una vez: si el mensaje automático se
// manda antes de que termine, la carga lo pisaría.
async function waitForHistoryLoad(timeoutMs = HISTORY_WAIT_MS) {
  const start = Date.now()
  while (chatStore.getState().loadingHistory && Date.now() - start < timeoutMs) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
}

interface ChatWindowProps {
  projectId: number
  phase?: string | null
  onProposalPhaseChanged?: () => void | Promise<void>
}

export function ChatWindow({ projectId, phase, onProposalPhaseChanged }: ChatWindowProps) {
  const { messages, isStreaming, error, loadingHistory, historyTruncated } = chatStore()
  // Fase: la que pasa la página o, si no viene, la del proyecto activo.
  const storePhase = projectsStore((s) => s.currentProject?.current_phase ?? null)
  const currentPhase = phase ?? storePhase
  // La tarjeta de propuesta se mantiene montada mientras se genera o
  // modifica una propuesta, aunque la fase cambie durante el stream.
  const proposalStreaming = proposalsStore((s) => s.activity === 'generating' || s.activity === 'modifying')
  const showProposalCard = currentPhase === 'propuesta' || proposalStreaming
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // Anuncios para lectores de pantalla: la respuesta llega por fragmentos,
  // así que se anuncia una sola vez al terminar en vez de marcar la lista
  // de mensajes como región viva.
  const [announcement, setAnnouncement] = useState('')
  const wasStreaming = useRef(false)
  const [checkingDiagrams, setCheckingDiagrams] = useState(false)
  // Proyecto para el que ya se intentó el diagrama automático en esta visita a
  // Refinamiento (evita repetirlo en cada render o por StrictMode).
  const autoDiagramFor = useRef<number | null>(null)
  const phaseRef = useRef(currentPhase)
  phaseRef.current = currentPhase

  useEffect(() => {
    if (isStreaming && !wasStreaming.current) {
      setAnnouncement('ArchAgent está escribiendo…')
    } else if (!isStreaming && wasStreaming.current) {
      const last = [...messages].reverse().find((message) => message.role === 'assistant')
      const spoken = last ? toSpokenText(last.content) : ''
      setAnnouncement(spoken ? `ArchAgent respondió: ${spoken}` : '')
    }
    wasStreaming.current = isStreaming
  }, [isStreaming, messages])

  // Cada proyecto tiene una conversación propia en el backend. El guard evita
  // el doble GET que React StrictMode puede disparar durante el montaje.
  useEffect(() => {
    const state = chatStore.getState()
    if (
      (state.loadingHistory || state.isStreaming) &&
      state.activeProjectId === projectId
    ) {
      return
    }
    void state.loadHistory(projectId)
  }, [projectId])

  // Refinamiento: al entrar, si el proyecto todavía no tiene ningún diagrama,
  // se genera solo. Si ya hay diagramas (volver a entrar, F5) no se genera
  // otro: el historial del chat ya los muestra. Ante cualquier falla no se
  // hace nada; el usuario todavía puede pedirlo a mano.
  useEffect(() => {
    if (!isRefinementPhase(currentPhase)) {
      autoDiagramFor.current = null
      setCheckingDiagrams(false)
      return
    }
    if (autoDiagramFor.current === projectId) return
    if (proposalsStore.getState().activity !== 'idle') return
    autoDiagramFor.current = projectId
    setCheckingDiagrams(true)

    void (async () => {
      try {
        await waitForHistoryLoad()
        const diagrams = await fetchDiagramHistory(projectId)
        if (diagrams.length > 0) return
        if (!isRefinementPhase(phaseRef.current)) return
        const state = chatStore.getState()
        if (state.isStreaming || state.loadingHistory) return
        await state.sendMessage(projectId, AUTO_DIAGRAM_PROMPT)
      } catch {
        // Silencioso a propósito: el usuario puede pedir el diagrama a mano.
      } finally {
        setCheckingDiagrams(false)
      }
    })()
  }, [currentPhase, projectId])

  // Scroll to bottom on new messages
  useEffect(() => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    messagesEndRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [messages, isStreaming])

  const handleSend = (text: string, displayText?: string) =>
    chatStore.getState().sendMessage(projectId, text, displayText)

  return (
    <div className="flex flex-col h-full">
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {showProposalCard && (
          <ProposalCard projectId={projectId} onPhaseChanged={onProposalPhaseChanged} />
        )}
        {loadingHistory && messages.length === 0 && <ChatHistorySkeleton />}

        {historyTruncated && (
          <p className="text-center text-xs text-gray-500">
            Se muestran los últimos {HISTORY_LIMIT} mensajes de esta conversación.
          </p>
        )}

        {messages.length === 0 && !isStreaming && !loadingHistory && (
          <div className="text-center text-gray-500 py-8">
            <svg className="mx-auto h-12 w-12 text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p>Envía un mensaje para comenzar la conversación</p>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} projectId={projectId} onSendMessage={handleSend} busy={isStreaming} />
        ))}

        {checkingDiagrams && !isStreaming && (
          <p className="text-center text-xs text-gray-500" data-testid="auto-diagram-checking">
            Preparando el diagrama de la propuesta aprobada…
          </p>
        )}

        {isStreaming && (
          <div className="flex items-start gap-2 justify-start">
            <img src={robotAvatar} alt="" aria-hidden="true" draggable={false} className="mt-1 h-9 w-auto shrink-0 select-none" />
            <div className="rounded-2xl rounded-tl-sm border border-sky-200 bg-sky-50 px-4 py-2 shadow-sm">
              <div className="flex items-center gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div role="alert" className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">
            {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <ChatInput projectId={projectId} onSend={handleSend} disabled={isStreaming || loadingHistory} />
    </div>
  )
}

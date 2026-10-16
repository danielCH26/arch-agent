import { useEffect, useRef, useState } from 'react'
import { fetchDiagramHistory } from '../api/diagrams'
import { chatStore, HISTORY_LIMIT } from '../stores/chatStore'
import { projectsStore } from '../stores/projectsStore'
import { proposalsStore } from '../stores/proposalsStore'
import { AdrPanel } from './AdrPanel'
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
  // Refinamiento: aprobar el diagrama cierra la fase y avanza a Revisión.
  onDiagramApproved?: () => void | Promise<void>
  // Revisión: al aprobar el ADR el proyecto queda terminado.
  onProjectCompleted?: () => void | Promise<void>
}

export function ChatWindow({
  projectId,
  phase,
  onProposalPhaseChanged,
  onDiagramApproved,
  onProjectCompleted,
}: ChatWindowProps) {
  const { messages, isStreaming, error, loadingHistory, historyTruncated } = chatStore()
  // Fase: la que pasa la página o, si no viene, la del proyecto activo.
  const storePhase = projectsStore((s) => s.currentProject?.current_phase ?? null)
  const currentPhase = phase ?? storePhase
  // La tarjeta de propuesta se mantiene montada mientras se genera o
  // modifica una propuesta, aunque la fase cambie durante el stream.
  const proposalStreaming = proposalsStore((s) => s.activity === 'generating' || s.activity === 'modifying')
  const showProposalCard = currentPhase === 'propuesta' || proposalStreaming
  // Revisión (y Cierre, para volver a descargarlo): el ADR del proyecto.
  const showAdrPanel = currentPhase === 'revision' || currentPhase === 'final'
  const projectName = projectsStore((s) => (s.currentProject?.id === projectId ? s.currentProject?.name : null))
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // Anuncios para lectores de pantalla: la respuesta llega por fragmentos,
  // así que se anuncia una sola vez al terminar en vez de marcar la lista
  // de mensajes como región viva.
  const [announcement, setAnnouncement] = useState('')
  const wasStreaming = useRef(false)
  const [checkingDiagrams, setCheckingDiagrams] = useState(false)
  // Revisión/Cierre: el historial del chat es uno solo por proyecto (los
  // mensajes no guardan la fase), así que la conversación de Requerimientos,
  // Propuesta y Refinamiento se oculta detrás de un botón. `priorCount` es
  // cuántos mensajes había al entrar a la fase; los nuevos sí se muestran.
  // Se guarda junto con el proyecto al que pertenece: así cambiar de proyecto
  // invalida el conteo sin un efecto aparte (que corría después y lo borraba).
  const [prior, setPrior] = useState<{ projectId: number; count: number } | null>(null)
  const [showPrior, setShowPrior] = useState(false)
  const priorCount = showAdrPanel && prior?.projectId === projectId ? prior.count : null
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

  useEffect(() => {
    if (!showAdrPanel) {
      setPrior(null)
      setShowPrior(false)
      return
    }
    if (prior?.projectId === projectId) return
    // Se lee el store en vivo: el historial de ESTE proyecto debe estar cargado
    // (si no, el conteo quedaría en 0 y se verían todos los mensajes viejos).
    const state = chatStore.getState()
    if (!state.loadingHistory && state.activeProjectId === projectId) {
      setPrior({ projectId, count: state.messages.length })
      setShowPrior(false)
    }
  }, [showAdrPanel, loadingHistory, messages.length, prior, projectId])

  const hiddenCount = showAdrPanel && !showPrior && priorCount !== null ? priorCount : 0
  const visibleMessages = hiddenCount > 0 ? messages.slice(hiddenCount) : messages

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
        {showAdrPanel && (
          <AdrPanel projectId={projectId} projectName={projectName} onCompleted={onProjectCompleted} />
        )}
        {showProposalCard && (
          <ProposalCard projectId={projectId} onPhaseChanged={onProposalPhaseChanged} />
        )}
        {loadingHistory && messages.length === 0 && <ChatHistorySkeleton />}

        {historyTruncated && (
          <p className="text-center text-xs text-gray-500">
            Se muestran los últimos {HISTORY_LIMIT} mensajes de esta conversación.
          </p>
        )}

        {showAdrPanel && priorCount !== null && priorCount > 0 && (
          <div className="text-center">
            <button
              type="button"
              data-testid="toggle-prior-chat"
              onClick={() => setShowPrior((value) => !value)}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              {showPrior
                ? 'Ocultar la conversación de las fases anteriores'
                : `Ver la conversación de las fases anteriores (${priorCount} mensajes)`}
            </button>
          </div>
        )}

        {messages.length === 0 && !isStreaming && !loadingHistory && !showAdrPanel && (
          <div className="text-center text-gray-500 py-8">
            <svg className="mx-auto h-12 w-12 text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p>Envía un mensaje para comenzar la conversación</p>
          </div>
        )}

        {visibleMessages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            projectId={projectId}
            onSendMessage={handleSend}
            busy={isStreaming}
            onDiagramApproved={isRefinementPhase(currentPhase) ? onDiagramApproved : undefined}
          />
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

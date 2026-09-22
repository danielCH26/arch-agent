import { proposalsStore } from '../../stores/proposalsStore'
import { CitationList } from './CitationList'
import { ProposalActions } from './ProposalActions'
import { renderProposalMarkdown } from './markdown.tsx'

interface ProposalCardProps {
  /**
   * When true, the card mounts unconditionally; when false, the parent
   * ChatWindow only renders it under `current_phase === "propuesta"` OR
   * while a proposal is in flight (SCN-8 / REQ-7).
   */
  forceMount?: boolean
  /**
   * Project id used by the explicit "Generar propuesta" trigger
   * (`proposalsStore.generate`). Per proposal.md decision #5 the trigger is
   * an explicit user action (button), NOT automatic on phase entry. When
   * omitted the button is hidden (backwards-compatible for embedders).
   */
  projectId?: number
}

/**
 * The proposal surface mounted by ChatWindow when the project is in
 * `propuesta` phase (SCN-8). Shows streamed markdown + citations + the
 * approve/modify/reject action panel once the stream completes.
 *
 * The component reads directly from `proposalsStore` (no props for content)
 * so the store stays the single source of truth and the card always reflects
 * the latest streamed chunk.
 */
export function ProposalCard({ forceMount, projectId }: ProposalCardProps) {
  const currentProposal = proposalsStore((s) => s.currentProposal)
  const inFlight = proposalsStore((s) => s.inFlight)
  const iterations = proposalsStore((s) => s.iterations)
  const error = proposalsStore((s) => s.error)
  const generate = proposalsStore((s) => s.generate)

  // Empty state when nothing has streamed yet (parent decided to mount us).
  if (!currentProposal && iterations.length === 0 && !forceMount) {
    return null
  }

  const lifecycle = currentProposal?.lifecycle ?? 'proposed'

  return (
    <div
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-testid="proposal-card"
      data-lifecycle={lifecycle}
    >
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">
          Propuesta de arquitectura
          {currentProposal && currentProposal.iteration > 0
            ? ` · iteración ${currentProposal.iteration}`
            : ''}
        </h3>
        <LifecycleChip lifecycle={lifecycle} />
      </div>

      {currentProposal?.feedback && (
        <p className="mb-2 rounded bg-blue-50 px-2 py-1 text-xs text-blue-700">
          Feedback previo: <span className="italic">{currentProposal.feedback}</span>
        </p>
      )}

      <div
        className="prose prose-sm max-w-none text-gray-900"
        data-testid="proposal-content"
      >
        {currentProposal?.content_markdown
          ? renderProposalMarkdown(currentProposal.content_markdown)
          : inFlight === 'generating' || inFlight === 'modifying'
            ? <p className="italic text-gray-400">Generando propuesta...</p>
            : <p className="italic text-gray-400">Aún no hay propuesta.</p>}
      </div>

      {/* Explicit generation trigger (proposal.md decision #5): when the
          stream is idle and nothing has been produced yet, offer the
          "Generar propuesta" action. It also serves as the retry affordance
          after a failed generation (store error surfaced inline). */}
      {projectId != null && inFlight === 'idle' && !currentProposal?.content_markdown && (
        <div className="mt-3 flex flex-col gap-2">
          {error && (
            <p className="text-xs text-red-600" data-testid="proposal-generate-error">
              {error}
            </p>
          )}
          <button
            type="button"
            data-testid="proposal-generate"
            onClick={() => void generate(projectId)}
            className="self-start rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            Generar propuesta
          </button>
        </div>
      )}

      {currentProposal?.citations && (
        <CitationList citations={currentProposal.citations} />
      )}

      {currentProposal?.id != null && lifecycle === 'proposed' && (
        <ProposalActions proposalId={currentProposal.id} />
      )}
    </div>
  )
}

function LifecycleChip({
  lifecycle,
}: {
  lifecycle: 'proposed' | 'approved' | 'rejected' | 'idle'
}) {
  if (lifecycle === 'approved') {
    return (
      <span
        className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700"
        data-testid="lifecycle-chip-approved"
      >
        Aprobada
      </span>
    )
  }
  if (lifecycle === 'rejected') {
    return (
      <span
        className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700"
        data-testid="lifecycle-chip-rejected"
      >
        Rechazada
      </span>
    )
  }
  return (
    <span
      className="rounded bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-600"
      data-testid="lifecycle-chip-proposed"
    >
      Propuesta
    </span>
  )
}
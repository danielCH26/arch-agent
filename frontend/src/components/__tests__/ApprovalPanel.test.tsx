import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../api/elicitation', () => ({ decideElicitation: vi.fn() }))

import { ApprovalPanel, resumenEntries } from '../ApprovalPanel'

describe('ApprovalPanel — origen de los atributos de calidad', () => {
  const resumen = {
    problema: 'Citas por teléfono',
    calidad: ['Seguridad', 'Disponibilidad'],
    calidad_origen: { Seguridad: 'dicho', Disponibilidad: 'propuesto' },
  }

  it('marca los atributos propuestos por el agente y no muestra calidad_origen como campo', () => {
    const entries = resumenEntries(resumen)
    expect(entries.map(([key]) => key)).toEqual(['problema', 'calidad'])
    expect(entries[1][1]).toEqual(['Seguridad', 'Disponibilidad (propuesto por el agente)'])
  })

  it('un resumen sin origen se muestra igual que antes', () => {
    expect(resumenEntries({ calidad: ['Seguridad'] })).toEqual([['calidad', ['Seguridad']]])
  })

  it('en pantalla se ve la marca', () => {
    render(<ApprovalPanel projectId={1} resumen={resumen} onDecided={vi.fn()} />)
    expect(screen.getByText('Disponibilidad (propuesto por el agente)')).toBeInTheDocument()
    expect(screen.queryByText(/calidad origen/i)).not.toBeInTheDocument()
  })
})

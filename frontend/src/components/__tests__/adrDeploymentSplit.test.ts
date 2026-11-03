import { describe, expect, it } from 'vitest'
import { splitAtDeploymentHeading } from '../AdrPanel'

/**
 * El corte que abre hueco para la imagen del diagrama de despliegue dentro
 * del ADR, justo debajo de su encabezado. Sin el corte, la imagen quedaría
 * al final de la sección anterior, como si ilustrara otra cosa.
 */
describe('splitAtDeploymentHeading', () => {
  const MD = [
    'Texto previo.',
    '',
    '### Despliegue en Amazon Web Services',
    '',
    '| Componente | Servicio |',
    '| --- | --- |',
    '',
    '## 5. Referencias',
  ].join('\n')

  it('parte en el encabezado del despliegue', () => {
    const parts = splitAtDeploymentHeading(MD)
    expect(parts.hasHeading).toBe(true)
    expect(parts.heading).toBe('### Despliegue en Amazon Web Services')
    expect(parts.before).toContain('Texto previo.')
    expect(parts.before).not.toContain('Despliegue en')
    expect(parts.after).toContain('| Componente | Servicio |')
    expect(parts.after).toContain('## 5. Referencias')
  })

  it('reconoce cualquier nube, no solo AWS', () => {
    const parts = splitAtDeploymentHeading('x\n### Despliegue en Google Cloud Platform\ny')
    expect(parts.hasHeading).toBe(true)
    expect(parts.heading).toContain('Google Cloud Platform')
  })

  it('sin la sección devuelve el texto entero sin tocar', () => {
    const parts = splitAtDeploymentHeading('## 4. Diagrama\n\nAlgo.')
    expect(parts.hasHeading).toBe(false)
    expect(parts.before).toBe('## 4. Diagrama\n\nAlgo.')
    expect(parts.after).toBe('')
  })

  it('no confunde un encabezado de otro nivel', () => {
    // "## Despliegue" (dos almohadillas) no es la subsección que escribe el
    // ADR; partir ahí metería la imagen en el sitio equivocado.
    const parts = splitAtDeploymentHeading('## Despliegue en AWS\ntexto')
    expect(parts.hasHeading).toBe(false)
  })

  it('tolera un documento vacío', () => {
    expect(splitAtDeploymentHeading('').hasHeading).toBe(false)
  })
})

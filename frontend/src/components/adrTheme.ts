// Identidad visual del ADR ("ArchAgent Blueprint"): paleta de azules,
// tipografías y espaciados del documento entregable (PDF).
//
// Colores y tipografías son los mismos de app/core/adr_theme.py, que los usa
// para los diagramas Mermaid; tests/core/test_adr_quality.py comprueba que no
// se separen.
// Reglas de uso en .atl/skills/adr-design/SKILL.md.

export const ADR_PALETTE = {
  // Azules
  navy: '#0B1F3A', // portada, encabezado de tablas, títulos de capítulo
  primary: '#1D4E89', // títulos, enlaces, bordes de acento
  secondary: '#2F74D0', // subtítulos, viñetas, bordes de nodos
  accent: '#38A3D9', // detalles (filete de portada, numeración)
  sky: '#D6E6F8', // bordes suaves, nodos secundarios
  tint: '#EEF4FC', // fondos de recuadros y nodos
  // Neutros
  ink: '#1B2533', // texto
  muted: '#5B6B80', // texto secundario, pies de figura
  line: '#D9E2EC', // filetes y bordes de tabla
  paper: '#F7F9FC', // filas alternas, bloques de código
  // Apoyo (solo para estados, nunca decorativos)
  success: '#1E7B4F',
  success_bg: '#E3F4EA',
  warning: '#9A5B00',
  warning_bg: '#FFF4DD',
  danger: '#B42318',
  danger_bg: '#FDECEA',
} as const

export const ADR_FONTS = {
  heading: "'Plus Jakarta Sans', 'Segoe UI', Helvetica, Arial, sans-serif",
  body: "'Inter', 'Segoe UI', Helvetica, Arial, sans-serif",
  mono: "'JetBrains Mono', Consolas, 'Courier New', monospace",
} as const

// Las tipografías se piden a Google Fonts; sin conexión quedan las de respaldo.
export const ADR_FONTS_HREF =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500' +
  '&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap'

// Escala de espaciado (pt) y tamaños de letra del documento.
export const ADR_SPACE = { xs: 4, sm: 8, md: 12, lg: 18, xl: 28 } as const
export const ADR_TYPE = { body: 10.5, small: 8.5, h5: 12.5, h4: 17, cover: 32 } as const

import colors from 'tailwindcss/colors.js'
import plugin from 'tailwindcss/plugin.js'

// --- Modo oscuro -------------------------------------------------------------
// Las paletas usadas en la app se definen con variables CSS. En `.dark` se
// reasignan sus valores, así los componentes no necesitan una variante
// `dark:` por cada clase (bg-gray-50, text-red-700, border-sky-200…).
// Ojo al escribir una variante `dark:` con estas paletas: el tono ya está
// invertido, p. ej. `dark:bg-blue-100` se ve como el azul 900.

const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

// Tintes claros <-> tonos oscuros. 400–600 (botones, marca) no cambian.
const DARK_SWAP = { 50: 950, 100: 900, 200: 800, 300: 700, 700: 300, 800: 200, 900: 100, 950: 50 }
const SWAPPED_PALETTES = ['blue', 'red', 'sky', 'green', 'amber', 'emerald', 'indigo', 'orange']

// Grises: superficies oscuras y texto claro.
const DARK_GRAY = {
  50: '#1f2937', // campos y superficies secundarias
  100: '#111827', // fondo de la página, hover
  200: '#374151', // bordes
  300: '#4b5563',
  400: '#6b7280', // texto de ayuda, íconos
  500: '#9ca3af', // texto secundario
  600: '#d1d5db',
  700: '#e5e7eb',
  800: '#f3f4f6',
  900: '#f9fafb',
  950: '#ffffff',
}
// `slate` se usa para superficies suaves (50/100) y para overlays oscuros
// (900/950), que deben seguir oscuros.
const DARK_SLATE = { 50: '#1f2937', 100: '#273244' }

// Superficie de tarjetas y paneles (`bg-white` en modo claro).
const DARK_SURFACE = '#1a2230'

// Tonos que NO se invierten en modo oscuro, para fondos de botones con texto
// blanco (contraste >= 4.5:1 en ambos temas). Ej.: `bg-solid-emerald-700`,
// `dark:hover:bg-solid-blue-700`.
const SOLID = Object.fromEntries(
  ['blue', 'red', 'emerald'].flatMap((name) =>
    [700, 800].map((shade) => [`${name}-${shade}`, colors[name][shade]]),
  ),
)

const PALETTES = ['gray', 'slate', ...SWAPPED_PALETTES]

const rgb = (hex) => {
  const value = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16)).join(' ')
}

const varPalette = (name) =>
  Object.fromEntries(SHADES.map((shade) => [shade, `rgb(var(--${name}-${shade}) / <alpha-value>)`]))

const lightVars = {}
const darkVars = { '--surface': rgb(DARK_SURFACE) }
for (const name of PALETTES) {
  for (const shade of SHADES) {
    lightVars[`--${name}-${shade}`] = rgb(colors[name][shade])
    let dark = colors[name][shade]
    if (name === 'gray') dark = DARK_GRAY[shade]
    else if (name === 'slate') dark = DARK_SLATE[shade] ?? dark
    else if (DARK_SWAP[shade]) dark = colors[name][DARK_SWAP[shade]]
    darkVars[`--${name}-${shade}`] = rgb(dark)
  }
}

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ...Object.fromEntries(PALETTES.map((name) => [name, varPalette(name)])),
        solid: SOLID,
      },
      fontFamily: {
        // Títulos principales y marca (diseño de Figma "UI-ArchAgent").
        display: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [
    plugin(({ addBase }) => {
      addBase({
        ':root': lightVars,
        '.dark': { ...darkVars, colorScheme: 'dark' },
      })
    }),
  ],
}

import { useEffect, useRef, useState } from 'react'
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { authStore } from '../stores/authStore'
import { projectsStore } from '../stores/projectsStore'
import { CreateProjectDialog } from './CreateProjectDialog'
import { ErrorBoundary } from './ErrorBoundary'
import { Logo } from './Logo'
import { SidebarProjectsSkeleton } from './Skeleton'
import { ThemeToggle } from './ThemeToggle'
import { ArchiveIcon, ChatIcon, ClockIcon, DocumentIcon, FolderIcon, PlusIcon } from './NavIcons'

// Elementos del menú: misma cuadrícula (px-3, ícono de 20 px, gap-3) en todos.
// El activo usa un tinte azul claro con indicador lateral, del mismo azul
// que los botones principales (bg-blue-600), en lugar de un bloque sólido.
const NAV_ITEM = 'relative flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors'
const NAV_ACTIVE =
  'bg-blue-50 font-semibold text-blue-700 before:absolute before:inset-y-1.5 before:w-[3px] before:rounded-full before:bg-blue-600'
const NAV_IDLE = 'font-medium text-gray-700 hover:bg-gray-100 hover:text-gray-900'
const navItemClass = (active: boolean) => `${NAV_ITEM} ${active ? `${NAV_ACTIVE} before:left-0` : NAV_IDLE}`
// Submenús: el indicador del activo se dibuja sobre la guía vertical.
const subItemClass = (active: boolean) => `${NAV_ITEM} ${active ? `${NAV_ACTIVE} before:-left-[12px]` : NAV_IDLE}`

export function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = authStore((state) => state.user)
  const logout = authStore((state) => state.logout)
  const projects = projectsStore((state) => state.projects)
  const fetchProjects = projectsStore((state) => state.fetchProjects)
  const projectsLoaded = projectsStore((state) => state.hasLoaded)
  const projectsError = projectsStore((state) => state.error)

  const [expanded, setExpanded] = useState<number | null>(null)
  // Menú lateral en pantallas pequeñas (< md): se abre como panel deslizable.
  const [menuOpen, setMenuOpen] = useState(false)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const closeMenuRef = useRef<HTMLButtonElement>(null)
  const openMenuRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  // Auto-expand project when navigating to its routes
  useEffect(() => {
    const match = location.pathname.match(/^\/projects\/(\d+)/)
    if (match) {
      const projectId = parseInt(match[1], 10)
      setExpanded(projectId)
    }
  }, [location.pathname])

  // Cerrar el menú móvil al navegar.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!menuOpen) return
    // Al abrir, el foco entra al menú; al cerrar vuelve al botón ☰.
    closeMenuRef.current?.focus()
    const opener = openMenuRef.current
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      // Si el foco quedó dentro del menú (ahora oculto), vuelve al botón ☰
      // (offsetParent es null en desktop, donde ese botón no se muestra).
      if (document.activeElement?.closest('#app-sidebar') && opener?.offsetParent) opener.focus()
    }
  }, [menuOpen])

  const toggleExpand = (projectId: number) => {
    setExpanded((prev) => (prev === projectId ? null : projectId))
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const isActivePath = (path: string) => location.pathname === path
  // Las páginas de ajustes se marcan en el pie del sidebar (avatar y engrane).
  const isProfileActive = isActivePath('/settings/profile')
  const isLlmActive = isActivePath('/settings/llm')

  return (
    <div className="flex h-dvh overflow-hidden bg-gray-100">
      {menuOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          aria-hidden="true"
          onClick={() => setMenuOpen(false)}
        />
      )}

      {/* Sidebar: fija en desktop, panel deslizable en móvil */}
      <aside
        id="app-sidebar"
        aria-label="Navegación principal"
        className={`fixed inset-y-0 left-0 z-40 flex w-80 max-w-[85vw] flex-col border-r border-gray-200 bg-white shadow-sm transition-[transform,visibility] duration-200 md:visible md:static md:max-w-none md:translate-x-0 ${
          menuOpen ? 'visible translate-x-0' : 'invisible -translate-x-full'
        }`}
      >
        <button
          type="button"
          onClick={() => setMenuOpen(false)}
          className="absolute right-3 top-3 rounded-lg p-2 text-gray-500 hover:bg-gray-100 md:hidden"
          ref={closeMenuRef}
          aria-label="Cerrar menú"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
        <div className="flex flex-col items-center gap-2 px-4 pb-4 pt-6">
          <Link to="/projects" className="flex flex-col items-center gap-1">
            <Logo size={64} alt="" />
            <span className="font-display text-2xl text-gray-900">
              <span className="text-[#0e54ce] dark:text-blue-400">Arch</span>Agent
            </span>
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto px-4">
          {/* Primary nav */}
          <nav className="space-y-1 border-b border-gray-200 pb-3">
            <Link
              to="/projects"
              aria-current={isActivePath('/projects') ? 'page' : undefined}
              className={navItemClass(isActivePath('/projects'))}
            >
              <FolderIcon />
              <span>Mis proyectos</span>
            </Link>

            <button type="button" onClick={() => setShowCreateDialog(true)} className={navItemClass(false)}>
              <PlusIcon />
              <span>Nuevo proyecto</span>
            </button>

            <Link
              to="/patterns"
              aria-current={isActivePath('/patterns') ? 'page' : undefined}
              className={navItemClass(isActivePath('/patterns'))}
            >
              <ArchiveIcon />
              <span>Base de patrones</span>
            </Link>
          </nav>

          {/* Projects */}
          <div className="pt-3">
            <div className="mb-2 px-3">
              <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">Proyectos</span>
            </div>

            {!projectsLoaded && projects.length === 0 && <SidebarProjectsSkeleton />}

            {projectsError && (
              <div role="alert" className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
                ⚠️ {projectsError}
              </div>
            )}

            {projects.length > 0 && (
              <div className="space-y-1">
                {projects.map((p) => {
                  const isOpen = expanded === p.id
                  const isChatActive = isActivePath(`/projects/${p.id}/chat`)
                  const isDocsActive = isActivePath(`/projects/${p.id}/documents`)
                  const isProjectActive = isChatActive || isDocsActive

                  return (
                    <div key={p.id}>
                      <button
                        onClick={() => toggleExpand(p.id)}
                        aria-expanded={isOpen}
                        className={`${NAV_ITEM} ${
                          isProjectActive
                            ? 'font-semibold text-blue-700 hover:bg-gray-100'
                            : NAV_IDLE
                        }`}
                      >
                        <ClockIcon />
                        <span className="truncate flex-1">{p.name}</span>
                        <svg
                          className={`w-4 h-4 text-gray-500 transition-transform flex-shrink-0 ${
                            isOpen ? 'rotate-90' : ''
                          }`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                          aria-hidden="true"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5l7 7-7 7" />
                        </svg>
                      </button>

                      {/* Guía en el centro del ícono del proyecto (12 + 10 px); con pl de
                          10 px y px-3 del enlace, el ícono del submenú empieza en 44 px,
                          justo donde empieza el texto del proyecto (12 + 20 + 12). */}
                      {isOpen && (
                        <div className="ml-[21px] mt-0.5 space-y-0.5 border-l border-gray-200 pl-2.5">
                          <Link
                            to={`/projects/${p.id}/chat`}
                            aria-current={isChatActive ? 'page' : undefined}
                            className={subItemClass(isChatActive)}
                          >
                            <ChatIcon />
                            <span>Chat</span>
                          </Link>
                          <Link
                            to={`/projects/${p.id}/documents`}
                            aria-current={isDocsActive ? 'page' : undefined}
                            className={subItemClass(isDocsActive)}
                          >
                            <DocumentIcon />
                            <span>Documentos</span>
                          </Link>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {projectsLoaded && !projectsError && projects.length === 0 && (
              <div className="py-4 text-sm text-gray-500 text-center">
                <p className="mb-2">No hay proyectos aún</p>
                <p className="text-xs">Usa "+ Nuevo proyecto" para crear el primero</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center gap-3 border-t border-gray-200 bg-gray-50 px-4 py-3">
          <Link
            to="/settings/profile"
            aria-current={isProfileActive ? 'page' : undefined}
            className="flex min-w-0 flex-1 items-center gap-3 hover:opacity-80"
          >
            <span
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-300 text-white dark:bg-slate-600 ${
                isProfileActive ? 'ring-2 ring-blue-600 ring-offset-2 ring-offset-gray-50' : ''
              }`}
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
              </svg>
            </span>
            <span className={`truncate text-sm ${isProfileActive ? 'font-semibold text-blue-700' : 'font-medium text-gray-800'}`}>
              {user?.username || 'Usuario'}
            </span>
          </Link>
          {/* Acciones agrupadas a la derecha, todas del mismo tamaño y separación. */}
          <div className="ml-auto flex shrink-0 items-center gap-0.5">
            <ThemeToggle className="p-1.5" />
            <Link
              to="/settings/llm"
              aria-current={isLlmActive ? 'page' : undefined}
              className={`rounded-lg p-1.5 ${
                isLlmActive ? 'bg-blue-50 text-blue-700 dark:bg-blue-100' : 'text-gray-500 hover:bg-gray-200 hover:text-gray-700'
              }`}
              title="Configuración LLM"
              aria-label="Configuración LLM"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.828c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.828c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.02-.397-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.828c.292-.241.437-.613.43-.991a7.712 7.712 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </Link>
            <button
              onClick={handleLogout}
              className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
              title="Cerrar sesión"
              aria-label="Cerrar sesión"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.25 9V5.25A2.25 2.25 0 0110.5 3h6a2.25 2.25 0 012.25 2.25v13.5A2.25 2.25 0 0116.5 21h-6a2.25 2.25 0 01-2.25-2.25V15m-3 0l-3-3m0 0l3-3m-3 3H15" />
              </svg>
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Barra superior solo en móvil */}
        <header className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2 md:hidden">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            className="rounded-lg p-2 text-gray-700 hover:bg-gray-100"
            ref={openMenuRef}
            aria-label="Abrir menú"
            aria-controls="app-sidebar"
            aria-expanded={menuOpen}
          >
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <Link to="/projects" className="flex items-center gap-2">
            <Logo size={32} alt="" />
            <span className="font-display text-lg text-gray-900">
              <span className="text-[#0e54ce] dark:text-blue-400">Arch</span>Agent
            </span>
          </Link>
        </header>

        {/* Main content */}
        <main className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
          <ErrorBoundary resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <CreateProjectDialog isOpen={showCreateDialog} onClose={() => setShowCreateDialog(false)} />
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { authStore } from '../stores/authStore'
import { projectsStore } from '../stores/projectsStore'

export function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = authStore((state) => state.user)
  const logout = authStore((state) => state.logout)
  const projects = projectsStore((state) => state.projects)
  const fetchProjects = projectsStore((state) => state.fetchProjects)
  const projectsStatus = projectsStore((state) => state.status)
  const projectsError = projectsStore((state) => state.error)

  const [expanded, setExpanded] = useState<number | null>(null)

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

  const toggleExpand = (projectId: number) => {
    setExpanded((prev) => (prev === projectId ? null : projectId))
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const isActivePath = (path: string) => location.pathname === path

  return (
    <div className="min-h-screen flex flex-col bg-gray-100">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <Link to="/projects" className="text-xl font-bold text-indigo-600">
                Arch Agent
              </Link>
            </div>
            <div className="flex items-center gap-4">
              {user && <span className="text-sm text-gray-600">{user.username}</span>}
              <button
                onClick={handleLogout}
                className="text-sm text-gray-600 hover:text-gray-900 transition-colors"
              >
                Cerrar sesión
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="hidden md:flex flex-col w-72 bg-white border-r border-gray-200 shadow-sm">
          <div className="flex-1 overflow-y-auto p-4">
            {/* Header: Proyectos */}
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Proyectos</span>
            </div>

            {/* Loading */}
            {projectsStatus === 'loading' && (
              <div className="py-3 text-sm text-gray-500 italic">Cargando...</div>
            )}

            {/* Error */}
            {projectsError && (
              <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
                ⚠️ {projectsError}
              </div>
            )}

            {/* Project list */}
            {projectsStatus !== 'loading' && !projectsError && (
              <div className="space-y-1">
                {projects.map((p) => {
                  const isOpen = expanded === p.id
                  const isChatActive = isActivePath(`/projects/${p.id}/chat`)
                  const isDocsActive = isActivePath(`/projects/${p.id}/documents`)
                  const isProjectActive = isChatActive || isDocsActive

                  return (
                    <div key={p.id}>
                      {/* Project button (expandable) */}
                      <button
                        onClick={() => toggleExpand(p.id)}
                        className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-left transition-all ${
                          isProjectActive
                            ? 'bg-indigo-50 text-indigo-700 font-medium'
                            : 'text-gray-700 hover:bg-gray-100'
                        }`}
                      >
                        {/* Chevron icon */}
                        <svg
                          className={`w-4 h-4 text-gray-400 transition-transform flex-shrink-0 ${
                            isOpen ? 'rotate-90' : ''
                          }`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                        <span className="truncate flex-1">{p.name}</span>
                      </button>

                      {/* Sub-items (Chat, Documentos) */}
                      {isOpen && (
                        <div className="ml-6 mt-1 space-y-0.5 border-l-2 border-gray-200 pl-3">
                          <Link
                            to={`/projects/${p.id}/chat`}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all ${
                              isChatActive
                                ? 'bg-indigo-100 text-indigo-700 font-medium'
                                : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                            }`}
                          >
                            <span>💬</span>
                            <span>Chat</span>
                          </Link>
                          <Link
                            to={`/projects/${p.id}/documents`}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all ${
                              isDocsActive
                                ? 'bg-indigo-100 text-indigo-700 font-medium'
                                : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                            }`}
                          >
                            <span>📄</span>
                            <span>Documentos</span>
                          </Link>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {/* Empty state */}
            {projectsStatus !== 'loading' && !projectsError && projects.length === 0 && (
              <div className="py-4 text-sm text-gray-500 text-center">
                <p className="mb-2">No hay proyectos aún</p>
                <p className="text-xs">Usa el botón de abajo para crear el primero</p>
              </div>
            )}

            {/* New project button */}
            <div className="mt-4 pt-4 border-t border-gray-200">
              <Link
                to="/projects"
                className="flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors shadow-sm"
              >
                <span>+</span>
                <span>Nuevo proyecto</span>
              </Link>
            </div>
          </div>

          {/* Footer: Settings */}
          <div className="p-4 border-t border-gray-200 bg-gray-50 space-y-1">
            <Link
              to="/settings/profile"
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all ${
                isActivePath('/settings/profile')
                  ? 'bg-indigo-100 text-indigo-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              <span className="text-lg">👤</span>
              <span>Perfil</span>
            </Link>
            <Link
              to="/settings/llm"
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all ${
                isActivePath('/settings/llm')
                  ? 'bg-indigo-100 text-indigo-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              <span className="text-lg">⚙️</span>
              <span>Configuración LLM</span>
            </Link>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 p-6 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

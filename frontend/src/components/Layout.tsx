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
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <Link to="/projects" className="text-xl font-bold text-gray-900">
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
        <aside className="hidden md:block w-64 bg-gray-50 border-r border-gray-200 overflow-y-auto">
          <nav className="p-4 space-y-1">
            <div className="mb-2">
              <Link
                to="/projects"
                className="flex items-center justify-between px-3 py-2 text-sm font-semibold text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <span>Proyectos</span>
              </Link>

              <div className="mt-1 space-y-1">
                {/* Loading state */}
                {projectsStatus === 'loading' && (
                  <div className="px-3 py-2 text-xs text-gray-500">Cargando proyectos...</div>
                )}

                {/* Error state */}
                {projectsError && (
                  <div className="px-3 py-2 text-xs text-red-600 bg-red-50 rounded">
                    {projectsError}
                  </div>
                )}

                {/* Empty state */}
                {projectsStatus !== 'loading' && !projectsError && projects.length === 0 && (
                  <div className="px-3 py-2 text-xs text-gray-500">
                    No hay proyectos aún.
                    <br />
                    <Link to="/projects" className="text-blue-600 hover:underline">
                      Crear el primero
                    </Link>
                  </div>
                )}

                {/* Project list */}
                {projects.map((p) => {
                  const isOpen = expanded === p.id
                  const isChatActive = isActivePath(`/projects/${p.id}/chat`)
                  const isDocsActive = isActivePath(`/projects/${p.id}/documents`)
                  return (
                    <div key={p.id} className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                      <button
                        onClick={() => toggleExpand(p.id)}
                        className={`w-full flex items-center justify-between px-3 py-2 text-sm hover:bg-gray-50 transition-colors ${
                          isChatActive || isDocsActive ? 'bg-blue-50' : 'text-gray-800'
                        }`}
                      >
                        <span className="font-medium truncate">{p.name}</span>
                        <svg
                          className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>

                      {isOpen && (
                        <div className="border-t border-gray-200 bg-gray-50 py-1">
                          <Link
                            to={`/projects/${p.id}/chat`}
                            className={`flex items-center gap-2 px-4 py-1.5 text-sm hover:bg-gray-100 ${
                              isChatActive ? 'bg-blue-100 font-semibold text-blue-700' : 'text-gray-700'
                            }`}
                          >
                            💬 Chat
                          </Link>
                          <Link
                            to={`/projects/${p.id}/documents`}
                            className={`flex items-center gap-2 px-4 py-1.5 text-sm hover:bg-gray-100 ${
                              isDocsActive ? 'bg-blue-100 font-semibold text-blue-700' : 'text-gray-700'
                            }`}
                          >
                            📄 Documentos
                          </Link>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              <Link
                to="/projects"
                className="mt-2 flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                + Nuevo proyecto
              </Link>
            </div>

            <div className="border-t border-gray-200 pt-2 mt-2">
              <Link
                to="/settings/llm"
                className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              >
                LLM Config
              </Link>
            </div>
          </nav>
        </aside>

        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
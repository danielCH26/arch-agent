import { useEffect, useState } from 'react'
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { authStore } from '../stores/authStore'
import { projectsStore } from '../stores/projectsStore'
import { Logo } from './Logo'

export function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = authStore((state) => state.user)
  const logout = authStore((state) => state.logout)
  const projects = projectsStore((state) => state.projects)
  const currentProject = projectsStore((state) => state.currentProject)
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
  const isOnActiveSession = currentProject !== null && location.pathname.startsWith(`/projects/${currentProject.id}`)

  return (
    <div className="h-screen flex overflow-hidden bg-gray-100">
      {/* Sidebar */}
      <aside className="hidden md:flex flex-col w-80 bg-white border-r border-gray-200 shadow-sm">
        <div className="flex flex-col items-center gap-2 px-4 pb-4 pt-6">
          <Link to="/projects" className="flex flex-col items-center gap-1">
            <Logo size={64} />
            <span className="text-2xl text-gray-900">
              <span className="text-[#0e54ce]">Arq</span>Agent
            </span>
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto px-4">
          {/* Primary nav */}
          <nav className="space-y-1 border-b border-gray-200 pb-3">
            <Link
              to="/projects"
              className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-gray-800 hover:bg-gray-100"
            >
              <span className="text-lg">+</span>
              <span>Nueva sesión</span>
            </Link>

            {currentProject && (
              <Link
                to={`/projects/${currentProject.id}/chat`}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors ${
                  isOnActiveSession ? 'bg-[#0e54ce]/70 text-white' : 'text-gray-800 hover:bg-gray-100'
                }`}
              >
                <span aria-hidden="true">💬</span>
                <span className="truncate">Sesión activa</span>
              </Link>
            )}

            {/* TODO: conectar cuando se decida abordar "Base de patrones" */}
            <div
              className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2.5 text-gray-400"
              title="Próximamente"
            >
              <span aria-hidden="true">🗄️</span>
              <span>Base de patrones</span>
            </div>
          </nav>

          {/* Projects */}
          <div className="pt-3">
            <div className="mb-2 px-3">
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Proyectos</span>
            </div>

            {projectsStatus === 'loading' && (
              <div className="py-3 text-sm text-gray-500 italic">Cargando...</div>
            )}

            {projectsError && (
              <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
                ⚠️ {projectsError}
              </div>
            )}

            {projectsStatus !== 'loading' && !projectsError && (
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
                        className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-left transition-all ${
                          isProjectActive
                            ? 'bg-indigo-50 text-indigo-700 font-medium'
                            : 'text-gray-700 hover:bg-gray-100'
                        }`}
                      >
                        <span aria-hidden="true" className="shrink-0">🕐</span>
                        <span className="truncate flex-1">{p.name}</span>
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
                      </button>

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

            {projectsStatus !== 'loading' && !projectsError && projects.length === 0 && (
              <div className="py-4 text-sm text-gray-500 text-center">
                <p className="mb-2">No hay proyectos aún</p>
                <p className="text-xs">Usa "+ Nueva sesión" para crear el primero</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 border-t border-gray-200 bg-gray-50 p-4">
          <Link to="/settings/profile" className="flex items-center gap-3 min-w-0 hover:opacity-80">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-300 text-white">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
              </svg>
            </span>
            <span className="truncate text-sm text-gray-800">{user?.username || 'Usuario'}</span>
          </Link>
          <div className="flex shrink-0 items-center gap-1">
            <Link
              to="/settings/llm"
              className="rounded-lg p-2 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
              title="Configuración LLM"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.828c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.828c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.02-.397-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.828c.292-.241.437-.613.43-.991a7.712 7.712 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </Link>
            <button
              onClick={handleLogout}
              className="rounded-lg p-2 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
              title="Cerrar sesión"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.25 9V5.25A2.25 2.25 0 0110.5 3h6a2.25 2.25 0 012.25 2.25v13.5A2.25 2.25 0 0116.5 21h-6a2.25 2.25 0 01-2.25-2.25V15m-3 0l-3-3m0 0l3-3m-3 3H15" />
              </svg>
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 min-w-0 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}

import { Outlet, Link, useNavigate } from 'react-router-dom'
import { authStore } from '../stores/authStore'
import { projectsStore } from '../stores/projectsStore'

export function Layout() {
  const navigate = useNavigate()
  const user = authStore((state) => state.user)
  const logout = authStore((state) => state.logout)
  const currentProject = projectsStore((state) => state.currentProject)

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <Link to="/projects" className="text-xl font-bold text-gray-900">
                Arch Agent
              </Link>
            </div>
            <div className="flex items-center gap-4">
              {user && (
                <span className="text-sm text-gray-600">{user.username}</span>
              )}
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
        <aside className="hidden md:block w-64 bg-gray-50 border-r border-gray-200">
          <nav className="p-4 space-y-1">
            <Link
              to="/projects"
              className="block px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Proyectos
            </Link>
            {currentProject && (
              <>
                <Link
                  to={`/projects/${currentProject.id}/chat`}
                  className="block px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  Chat
                </Link>
                <Link
                  to={`/projects/${currentProject.id}/documents`}
                  className="block px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  Documentos
                </Link>
                <Link
                  to={`/projects/${currentProject.id}/settings`}
                  className="block px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  Configuración
                </Link>
              </>
            )}
            <Link
              to="/settings/llm"
              className="block px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              LLM Config
            </Link>
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

import { create } from 'zustand'
import * as projectsApi from '../api/projects'

export interface Project {
  id: number
  name: string
  description: string | null
  current_phase: string | null
  phase_ready: boolean
  created_at: string
}

interface ProjectsState {
  projects: Project[]
  currentProject: Project | null
  status: 'idle' | 'loading' | 'creating' | 'deleting' | 'error'
  error: string | null
  // true tras la primera carga (con éxito o error): distingue "cargando por
  // primera vez" de "no hay proyectos" y de "actualizando la lista".
  hasLoaded: boolean

  fetchProjects: () => Promise<void>
  createProject: (name: string, description?: string) => Promise<Project>
  deleteProject: (id: number) => Promise<void>
  setCurrentProject: (project: Project | null) => void
  clearError: () => void
}

export const projectsStore = create<ProjectsState>((set) => ({
  projects: [],
  currentProject: null,
  status: 'idle',
  error: null,
  hasLoaded: false,

  fetchProjects: async () => {
    set({ status: 'loading', error: null })
    try {
      const projects = await projectsApi.listProjects()
      set({ projects, status: 'idle', hasLoaded: true })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudieron cargar los proyectos.'
      set({ status: 'error', error: message, hasLoaded: true })
    }
  },

  createProject: async (name: string, description?: string) => {
    set({ status: 'creating', error: null })
    try {
      const newProject = await projectsApi.createProject({ name, description })
      set((state) => ({
        projects: [...state.projects, newProject],
        status: 'idle',
      }))
      return newProject
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudo crear el proyecto.'
      set({ status: 'error', error: message })
      throw error
    }
  },

  deleteProject: async (id: number) => {
    set({ status: 'deleting', error: null })
    try {
      await projectsApi.deleteProject(id)
      set((state) => ({
        projects: state.projects.filter((p) => p.id !== id),
        currentProject: state.currentProject?.id === id ? null : state.currentProject,
        status: 'idle',
      }))
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudo eliminar el proyecto.'
      set({ status: 'error', error: message })
      throw error
    }
  },

  setCurrentProject: (project: Project | null) => {
    set({ currentProject: project })
  },

  clearError: () => set({ error: null }),
}))

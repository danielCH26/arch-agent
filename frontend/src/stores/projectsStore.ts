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

  fetchProjects: async () => {
    set({ status: 'loading', error: null })
    try {
      const projects = await projectsApi.listProjects()
      set({ projects, status: 'idle' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load projects'
      set({ status: 'error', error: message })
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
      const message = error instanceof Error ? error.message : 'Failed to create project'
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
      const message = error instanceof Error ? error.message : 'Failed to delete project'
      set({ status: 'error', error: message })
      throw error
    }
  },

  setCurrentProject: (project: Project | null) => {
    set({ currentProject: project })
  },

  clearError: () => set({ error: null }),
}))

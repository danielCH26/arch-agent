import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { LoginPage } from '../LoginPage'

// Mock authStore - provide hook-based store
vi.mock('../../stores/authStore', () => ({
  authStore: vi.fn((selector) => {
    // Return mock state based on what selector is asking for
    if (selector) {
      return selector({ login: vi.fn(), status: 'idle', logout: vi.fn() })
    }
    return { login: vi.fn(), status: 'idle', logout: vi.fn() }
  }),
}))

const renderWithRouter = (ui: React.ReactElement) => {
  return render(<BrowserRouter>{ui}</BrowserRouter>)
}

describe('LoginPage', () => {
  it('renders login form', () => {
    renderWithRouter(<LoginPage />)

    expect(screen.getByRole('heading', { name: /iniciar sesión/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /iniciar sesión/i })).toBeInTheDocument()
  })

  it('has link to register page', () => {
    renderWithRouter(<LoginPage />)

    expect(screen.getByRole('link', { name: /crear una nueva cuenta/i })).toHaveAttribute('href', '/register')
  })

  it('has form with required fields', () => {
    renderWithRouter(<LoginPage />)

    const usernameInput = screen.getByLabelText(/username/i)
    const passwordInput = screen.getByLabelText(/password/i)

    expect(usernameInput).toHaveAttribute('required')
    expect(passwordInput).toHaveAttribute('required')
  })
})

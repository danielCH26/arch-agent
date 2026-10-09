// replace: no deja la página protegida en el historial.
export function redirectToLogin(): void {
  window.location.replace('/login')
}

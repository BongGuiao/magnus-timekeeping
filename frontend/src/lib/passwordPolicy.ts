export const MIN_PASSWORD_LENGTH = 8
export const MAX_PASSWORD_LENGTH = 128

export interface PasswordChangeInput {
  current: string
  next: string
  confirm: string
}

// Mirrors the server rules so mistakes are caught before a request is sent; the server stays authoritative.
export function validatePasswordChange({ current, next, confirm }: PasswordChangeInput): string | null {
  if (!current) return 'Enter your current password.'
  if (next.length < MIN_PASSWORD_LENGTH) return `The new password must be at least ${MIN_PASSWORD_LENGTH} characters long.`
  if (next.length > MAX_PASSWORD_LENGTH) return `The new password must be at most ${MAX_PASSWORD_LENGTH} characters long.`
  if (next === current) return 'The new password must be different from the current password.'
  if (next !== confirm) return 'The new password and its confirmation do not match.'
  return null
}

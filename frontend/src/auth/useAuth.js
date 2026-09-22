/**
 * The hook components use to read the signed-in user.
 *
 * Usage:
 *     const { user, logout } = useAuth()
 *
 * Wrapping `useContext` rather than exposing the context directly buys one
 * important thing: a clear error when a component is rendered outside the
 * provider. Without this check, `user` would silently be null and the bug would
 * show up much later as a confusing "cannot read property of null" somewhere
 * unrelated.
 */

import { useContext } from 'react'

import AuthContext from './AuthContext'

export default function useAuth() {
  const value = useContext(AuthContext)

  if (value === null) {
    throw new Error('useAuth must be used inside <AuthProvider>.')
  }

  return value
}

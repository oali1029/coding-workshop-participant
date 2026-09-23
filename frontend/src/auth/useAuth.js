/**
 * Read the signed-in user: `const { user, logout } = useAuth()`.
 *
 * Wrapping useContext gives a clear error when a component is rendered outside
 * the provider, instead of a null `user` surfacing much later as an unrelated
 * crash.
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

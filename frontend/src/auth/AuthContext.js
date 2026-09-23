/**
 * Context carrying the signed-in user, so components can read it without it
 * being passed down through every intervening layer.
 *
 * Kept separate from the provider component and the hook because Vite's fast
 * refresh only works cleanly when a file exports components or plain values,
 * not both.
 *
 * Provided shape: { user, status, login, register, logout }, where status is
 * 'loading' | 'authenticated' | 'anonymous'.
 */

import { createContext } from 'react'

// Null default so useAuth can detect a missing provider and say so clearly.
const AuthContext = createContext(null)

export default AuthContext

/**
 * Holds the current user and the sign-in, register and sign-out actions.
 *
 * There are three statuses rather than two because on a fresh page load we have
 * a stored token but no user details, and confirming it takes a round trip.
 * Treating that gap as "signed out" would bounce anyone refreshing a page to
 * the login screen and back — a visible flicker, or an actual lost navigation
 * on a slow connection. ProtectedRoute waits on 'loading' instead.
 *
 * Nothing here is a security control. A user can edit this code in their
 * browser and set their role to anything; the API re-checks permissions
 * server-side on every request. The point of tracking roles here is to avoid
 * showing controls that would only fail.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import AuthContext from './AuthContext'
import * as api from '../api/client'

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null)

  // With no stored token there is nothing to verify, so we can answer at once
  // and skip the round trip.
  const [status, setStatus] = useState(() => (api.getAuthToken() ? 'loading' : 'anonymous'))

  // Runs once on mount to turn a stored token back into a user. Signing in and
  // out set the state directly, so they do not go through here.
  useEffect(() => {
    if (!api.getAuthToken()) {
      return undefined
    }

    // Guards against writing state if the component unmounts mid-request.
    let ignore = false

    async function restoreSession() {
      try {
        const { user: currentUser } = await api.getMe()
        if (!ignore) {
          setUser(currentUser)
          setStatus('authenticated')
        }
      } catch {
        // The token is expired, tampered with, or the account was deactivated;
        // client.js has already cleared it on a 401. No error is surfaced
        // because from the user's perspective they are simply signed out.
        if (!ignore) {
          setUser(null)
          setStatus('anonymous')
        }
      }
    }

    restoreSession()

    return () => {
      ignore = true
    }
  }, [])

  // Errors are deliberately not caught: the calling form needs to know the
  // attempt failed so it can show the message beside the fields.
  const login = useCallback(async (email, password) => {
    const { token, user: signedInUser } = await api.login({ email, password })

    // Token first: once status flips, protected pages render and immediately
    // make API calls that need it.
    api.setAuthToken(token)
    setUser(signedInUser)
    setStatus('authenticated')
  }, [])

  const register = useCallback(async ({ fullName, email, password }) => {
    const { token, user: newUser } = await api.register({ fullName, email, password })

    api.setAuthToken(token)
    setUser(newUser)
    setStatus('authenticated')
  }, [])

  /**
   * Sign out by discarding the token. There is no server call because the
   * backend keeps no session — tokens are stateless and signed.
   *
   * Known limitation: a copied token stays valid until it expires. Real
   * revocation needs a server-side blocklist, which reintroduces the shared
   * state stateless tokens exist to avoid; the 12-hour lifetime is the
   * mitigation.
   */
  const logout = useCallback(() => {
    api.setAuthToken(null)
    setUser(null)
    setStatus('anonymous')
  }, [])

  // Memoised so consumers do not re-render on every parent render.
  const value = useMemo(
    () => ({ user, status, login, register, logout }),
    [user, status, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

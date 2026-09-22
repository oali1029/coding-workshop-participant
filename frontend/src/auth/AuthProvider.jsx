/**
 * =============================================================================
 * WHO IS SIGNED IN — the single source of truth for the front end
 * =============================================================================
 * This component wraps the whole application and holds the current user. Any
 * component below it can read that with the `useAuth()` hook.
 *
 * It owns three things:
 *   1. Restoring a session when the page loads.
 *   2. The login, register and logout actions.
 *   3. The `status` value that tells the rest of the app what to render.
 *
 * =============================================================================
 * WHY THERE IS A 'loading' STATUS
 * =============================================================================
 * On a fresh page load we have a token in browser storage but no user details —
 * the token is just a signed string, and we deliberately do not trust whatever
 * a browser might have stored next to it. So we ask the backend who it belongs
 * to, which takes a network round trip.
 *
 * During that gap we genuinely do not know whether the person is signed in. If
 * we guessed "signed out", anyone refreshing a page would be bounced to the
 * login screen for a moment and then bounced back — a visible flicker, and on a
 * slow connection an actual redirect away from the page they wanted.
 *
 * So there are three states, not two, and `ProtectedRoute` waits rather than
 * redirecting while the answer is unknown.
 *
 * =============================================================================
 * THE FRONT END IS NOT A SECURITY BOUNDARY
 * =============================================================================
 * Everything here — the stored user, the role, the protected routes — is a
 * convenience for the person using the app. None of it stops anyone. A user can
 * edit the JavaScript in their browser, change `role` to FACILITY_ADMIN, and
 * make the interface show every administrator button.
 *
 * That does not matter, because those buttons call an API that checks
 * permissions again on the server, where the user cannot reach. The backend is
 * the only real boundary; see backend/v1/app/router.py. What we do here is
 * avoid showing people controls that would only fail.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import AuthContext from './AuthContext'
import * as api from '../api/client'

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null)

  // 'loading' while we check a stored token, then 'authenticated' or
  // 'anonymous'. Starting at 'loading' is only correct when a token exists;
  // with no token there is nothing to check, so we can answer immediately and
  // skip the round trip entirely.
  const [status, setStatus] = useState(() =>
    api.getAuthToken() ? 'loading' : 'anonymous',
  )

  /**
   * On first load, turn any stored token back into a user.
   *
   * The `ignore` flag is a cleanup guard: if this component is removed while
   * the request is still in flight, the late response must not write to state
   * that no longer exists.
   */
  useEffect(() => {
    // No token means nothing to restore, and `status` is already 'anonymous'.
    if (!api.getAuthToken()) {
      return undefined
    }

    let ignore = false

    async function restoreSession() {
      try {
        const { user: currentUser } = await api.getMe()
        if (!ignore) {
          setUser(currentUser)
          setStatus('authenticated')
        }
      } catch {
        // Any failure here means the token is unusable — expired, tampered
        // with, or the account was deactivated. api/client.js has already
        // cleared it on a 401. We do not surface an error: from the person's
        // point of view they are simply signed out, which the login screen
        // already communicates.
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

  /**
   * Sign in with an email and password.
   *
   * Deliberately does NOT catch errors. The calling form needs to know the
   * attempt failed so it can show the message next to the fields, and
   * swallowing the error here would leave the user staring at a form that
   * silently did nothing.
   */
  const login = useCallback(async (email, password) => {
    const { token, user: signedInUser } = await api.login({ email, password })

    // Store the token BEFORE updating React state. The moment `status` becomes
    // 'authenticated', protected pages render and immediately start making API
    // calls — and those calls need the token to already be in place.
    api.setAuthToken(token)
    setUser(signedInUser)
    setStatus('authenticated')
  }, [])

  /**
   * Create an account and sign straight in.
   *
   * The backend returns a token alongside the new user, so there is no need to
   * make the person type the password again one second after choosing it.
   */
  const register = useCallback(async ({ fullName, email, password }) => {
    const { token, user: newUser } = await api.register({ fullName, email, password })

    api.setAuthToken(token)
    setUser(newUser)
    setStatus('authenticated')
  }, [])

  /**
   * Sign out.
   *
   * There is no server call, because there is no server-side session to end.
   * The backend issues stateless signed tokens (see the JWT explanation in
   * backend/v1/app/security.py), so signing out means the browser forgetting
   * its token.
   *
   * HONEST LIMITATION: the discarded token remains cryptographically valid
   * until it expires, so anyone who had already copied it could keep using it
   * for up to twelve hours. Properly revoking a token needs a server-side
   * blocklist, which reintroduces exactly the shared state that stateless
   * tokens were chosen to avoid. The short lifetime is the mitigation.
   */
  const logout = useCallback(() => {
    api.setAuthToken(null)
    setUser(null)
    setStatus('anonymous')
  }, [])

  // `useMemo` keeps this object identical between renders unless something in
  // it actually changed. Without it, a brand-new object would be created on
  // every render, and every component reading the context would re-render too,
  // whether or not the user had changed.
  const value = useMemo(
    () => ({ user, status, login, register, logout }),
    [user, status, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

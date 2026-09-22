/**
 * The React "context" object that carries the signed-in user around the app.
 *
 * A context is React's way of making a value available to every component in a
 * tree without passing it down manually through each layer. Without it, the
 * current user would have to be handed from App to the layout, from the layout
 * to the page, from the page to the header, and so on — a pattern known as
 * "prop drilling" that makes every component in the chain care about data it
 * does not itself use.
 *
 * This lives in its own file, separate from the provider component and the
 * hook, for a practical reason: Vite's fast-refresh (which live-updates the
 * page as you edit) works reliably only when a file exports either components
 * or plain values, not a mixture. Splitting them keeps editing smooth and keeps
 * the project's linter happy.
 */

import { createContext } from 'react'

/**
 * The shape provided by AuthProvider:
 *
 *   user       {id, email, full_name, role} while signed in, otherwise null
 *   status     'loading' | 'authenticated' | 'anonymous'
 *   login      (email, password)      => Promise<void>
 *   register   ({fullName, email, password}) => Promise<void>
 *   logout     ()                     => void
 *
 * The default value is only used if a component reads the context without a
 * provider above it. `useAuth` turns that mistake into a clear error instead.
 */
const AuthContext = createContext(null)

export default AuthContext

/**
 * A route wrapper that only renders its children for a signed-in user.
 *
 * Used in App.jsx like this:
 *
 *     <Route element={<ProtectedRoute />}>
 *       <Route path="/" element={<HomePage />} />
 *     </Route>
 *
 * `<Outlet />` is where React Router renders whichever child route matched.
 *
 * WHAT THIS IS AND IS NOT FOR
 * It stops someone seeing a broken, empty page by typing a URL while signed
 * out, and sends them somewhere useful instead. It is NOT a security control —
 * the data those pages display comes from an API that checks the token itself.
 * Anyone can edit the JavaScript to bypass this; nobody can bypass the backend.
 */

import { Box, CircularProgress } from '@mui/material'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import useAuth from './useAuth'

export default function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  // Still checking a stored token. Waiting here rather than redirecting is what
  // prevents a refresh from flashing the login screen before landing back on
  // the page the user was already on. See the explanation in AuthProvider.jsx.
  if (status === 'loading') {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (status === 'anonymous') {
    // `state={{ from: location }}` remembers where they were trying to go, so
    // LoginPage can send them straight there after a successful sign-in rather
    // than dumping everyone on the home page.
    //
    // `replace` swaps this entry in the browser history instead of adding one,
    // so pressing Back does not return to a page they cannot view.
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <Outlet />
}

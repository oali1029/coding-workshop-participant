/**
 * Renders child routes only for a signed-in user, redirecting to /login
 * otherwise.
 *
 * A usability guard, not a security control — it stops someone landing on an
 * empty broken page by typing a URL. The data those pages show comes from an
 * API that verifies the token itself.
 */

import { Box, CircularProgress } from '@mui/material'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import useAuth from './useAuth'

export default function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  // Waiting rather than redirecting is what stops a refresh flashing the login
  // screen before returning to the page the user was already on.
  if (status === 'loading') {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (status === 'anonymous') {
    // `from` lets LoginPage return the user to where they were heading.
    // `replace` keeps an unviewable page out of history.
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <Outlet />
}

/**
 * Renders child routes only for a Facility Admin.
 *
 * Wraps ProtectedRoute's job and adds a role check, so an employee who types
 * an /admin URL lands somewhere useful instead of on a page that would only
 * fill with 403 errors.
 *
 * Like ProtectedRoute, this is a usability guard rather than a security
 * boundary — the admin endpoints check the caller's role themselves, and that
 * check is the one that cannot be bypassed.
 */

import { Box, CircularProgress } from '@mui/material'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import useAuth from './useAuth'
import { ROLE_FACILITY_ADMIN } from '../roles'

export default function AdminRoute() {
  const { status, user } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (status === 'anonymous') {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  // Signed in but not an admin: send them home rather than to the login page,
  // which would wrongly imply their session had expired.
  if (user.role !== ROLE_FACILITY_ADMIN) {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}

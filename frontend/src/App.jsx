/**
 * Root component: installs the theme, the auth provider and the router, then
 * declares which URL shows which page. All content lives in src/pages/.
 *
 * AuthProvider sits inside BrowserRouter because its children use navigation
 * hooks, which only work beneath a router.
 *
 * Login and register are public out of necessity — there would otherwise be no
 * way in. Everything else sits behind ProtectedRoute, which is a usability
 * guard rather than a security boundary; the API checks the token itself.
 */

import { CssBaseline, ThemeProvider } from '@mui/material'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import AdminRoute from './auth/AdminRoute'
import AuthProvider from './auth/AuthProvider'
import ProtectedRoute from './auth/ProtectedRoute'
import AppLayout from './layout/AppLayout'
import AdminIncidentsPage from './pages/AdminIncidentsPage'
import AdminUsersPage from './pages/AdminUsersPage'
import AssignedIncidentsPage from './pages/AssignedIncidentsPage'
import HomePage from './pages/HomePage'
import IncidentDetailPage from './pages/IncidentDetailPage'
import LoginPage from './pages/LoginPage'
import MyIncidentsPage from './pages/MyIncidentsPage'
import RegisterPage from './pages/RegisterPage'
import ReportIncidentPage from './pages/ReportIncidentPage'
import StatusPage from './pages/StatusPage'
import theme from './theme'

function App() {
  return (
    <ThemeProvider theme={theme}>
      {/* Normalises browser default styling and applies the theme background. */}
      <CssBaseline />
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />

            {/* Routes without a path of their own wrap their children without
                adding a URL segment: ProtectedRoute decides whether to render,
                AppLayout supplies the surrounding chrome. */}
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/incidents" element={<MyIncidentsPage />} />
                {/* Declared before "/incidents/:id" so "new" is treated as a
                    page rather than an incident id. */}
                <Route path="/incidents/new" element={<ReportIncidentPage />} />
                <Route path="/incidents/:id" element={<IncidentDetailPage />} />
                {/* Engineers only. The API refuses everyone else; the page
                    simply shows the resulting error rather than guarding, since
                    only engineers ever see the nav link. */}
                <Route path="/assigned" element={<AssignedIncidentsPage />} />
                <Route path="/status" element={<StatusPage />} />

                {/* Facility Admin only. Nested inside AppLayout so these
                    pages keep the same chrome as everything else. */}
                <Route element={<AdminRoute />}>
                  <Route path="/admin/incidents" element={<AdminIncidentsPage />} />
                  <Route path="/admin/users" element={<AdminUsersPage />} />
                </Route>
              </Route>
            </Route>

            {/* Unknown URLs go home rather than showing a blank page. */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  )
}

export default App

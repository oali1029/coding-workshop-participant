/**
 * =============================================================================
 * THE ROOT COMPONENT — global setup and the URL map
 * =============================================================================
 * `src/main.jsx` renders this, and everything the user sees hangs below it.
 *
 * It does two jobs and no more:
 *   1. Installs the three things every page depends on — the visual theme, the
 *      signed-in user, and the router.
 *   2. Declares which URL shows which page.
 *
 * All actual content lives in `src/pages/`. Keeping this file to structure
 * alone means the application's shape can be understood by reading one screen
 * of code.
 *
 * =============================================================================
 * WHY THE PROVIDERS ARE NESTED IN THIS ORDER
 * =============================================================================
 *     ThemeProvider          colours and fonts, needed by every component
 *       CssBaseline          normalises browser default styling
 *         BrowserRouter      makes the current URL available
 *           AuthProvider     needs the router, because signing out navigates
 *             Routes         the URL map itself
 *
 * AuthProvider sits INSIDE BrowserRouter because its children use navigation
 * hooks, and those only work beneath a router.
 *
 * =============================================================================
 * PUBLIC VERSUS PROTECTED ROUTES
 * =============================================================================
 * Login and register must be reachable while signed out — otherwise there
 * would be no way in. Everything else is wrapped in `<ProtectedRoute>`, which
 * redirects anonymous visitors to the login screen.
 *
 * Worth repeating: that wrapper is a convenience, not a security control. It
 * stops someone landing on an empty broken page by typing a URL. The data those
 * pages show comes from an API that verifies the token itself, and that check
 * is the one that cannot be bypassed.
 */

import { CssBaseline, ThemeProvider } from '@mui/material'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import AuthProvider from './auth/AuthProvider'
import ProtectedRoute from './auth/ProtectedRoute'
import AppLayout from './layout/AppLayout'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import StatusPage from './pages/StatusPage'
import theme from './theme'

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public — reachable without signing in. */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />

            {/* Protected. A route with no `path` of its own is a "layout
                route": it wraps its children without adding a URL segment. Here
                ProtectedRoute decides whether to render at all, and AppLayout
                supplies the toolbar the pages appear inside. */}
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/status" element={<StatusPage />} />
              </Route>
            </Route>

            {/* Anything unrecognised goes home rather than showing a blank
                page. `replace` keeps the bad URL out of browser history, so
                pressing Back does not return to it. */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  )
}

export default App

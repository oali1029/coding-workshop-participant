/**
 * =============================================================================
 * THE ROOT COMPONENT OF THE REACT APPLICATION
 * =============================================================================
 * This is the top of the user interface. `src/main.jsx` renders this component
 * into the page, and everything the user ever sees hangs below it.
 *
 * Right now it does one thing: ask the backend whether it is healthy, and show
 * the answer. That is the visible half of "Slice 0", the walking skeleton.
 *
 * =============================================================================
 * WHY THE FIRST SCREEN IS A STATUS PAGE
 * =============================================================================
 * It proves the entire chain works before any real feature is built:
 *
 *   React (this file)
 *     -> src/api/client.js builds the URL
 *       -> CloudFront on AWS, or the local proxy on a laptop
 *         -> the Lambda entry point (backend/v1/function.py)
 *           -> the router (backend/v1/app/router.py)
 *             -> the health handler (backend/v1/app/domains/health.py)
 *               -> PostgreSQL
 *             ...and all the way back to the screen.
 *
 * If this page shows a green result on the deployed site, every one of those
 * links is working. Incidents, users and facilities are then "just" more
 * handlers added along the same proven path.
 *
 * =============================================================================
 * THE THREE STATES OF ANY SCREEN THAT LOADS DATA
 * =============================================================================
 * Network calls take time and can fail. A screen that ignores this shows a
 * blank panel while waiting, and nothing at all when something breaks. Every
 * data-loading screen in this project therefore handles three cases explicitly:
 *
 *   LOADING   the request is in flight        -> show a spinner
 *   ERROR     the request failed              -> explain what went wrong
 *   SUCCESS   the data arrived                -> show it
 *
 * The `status` variable below tracks which of the three we are in.
 */

import { useCallback, useEffect, useState } from 'react'
import { useMediaQuery } from 'react-responsive'
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  CssBaseline,
  Paper,
  Stack,
  ThemeProvider,
  Toolbar,
  Typography,
  createTheme,
} from '@mui/material'

import { apiBaseUrl, getHealth } from './api/client'

/**
 * The application's visual settings: colours, fonts and spacing.
 *
 * Defining this once and wrapping the app in a ThemeProvider is what makes
 * every button, heading and card look like part of the same product. Individual
 * components then read from the theme instead of hard-coding colours, so a
 * future rebrand is a change in one place.
 */
const theme = createTheme({
  palette: {
    primary: { main: '#00539b' }, // a corporate blue, suitable for ACME
    background: { default: '#f4f6f8' },
  },
  shape: { borderRadius: 8 },
})

/**
 * One labelled line of information, e.g. "Environment: aws".
 *
 * Extracted into its own small component because it is used several times
 * below. Reusing it rather than copying the markup is what keeps the rows
 * visually identical, and is the habit that later prevents large duplicated
 * blocks across pages.
 *
 * `label` and `children` are "props" — the inputs a React component receives
 * from its parent. `children` is the special prop holding whatever was placed
 * between the opening and closing tags.
 */
function DetailRow({ label, children }) {
  return (
    <Stack
      // On a narrow phone, stack the label above the value so long text is not
      // squeezed into a sliver. On wider screens, place them side by side.
      // This is the responsive design requirement in practice, not just as CSS.
      direction={{ xs: 'column', sm: 'row' }}
      spacing={{ xs: 0.5, sm: 2 }}
      sx={{ py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
        {label}
      </Typography>
      {/* `wordBreak` stops the long PostgreSQL version string from pushing the
          layout wider than the phone screen and creating sideways scrolling. */}
      <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
        {children}
      </Typography>
    </Stack>
  )
}

function App() {
  /**
   * `useState` gives a component memory. Without it, every re-render would
   * start from scratch and the fetched data would be lost.
   *
   * Each call returns the current value and a function to change it. Calling
   * that function tells React the value changed, and React re-runs this
   * component to update what is on screen.
   */
  const [status, setStatus] = useState('loading') // 'loading' | 'error' | 'success'
  const [health, setHealth] = useState(null) // the data, once it arrives
  const [errorMessage, setErrorMessage] = useState('')

  // True when the screen is phone-sized. `react-responsive` is used here rather
  // than a CSS media query because we are changing BEHAVIOUR (which text to
  // render), not merely appearance. Purely visual changes stay in CSS via the
  // `sx` breakpoints seen in DetailRow above.
  const isCompact = useMediaQuery({ maxWidth: 600 })

  // Incremented by the "Try again" button. The effect below lists it as a
  // dependency, so changing it is what causes the request to run again. This
  // indirection — rather than calling the fetch function from the button — is
  // what keeps all network access inside the effect, where React can manage
  // its lifecycle.
  const [reloadToken, setReloadToken] = useState(0)

  /**
   * `useEffect` runs code that reaches outside React — here, a network call.
   *
   * The fetch cannot go directly in the component body: that code runs on
   * every render, so each response would trigger another render and another
   * fetch, looping forever.
   *
   * The second argument is the dependency list. React re-runs the effect
   * whenever something in it changes. `reloadToken` starts at 0, so this runs
   * once when the page opens, and again each time the retry button bumps it.
   *
   * THE `ignore` FLAG
   * -----------------
   * The function returned at the end is a "cleanup" function. React calls it
   * when the component is removed from the screen, or before re-running the
   * effect.
   *
   * It guards against a race: if the user leaves this page while the request
   * is still travelling, the response arrives for a component that no longer
   * exists, and calling setState on it would be a wasted update on stale data.
   * Setting `ignore = true` makes the late response harmless. The request
   * itself cannot be un-sent, but we can decline to act on its result.
   */
  useEffect(() => {
    let ignore = false

    async function loadHealth() {
      try {
        const data = await getHealth()
        if (!ignore) {
          setHealth(data)
          setStatus('success')
        }
      } catch (error) {
        // client.js has already converted this into a readable sentence, so
        // it can be shown to the user directly.
        if (!ignore) {
          setErrorMessage(error.message)
          setStatus('error')
        }
      }
    }

    loadHealth()

    return () => {
      ignore = true
    }
  }, [reloadToken])

  /**
   * Handler for the "Try again" button.
   *
   * Switches back to the loading state so the user gets immediate feedback
   * that their click registered, then bumps the token to re-trigger the effect
   * above. Setting state directly is fine here because an event handler runs
   * in response to a user action, not as part of rendering.
   */
  const retry = useCallback(() => {
    setStatus('loading')
    setReloadToken((token) => token + 1)
  }, [])

  return (
    // ThemeProvider makes the theme available to every component below it.
    <ThemeProvider theme={theme}>
      {/* CssBaseline normalises browser default styles, so the app looks the
          same in Chrome, Safari and Firefox. It also applies the theme's
          background colour to the page. */}
      <CssBaseline />

      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" component="h1" sx={{ flexGrow: 1 }}>
            {/* Shorten the title on a phone, where the full name would wrap
                awkwardly against the toolbar height. */}
            {isCompact ? 'ACME Incidents' : 'ACME Facility Incident Management'}
          </Typography>
        </Toolbar>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 4 }}>
        <Typography variant="h5" component="h2" gutterBottom>
          System status
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          This page confirms that the web application can reach its backend
          service and that the backend can reach its database.
        </Typography>

        <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
          {/*
            Below is "conditional rendering": JavaScript decides which elements
            to produce. `&&` renders the right-hand side only when the left side
            is true, so exactly one of these three blocks appears at a time.
          */}

          {status === 'loading' && (
            <Stack alignItems="center" spacing={2} sx={{ py: 4 }}>
              <CircularProgress />
              <Typography variant="body2" color="text.secondary">
                Contacting the backend service...
              </Typography>
            </Stack>
          )}

          {status === 'error' && (
            <Stack spacing={2}>
              <Alert severity="error">
                <strong>Could not reach the backend.</strong> {errorMessage}
              </Alert>
              <Typography variant="caption" color="text.secondary">
                Tried: {apiBaseUrl}/health
              </Typography>
              <Box>
                {/* Letting the user retry avoids a full page reload, and covers
                    the common local case where the backend is simply still
                    starting up. */}
                <Button variant="contained" onClick={retry}>
                  Try again
                </Button>
              </Box>
            </Stack>
          )}

          {status === 'success' && health && (
            <Stack spacing={0}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                <Chip label="Operational" color="success" size="small" />
                <Typography variant="body2" color="text.secondary">
                  All checks passed
                </Typography>
              </Stack>

              {/* `environment` tells us whether this page is talking to the
                  real cloud deployment or to the local emulator — the quickest
                  way to confirm a deployment actually took effect. */}
              <DetailRow label="Environment">
                {health.environment === 'aws' ? 'AWS (deployed)' : 'Local development'}
              </DetailRow>

              {/* Proof the Lambda genuinely queried PostgreSQL. On AWS this
                  string mentions Aurora, Amazon's managed PostgreSQL. */}
              <DetailRow label="Database">{health.database}</DetailRow>

              {/* Which database migration has been applied. If a deployment
                  failed to update the schema, this number would lag behind. */}
              <DetailRow label="Schema version">{health.schema_version}</DetailRow>

              <DetailRow label="API address">{apiBaseUrl}</DetailRow>
            </Stack>
          )}
        </Paper>

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 3 }}>
          Slice 0 — walking skeleton. Incident reporting, facilities and user
          roles are added in later slices.
        </Typography>
      </Container>
    </ThemeProvider>
  )
}

export default App

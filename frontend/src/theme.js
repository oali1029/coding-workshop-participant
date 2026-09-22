/**
 * The application's visual settings: colours, shape and typography.
 *
 * Extracted into its own file so that every page shares one definition. A
 * component that needs a colour reads it from the theme rather than writing a
 * hex code inline, which is what keeps the product looking like one product
 * and makes a future rebrand a single-file change.
 *
 * Material UI reads this through the `<ThemeProvider>` wrapper in App.jsx.
 */

import { createTheme } from '@mui/material'

const theme = createTheme({
  palette: {
    primary: { main: '#00539b' }, // corporate blue
    background: { default: '#f4f6f8' },
  },
  shape: { borderRadius: 8 },
  typography: {
    // Slightly tighter headings than the MUI default, which suits an
    // information-dense internal tool better than a marketing site.
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
})

export default theme

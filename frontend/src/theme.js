/**
 * Shared visual settings. Components read colours from the theme rather than
 * hardcoding them, so the product looks consistent and a rebrand is one edit.
 */

import { createTheme } from '@mui/material'

const theme = createTheme({
  palette: {
    primary: { main: '#00539b' },
    background: { default: '#f4f6f8' },
  },
  shape: { borderRadius: 8 },
  typography: {
    // Tighter than MUI's defaults, which suits a dense internal tool.
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
})

export default theme

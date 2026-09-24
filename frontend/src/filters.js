/**
 * Shared state and constants for the incident search/filter bar.
 *
 * Separate from the component because Vite's fast refresh expects a file to
 * export components or plain values, not both — the same reason roles.js and
 * incidents.js exist.
 */

import { useEffect, useState } from 'react'

// Long enough to cover typing, short enough to feel immediate.
export const SEARCH_DEBOUNCE_MS = 300

// The backend understands this exact word — see build_filters in
// backend/v1/app/domains/incidents.py.
export const UNASSIGNED = 'unassigned'

export const NO_FILTERS = {
  q: '',
  status: '',
  category: '',
  priority: '',
  building: '',
  assignee: '',
}

/**
 * Debounce the search box: returns the value to actually send to the API, so
 * typing a word fires one request rather than one per keystroke.
 */
export function useDebouncedSearch(search) {
  const [applied, setApplied] = useState(search)

  useEffect(() => {
    const timer = setTimeout(() => setApplied(search), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search])

  return applied
}

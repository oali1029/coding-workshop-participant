/**
 * Display labels and colours for incident categories, priorities and statuses.
 *
 * The keys must match the CHECK constraints in migration 3 and the tuples in
 * backend/v1/app/domains/incidents.py — those values are what the API accepts
 * and what the database stores. Only the display text and colours here are
 * free to change.
 *
 * Kept out of any component file because Vite's fast refresh expects a module
 * to export components or plain values, not both.
 */

export const CATEGORIES = [
  { value: 'TECHNOLOGY', label: 'Technology' },
  { value: 'ELECTRICAL', label: 'Electrical' },
  { value: 'PLUMBING', label: 'Plumbing' },
  { value: 'HVAC', label: 'Heating / Cooling' },
  { value: 'FURNITURE', label: 'Furniture' },
  { value: 'OTHER', label: 'Other' },
]

export const PRIORITIES = [
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
]

export const DEFAULT_PRIORITY = 'MEDIUM'

// MUI Chip colours. Statuses beyond OPEN are unreachable in this slice, but a
// later slice moves incidents through them and the list will render whatever
// the API returns, so they are all mapped now.
const STATUS_DISPLAY = {
  OPEN: { label: 'Open', color: 'info' },
  IN_PROGRESS: { label: 'In Progress', color: 'primary' },
  BLOCKED: { label: 'Blocked', color: 'error' },
  RESOLVED: { label: 'Resolved', color: 'success' },
  CLOSED: { label: 'Closed', color: 'default' },
}

const PRIORITY_DISPLAY = {
  LOW: { label: 'Low', color: 'default' },
  MEDIUM: { label: 'Medium', color: 'warning' },
  HIGH: { label: 'High', color: 'error' },
}

/** Falls back to the raw value so an unmapped code still shows something. */
export function statusDisplay(status) {
  return STATUS_DISPLAY[status] || { label: status, color: 'default' }
}

export function priorityDisplay(priority) {
  return PRIORITY_DISPLAY[priority] || { label: priority, color: 'default' }
}

export function categoryLabel(category) {
  return CATEGORIES.find((entry) => entry.value === category)?.label || category
}

/** Render a timestamp in the reader's local format, e.g. "22 Sep 2026, 14:03". */
export function formatDateTime(value) {
  if (!value) {
    return '—'
  }
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

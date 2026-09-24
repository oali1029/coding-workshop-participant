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
// `short` is the plain status name, for places with no room for the fuller
// wording — the analytics summary cards. Everywhere else uses `label`.
const STATUS_DISPLAY = {
  OPEN: { label: 'Open', short: 'Open', color: 'info' },
  IN_PROGRESS: { label: 'In Progress', short: 'In Progress', color: 'primary' },
  BLOCKED: { label: 'Blocked', short: 'Blocked', color: 'error' },
  // The stored value stays RESOLVED; only the wording changes. It means the
  // engineer believes the work is done and has submitted it for admin review —
  // not that the incident is finished. CLOSED is the finished state.
  RESOLVED: { label: 'Resolved — awaiting review', short: 'Resolved', color: 'warning' },
  CLOSED: { label: 'Closed', short: 'Closed', color: 'success' },
}

// Workflow order, used by the dashboards and analytics so their cards and rows
// read as a pipeline rather than in whatever order the API serialised them.
export const STATUS_ORDER = ['OPEN', 'IN_PROGRESS', 'BLOCKED', 'RESOLVED', 'CLOSED']

// The happy path through the workflow, for the stepper on the detail page.
// BLOCKED is deliberately absent: it is a state work can fall into at any point,
// not a step along the way, so it is rendered as an error on the current step.
export const WORKFLOW_ORDER = ['OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED']

export const STATUS_BLOCKED = 'BLOCKED'
export const STATUS_CLOSED = 'CLOSED'

// Which statuses each role may set. Mirrors ENGINEER_SETTABLE_STATUSES and
// ADMIN_SETTABLE_STATUSES in backend/v1/app/domains/incidents.py — the backend
// re-checks, so this only decides what the dropdown offers.
export const ENGINEER_SETTABLE = ['OPEN', 'IN_PROGRESS', 'BLOCKED', 'RESOLVED']
export const ADMIN_SETTABLE = ['OPEN', 'IN_PROGRESS', 'BLOCKED', 'RESOLVED', 'CLOSED']

const PRIORITY_DISPLAY = {
  LOW: { label: 'Low', color: 'default' },
  MEDIUM: { label: 'Medium', color: 'warning' },
  HIGH: { label: 'High', color: 'error' },
}

/** Falls back to the raw value so an unmapped code still shows something. */
export function statusDisplay(status) {
  return STATUS_DISPLAY[status] || { label: status, short: status, color: 'default' }
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

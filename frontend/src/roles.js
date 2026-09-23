/**
 * Display names for the three application roles.
 *
 * The keys must match backend/v1/app/security.py exactly — those values are
 * compared in Python, enforced by a SQL CHECK constraint, and carried in login
 * tokens. Only the display text on the right is free to change.
 *
 * Separate from any component file because Vite's fast refresh expects a file
 * to export components or plain values, not both.
 */

export const ROLE_LABELS = {
  EMPLOYEE: 'Employee',
  ENGINEER: 'Engineer',
  FACILITY_ADMIN: 'Facility Admin',
}

/** Falls back to the raw value so an unmapped role still shows something. */
export function roleLabel(role) {
  return ROLE_LABELS[role] || role
}

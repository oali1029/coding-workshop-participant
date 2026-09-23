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

export const ROLE_EMPLOYEE = 'EMPLOYEE'
export const ROLE_ENGINEER = 'ENGINEER'
export const ROLE_FACILITY_ADMIN = 'FACILITY_ADMIN'

export const ROLE_LABELS = {
  [ROLE_EMPLOYEE]: 'Employee',
  [ROLE_ENGINEER]: 'Engineer',
  [ROLE_FACILITY_ADMIN]: 'Facility Admin',
}

// The roles an admin may assign. FACILITY_ADMIN is absent to match the backend,
// which rejects it — administrator accounts are managed separately.
export const MANAGEABLE_ROLES = [ROLE_EMPLOYEE, ROLE_ENGINEER]

/** Falls back to the raw value so an unmapped role still shows something. */
export function roleLabel(role) {
  return ROLE_LABELS[role] || role
}

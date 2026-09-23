/**
 * The incident workflow, drawn as a stepper.
 *
 * Open → In Progress → Resolved → Closed is the happy path. BLOCKED is not a
 * step: work can fall into it at any point and then continue, so it is shown as
 * an error marker on the step the incident is currently sitting at.
 *
 * Read-only. Changing status is done through the control beside it, which knows
 * what the signed-in role is allowed to set.
 */

import { Step, StepLabel, Stepper, Typography } from '@mui/material'

import { STATUS_BLOCKED, WORKFLOW_ORDER, statusDisplay } from '../incidents'

export default function WorkflowStepper({ status }) {
  const isBlocked = status === STATUS_BLOCKED

  // A blocked incident still occupies a position in the workflow, but the status
  // value no longer tells us which. Showing it at In Progress is honest: work
  // has started and has stalled.
  const effectiveStatus = isBlocked ? 'IN_PROGRESS' : status
  const activeStep = Math.max(WORKFLOW_ORDER.indexOf(effectiveStatus), 0)

  return (
    <>
      <Stepper
        activeStep={activeStep}
        alternativeLabel
        sx={{ mt: 1, mb: isBlocked ? 1 : 0 }}
      >
        {WORKFLOW_ORDER.map((step, index) => (
          <Step key={step} completed={index < activeStep}>
            <StepLabel error={isBlocked && index === activeStep}>
              {statusDisplay(step).label}
            </StepLabel>
          </Step>
        ))}
      </Stepper>

      {isBlocked && (
        <Typography variant="body2" color="error" align="center">
          Blocked — work cannot currently proceed.
        </Typography>
      )}
    </>
  )
}

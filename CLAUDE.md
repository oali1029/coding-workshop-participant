# Project Development Guidelines

## Implementation Style

This is a two-day workshop MVP. Prefer the simplest reliable implementation that satisfies the requirements.

- Use straightforward, conventional solutions.
- Avoid over-engineering, unnecessary abstractions, and premature optimization.
- Reuse the existing architecture instead of introducing new layers without a clear reason.
- Prefer explicit, easy-to-follow code for CRUD and business features.
- Keep request flows easy to trace from frontend → API → backend → PostgreSQL.
- Do not sacrifice important security, data integrity, tests, or reliable AWS deployment for simplicity.
- If a substantially more complex approach is necessary, explain why before implementing it.
- The code should be something I can understand and explain during a technical presentation.

## Commenting Style

Use an "educational professional" commenting style.

- Explain WHY behind non-obvious architectural, security, database, AWS, concurrency, authentication, authorization, and deployment decisions.
- Briefly explain complex or surprising behavior.
- Keep enough explanation that I can learn the code and present it to another engineer.
- Use concise docstrings where useful.
- Do not narrate straightforward code line-by-line.
- Do not explain basic programming syntax or common concepts.
- Avoid tutorial-style essays, banner comments, and Step 1 / Step 2 / Step 3 narration.
- Avoid repeating the same explanation in multiple files.
- Prefer clear naming and structure over excessive comments.

## Development Workflow

We are developing in vertical slices.

For each slice:
- Implement one coherent user-facing capability end-to-end.
- Include database/backend/frontend pieces needed for that capability.
- Test it locally where appropriate.
- Run the existing automated tests.
- Commit the completed slice incrementally.
- Deploy the slice to AWS and verify it works in the deployed application before moving on.
- Preserve already-working functionality from previous slices.

Do not deploy or commit unless I explicitly tell you to.

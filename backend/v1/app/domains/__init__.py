"""The features of the product, one module per area of the business.

=============================================================================
WHAT THIS FOLDER IS FOR
=============================================================================
Everything in the parent `app/` package is plumbing: connecting to a database,
parsing AWS events, matching URLs. This folder is where the actual PRODUCT
lives — the rules about incidents, facilities, engineers, and permissions.

Keeping the two apart is deliberate. Someone asking "how does an employee
report a fault?" should be able to read one file here without wading through
Lambda or database mechanics. Grouping by business area rather than by
technical layer also means a change to one feature touches one file.

=============================================================================
THE SHAPE OF EVERY HANDLER IN THIS FOLDER
=============================================================================
Each module exposes plain functions with an identical signature:

    def do_something(request: Request) -> dict:

They take our own Request object (never a raw AWS event) and return a response
built by the helpers in app/http.py. They are wired to URLs in app/router.py.

Because they are ordinary functions taking ordinary arguments, they can be
tested by constructing a Request directly — no AWS, no web server needed.

=============================================================================
WHAT EXISTS SO FAR
=============================================================================
Slice 0 contains only `health`, the endpoint that proves the system is alive.
Later slices add auth, users, facilities, engineers, incidents, notes, and
reports.
"""

__all__ = ["health"]

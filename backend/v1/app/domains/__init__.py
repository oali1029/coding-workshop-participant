"""Product features, one module per area of the business.

The parent package is plumbing — events, routing, database access. These
modules hold the rules about incidents, facilities and permissions, so a
question like "how does an employee report a fault?" can be answered from one
file without wading through Lambda mechanics.

Every handler takes an :class:`app.http.Request` and returns a response built
by the helpers in ``app.http``, which means it can be tested by constructing a
Request directly. Routes are wired to them in ``app.router``.
"""

__all__ = ["analytics", "auth", "comments", "facilities", "health", "incidents", "users"]

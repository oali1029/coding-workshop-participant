"""ACME Facility Incident Management — backend application package.

The entire backend is a single AWS Lambda. Terraform discovers it from
``backend/v1/`` and pins its entry point to ``function.handler``.

Request flow:

    React → CloudFront (AWS) or the dev proxy (local)
          → function.py      translate the AWS event
          → router.py        match the URL, enforce the route's access rule
          → domains/*.py     business logic
          → db.py            PostgreSQL
          → back out as JSON

One Lambda rather than one per domain: the infrastructure creates a Lambda per
folder under ``backend/``, and splitting would duplicate the database, auth and
permission code into every folder (there is no shared-layer mechanism here),
multiply cold starts, and open a separate connection per copy against a
deliberately small database.

Modules:
    errors      expected failures and their HTTP status codes
    http        AWS event in, JSON response out
    db          PostgreSQL connection handling
    migrations  schema creation and versioning
    security    password hashing, tokens, role checks
    router      URL matching and the route table
    domains/    the product features themselves
"""

__all__ = ["db", "errors", "http", "migrations", "router", "security"]

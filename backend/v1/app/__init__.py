"""ACME Facility Incident Management — backend application package.

=============================================================================
WHAT THIS WHOLE FOLDER IS
=============================================================================
This package contains the entire backend of the ACME facility incident
management platform: the system where employees report broken air
conditioning, faulty laptops, or a jammed badge reader, and where facility
admins and engineers track those reports to completion.

The whole backend is ONE AWS Lambda function. A Lambda is a small program that
cloud infrastructure runs on demand: it wakes up when a request arrives, does
its work, and goes back to sleep. We do not run a server that sits idle.

=============================================================================
HOW A SINGLE REQUEST TRAVELS THROUGH THE SYSTEM
=============================================================================
This is the most important thing to understand about the project. Follow one
click from a user's browser all the way to the database and back:

    1. React (browser)       User clicks "Report Incident". Our React code
                             calls fetch("/api/v1/incidents").

    2. CloudFront (on AWS)   Amazon's content delivery network receives it.
       or the local proxy    A rule says: anything starting with "/api/v1"
       (on a laptop)         is not a web page, it is an API call — forward
                             it to the Lambda. Everything else is the React
                             app itself, served from S3 storage.

    3. Lambda entry point    AWS starts our function and hands it a Python
       (../function.py)      dictionary describing the HTTP request.

    4. http.parse_request()  We translate that AWS-shaped dictionary into our
                             own simple Request object, so no other code has
                             to know what an AWS event looks like.

    5. router.dispatch()     We look at the method ("POST") and the path
                             ("/incidents") and decide which function should
                             handle it.

    6. A domain handler      The chosen function in domains/ runs the actual
       (domains/*.py)        business logic: validate the input, decide if
                             this user is allowed, then read or write data.

    7. db.py                 We send SQL to PostgreSQL and get rows back.

    8. http.ok(...)          We wrap the result in the response shape AWS
                             expects, and it travels back up the same chain
                             to the browser, where React renders it.

=============================================================================
WHY ONE LAMBDA INSTEAD OF MANY
=============================================================================
This project's infrastructure automatically creates one Lambda for every
folder inside backend/. We deliberately use a SINGLE folder, "v1", so we get
a single Lambda, because:

  * Shared code stays shared. Database connection logic, login checking, and
    permission rules are written once and imported normally. With several
    Lambdas we would have to copy those files into every folder.
  * Fewer database connections. Each running copy of a Lambda opens its own
    connection to PostgreSQL. More Lambdas means more connections competing
    for a database that is deliberately sized small for this workshop.
  * Simpler front end. The React app has one API address to remember.

The folder is named "v1" purely so the public URL reads nicely as
"/api/v1/...", which is a conventional way to version a web API.

=============================================================================
MODULE MAP — what each file in this package is for
=============================================================================
    errors.py       Our catalogue of expected failures (not found, forbidden,
                    invalid input...) and which HTTP status each becomes.
    http.py         Translating AWS events in, and JSON responses out.
    db.py           Talking to PostgreSQL, and reusing the connection.
    migrations.py   Creating and updating database tables automatically.
    router.py       Matching a URL to the function that handles it.
    domains/        The actual features, one file per area of the product.
"""

__all__ = ["db", "errors", "http", "migrations", "router"]

#!/usr/bin/env bash
# Script: Seed the ACME Facility Incident demo dataset
#
# Usage:
#   ./bin/seed-demo-data.sh local            Create the demo dataset locally
#   ./bin/seed-demo-data.sh local --clean    Remove it again
#   ./bin/seed-demo-data.sh local --status   Report what is currently seeded
#   ./bin/seed-demo-data.sh aws              The same, against the deployed stack
#   ./bin/seed-demo-data.sh aws --clean
#   ./bin/seed-demo-data.sh aws --status
#
# Nothing here runs on its own. The application never seeds itself, and this
# script is the only way in.
#
# WHY THE TWO ENVIRONMENTS DIFFER. Locally the database is on localhost, so the
# seeder runs as an ordinary Python program. Aurora is not publicly reachable —
# it has no public address — so the same code is run *inside* the deployed
# Lambda by invoking the function directly through the AWS API. That path needs
# lambda:InvokeFunction, which only this account holds, and it cannot be reached
# through CloudFront or the Function URL. See app/demo_seed.py:classify_event.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P)"
SERVICE="v1"

# Demo account passwords are kept out of the repository. This directory is
# gitignored; the file inside it is created with owner-only permissions and its
# contents are never printed.
CREDENTIALS_DIR="$PROJECT_ROOT/.demo-seed"
CREDENTIALS_FILE="$CREDENTIALS_DIR/credentials.env"

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

fail() {
    echo "" >&2
    echo "ERROR: $*" >&2
    exit 1
}

[ $# -ge 1 ] || usage 1
case "${1:-}" in -h|--help) usage 0 ;; esac

ENVIRONMENT="$1"
shift

ACTION="seed"
while [ $# -gt 0 ]; do
    case "$1" in
        --clean)  ACTION="clean" ;;
        --status) ACTION="status" ;;
        -h|--help) usage 0 ;;
        *) fail "Unknown option '$1'. Try --help." ;;
    esac
    shift
done

case "$ENVIRONMENT" in
    local|aws) ;;
    *) fail "First argument must be 'local' or 'aws'." ;;
esac

# Used by both environments — to generate the password, build the invocation
# payload, and format the result.
command -v python3 >/dev/null 2>&1 || fail "python3 is required."

# ---------------------------------------------------------------------------
# Demo account password
# ---------------------------------------------------------------------------
# Read from the environment if the operator supplied one, otherwise generate one
# and remember it, so a reseed keeps the same logins working. Only ever written
# to a gitignored file with 600 permissions, and never echoed.
resolve_password() {
    if [ -n "${DEMO_USER_PASSWORD:-}" ]; then
        return
    fi

    if [ -f "$CREDENTIALS_FILE" ]; then
        # shellcheck disable=SC1090
        . "$CREDENTIALS_FILE"
    fi

    if [ -z "${DEMO_USER_PASSWORD:-}" ]; then
        mkdir -p "$CREDENTIALS_DIR"
        chmod 700 "$CREDENTIALS_DIR"
        local generated
        # Generated with python3 rather than a /dev/urandom pipeline: `head`
        # closing the pipe early makes `tr` exit on SIGPIPE, which `pipefail`
        # then turns into a failed script.
        generated="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
        umask 077
        printf 'export DEMO_USER_PASSWORD=%s\n' "$generated" > "$CREDENTIALS_FILE"
        chmod 600 "$CREDENTIALS_FILE"
        DEMO_USER_PASSWORD="$generated"
        echo "Generated a demo account password and stored it in:"
        echo "  $CREDENTIALS_FILE"
        echo "  (source that file to sign in as a demo user; it is gitignored)"
        echo ""
    fi

    export DEMO_USER_PASSWORD
}

# ---------------------------------------------------------------------------
# Output formatting — one formatter for both environments
# ---------------------------------------------------------------------------
print_result() {
    ENV_LABEL="$1" TARGET_LABEL="$2" ACTION_LABEL="$3" python3 - "$4" <<'PYTHON'
import json, os, sys

with open(sys.argv[1]) as handle:
    text = handle.read().strip()

try:
    payload = json.loads(text) if text else {}
except json.JSONDecodeError:
    print(text)
    raise SystemExit(1)

# A direct Lambda invocation wraps the result; the local run returns it plainly.
if isinstance(payload, dict) and "ok" in payload:
    if not payload.get("ok"):
        print("Demo seed FAILED: %s" % payload.get("error", "unknown error"), file=sys.stderr)
        raise SystemExit(1)
    payload = payload.get("result", {})

action = os.environ["ACTION_LABEL"]


def row(label, value):
    print("%-22s %8s" % (label + ":", value))


if action == "clean":
    if not payload.get("found"):
        print("No demo dataset was present; nothing was removed.")
    else:
        print("Demo dataset removed\n")
        for key, value in payload.get("removed", {}).items():
            row(key.capitalize(), value)
        skipped = payload.get("skipped") or {}
        if skipped:
            print("\nKept (still referenced by records this seeder did not create):")
            for key, value in skipped.items():
                row("  " + key.capitalize(), value)
elif action == "status":
    if not payload.get("present"):
        print("No demo dataset is currently seeded.")
    else:
        print("Demo dataset present (seeded %s)\n" % payload.get("seeded_at", "unknown"))
        action = "seed"

if action == "seed" and payload.get("incidents"):
    if payload.get("replaced_previous"):
        print("An earlier demo dataset was found and replaced.\n")
    print("Demo dataset seeded successfully\n")
    status = payload.get("by_status", {})
    row("Buildings", payload.get("buildings", 0))
    row("Floors", payload.get("floors", 0))
    row("Seats", payload.get("seats", 0))
    row("Employees", payload.get("employees", 0))
    row("Engineers", payload.get("engineers", 0))
    row("  unavailable", payload.get("unavailable_engineers", 0))
    row("Incidents", payload.get("incidents", 0))
    row("  Open", status.get("OPEN", 0))
    row("  In Progress", status.get("IN_PROGRESS", 0))
    row("  Blocked", status.get("BLOCKED", 0))
    row("  Resolved", status.get("RESOLVED", 0))
    row("  Closed", status.get("CLOSED", 0))
    row("Comments", payload.get("comments", 0))
    row("Escalated", payload.get("escalated", 0))
    row("Recurring clusters", payload.get("recurring_clusters", 0))

print("")
print("Environment: %s" % os.environ["ENV_LABEL"])
print("Target:      %s" % os.environ["TARGET_LABEL"])
PYTHON
}

RESULT_FILE="$(mktemp)"
trap 'rm -f "$RESULT_FILE"' EXIT

# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------
run_local() {
    command -v python3 >/dev/null 2>&1 || fail "python3 is required."

    export IS_LOCAL="${IS_LOCAL:-true}"
    export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
    export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
    export POSTGRES_USER="${POSTGRES_USER:-postgres}"
    export POSTGRES_PASS="${POSTGRES_PASS:-postgres123}"
    export POSTGRES_NAME="${POSTGRES_NAME:-postgres}"

    if ! pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -q 2>/dev/null; then
        fail "PostgreSQL is not reachable on $POSTGRES_HOST:$POSTGRES_PORT. Start it with ./bin/start-dev.sh"
    fi

    # Run from the service directory: Lambda loads `app` and `function` side by
    # side rather than as an installed package, and so does this.
    ( cd "$PROJECT_ROOT/backend/$SERVICE" && python3 -m app.demo_seed "$ACTION" ) > "$RESULT_FILE"

    print_result "local" "postgresql://$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_NAME" "$ACTION" "$RESULT_FILE"
}

# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------
check_aws_credentials() {
    command -v aws >/dev/null 2>&1 || fail "The AWS CLI is required for 'aws'."

    local config="$PROJECT_ROOT/ENVIRONMENT.config"
    if [ -f "$config" ]; then
        # shellcheck disable=SC1090
        . "$config"
    fi

    if [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
        fail "No AWS credentials found. Run: ./bin/setup-participant.sh"
    fi

    local stderr_file
    stderr_file="$(mktemp)"
    if ! aws sts get-caller-identity >/dev/null 2>"$stderr_file"; then
        local message
        message="$(cat "$stderr_file")"
        rm -f "$stderr_file"
        if echo "$message" | grep -qi "ExpiredToken\|expired"; then
            fail "Your AWS session has expired. Run: ./bin/setup-participant.sh"
        fi
        fail "AWS credentials are not usable. Run: ./bin/setup-participant.sh

Reported by the AWS CLI:
$message"
    fi
    rm -f "$stderr_file"
}

resolve_function_name() {
    # Built from the same values Terraform uses, so nothing is hardcoded, then
    # confirmed against the account before anything is invoked.
    local name="${PROJECT_NAME:-coding-workshop}-${SERVICE}-${PARTICIPANT_ID:-}"

    if [ -z "${PARTICIPANT_ID:-}" ]; then
        fail "PARTICIPANT_ID is not set. Run: ./bin/setup-participant.sh"
    fi

    if ! aws lambda get-function --function-name "$name" >/dev/null 2>&1; then
        fail "Lambda function '$name' was not found in this account.
Deploy the backend first: ./bin/deploy-backend.sh"
    fi

    FUNCTION_NAME="$name"
}

run_aws() {
    check_aws_credentials
    resolve_function_name

    # The payload carries the demo password, so it goes to a 600 temp file
    # rather than the command line, where it would be visible in `ps`.
    local payload_file
    payload_file="$(mktemp)"
    chmod 600 "$payload_file"
    # shellcheck disable=SC2064
    trap "rm -f '$payload_file' '$RESULT_FILE'" EXIT

    ACTION="$ACTION" PASSWORD="${DEMO_USER_PASSWORD:-}" python3 - "$payload_file" <<'PYTHON'
import json, os, sys

payload = {
    "demo_seed": {
        "marker": "acme.facility.demo-seed.v1",
        "action": os.environ["ACTION"],
    }
}
if os.environ.get("PASSWORD"):
    payload["demo_seed"]["password"] = os.environ["PASSWORD"]

with open(sys.argv[1], "w") as handle:
    json.dump(payload, handle)
PYTHON

    echo "Invoking $FUNCTION_NAME (action: $ACTION)..."
    local invoke_output
    invoke_output="$(aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --cli-binary-format raw-in-base64-out \
        --payload "file://$payload_file" \
        --cli-read-timeout 300 \
        "$RESULT_FILE" 2>&1)" || fail "The Lambda invocation failed:
$invoke_output"

    rm -f "$payload_file"

    if echo "$invoke_output" | grep -q '"FunctionError"'; then
        fail "The function returned an error:
$(cat "$RESULT_FILE")"
    fi

    print_result "aws" "$FUNCTION_NAME" "$ACTION" "$RESULT_FILE"
}

# ---------------------------------------------------------------------------
if [ "$ACTION" = "seed" ]; then
    resolve_password
fi

case "$ENVIRONMENT" in
    local) run_local ;;
    aws)   run_aws ;;
esac

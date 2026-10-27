#!/usr/bin/env bash
# google-api.sh — wrapper for Google API calls with automatic token refresh
#
# Usage:
#   google-api.sh <METHOD> <URL> [curl-options...]
#
# Examples:
#   google-api.sh GET "https://www.googleapis.com/drive/v3/files?pageSize=10"
#   google-api.sh POST "https://docs.googleapis.com/v1/documents" -H "Content-Type: application/json" -d '{"title":"My Doc"}'
#   google-api.sh POST "https://docs.googleapis.com/v1/documents/DOC_ID:batchUpdate" -H "Content-Type: application/json" -d @/tmp/payload.json
#
# Output: raw API response JSON to stdout
# Errors: to stderr, exit 1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REFRESH_SCRIPT="$SCRIPT_DIR/google-refresh.sh"

if [ ! -f "$REFRESH_SCRIPT" ]; then
  echo "ERROR: google-refresh.sh not found at $REFRESH_SCRIPT" >&2
  exit 1
fi

# Get fresh access token
ACCESS_TOKEN=$("$REFRESH_SCRIPT")
if [ $? -ne 0 ] || [ -z "$ACCESS_TOKEN" ]; then
  echo "ERROR: Could not get access token" >&2
  exit 1
fi

METHOD="$1"
URL="$2"
shift 2

# Make the API call
curl -s -X "$METHOD" "$URL" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "$@"

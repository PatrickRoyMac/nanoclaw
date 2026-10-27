#!/usr/bin/env bash
# google-refresh.sh — ensures google-tokens.json has a valid access token
# Outputs fresh access token to stdout; exits 1 on failure

TOKENS_FILE="/root/nanoclaw/data/secrets/google-tokens.json"

python3 - "$TOKENS_FILE" << 'EOF'
import sys, json, time, urllib.request, urllib.parse, os

tokens_file = sys.argv[1]

with open(tokens_file) as f:
    tok = json.load(f)

refresh_token = tok['refresh_token']
client_id = tok['client_id']
client_secret = tok['client_secret']
access_token = tok.get('access_token', '')
token_expiry = tok.get('token_expiry', 0)

now = int(time.time())
refresh_threshold = now + 300  # refresh if expiring within 5 min

if not access_token or token_expiry < refresh_threshold:
    data = urllib.parse.urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }).encode()
    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=data,
        method='POST'
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    new_token = result['access_token']
    expires_in = result.get('expires_in', 3599)
    new_expiry = now + expires_in - 60

    tok['access_token'] = new_token
    tok['token_expiry'] = new_expiry

    tmp_file = tokens_file + '.tmp'
    with open(tmp_file, 'w') as f:
        json.dump(tok, f, indent=2)
    os.replace(tmp_file, tokens_file)
    os.chmod(tokens_file, 0o600)

    print(new_token)
else:
    print(access_token)
EOF

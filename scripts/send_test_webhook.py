#!/usr/bin/env python3
import os
import sys
import json
import hmac
import hashlib
import requests

"""Send a test webhook to the local app using the WEBHOOK_SHARED_SECRET.

Usage:
  export WEBHOOK_SHARED_SECRET=yoursecret
  python3 scripts/send_test_webhook.py [URL]

If URL is omitted the script posts to http://localhost:8080/integrations/incoming-webhook
"""

def compute_sig(secret: str, payload: bytes) -> str:
    mac = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256)
    return mac.hexdigest()


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8080/integrations/incoming-webhook'
    secret = os.getenv('WEBHOOK_SHARED_SECRET')
    payload = json.dumps({'event': 'test_ping'}).encode('utf-8')
    sig = compute_sig(secret, payload) if secret else ''
    headers = {'Content-Type': 'application/json'}
    if sig:
        headers['X-Webhook-Signature'] = sig
    else:
        print('Warning: WEBHOOK_SHARED_SECRET not set; sending unsigned request')

    try:
        r = requests.post(url, data=payload, headers=headers, timeout=5)
        print('Response:', r.status_code)
        print(r.text)
    except Exception as e:
        print('Request failed:', e)


if __name__ == '__main__':
    main()

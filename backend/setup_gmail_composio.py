"""
Verify that Gmail is connected to Composio for luongphambao1901@gmail.com.

SETUP (one-time, do this in browser):
  1. Go to: https://app.composio.dev/apps/gmail
  2. Click "Connect Account"
  3. Sign in with luongphambao1901@gmail.com and grant Gmail access

Then run this script to confirm:
    python setup_gmail_composio.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "src"))

import composio

api_key = os.environ.get("COMPOSIO_API_KEY", "")
if not api_key:
    print("ERROR: COMPOSIO_API_KEY not found in .env")
    sys.exit(1)

client = composio.Composio(api_key=api_key)

print("Checking Gmail connections on your Composio account...")
all_accounts = client.connected_accounts.list()

gmail_all = [a for a in all_accounts.items if a.toolkit.slug == "gmail"]
gmail_active = [a for a in gmail_all if a.status == "ACTIVE"]

if gmail_all:
    print(f"\nFound {len(gmail_all)} Gmail connection(s):")
    for acc in gmail_all:
        print(f"  - ID: {acc.id}  status: {acc.status}")
else:
    print("\nNo Gmail connections found.")

if gmail_active:
    print(f"\n✓ Gmail is ACTIVE and ready to send emails.")
    print("Run the test:")
    print("  python test_email_send.py")
else:
    print("\n⚠ No active Gmail connection found.")
    print("\nTo connect, open this URL in your browser:")
    print("  https://app.composio.dev/apps/gmail")
    print("\nClick 'Connect Account' and sign in with luongphambao1901@gmail.com")
    sys.exit(1)

"""Seed the demo admin account for testing + interviews.

Creates (or reuses) the Firebase Auth user from DEMO_ADMIN_EMAIL /
DEMO_ADMIN_PASSWORD, sets the `admin: true` custom claim, and prints the
credentials to share with the interviewer.

Usage:
    backend/venv/bin/python backend/seed_admin.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firebase_admin import auth as firebase_auth

from backend.config import initialize_firebase, settings


def main() -> None:
    initialize_firebase()
    email = settings.demo_admin_email
    password = settings.demo_admin_password

    try:
        user = firebase_auth.get_user_by_email(email)
        print(f"User already exists: {email} (uid={user.uid}) — resetting password + admin claim.")
        firebase_auth.update_user(user.uid, password=password, email_verified=True)
        uid = user.uid
    except firebase_auth.UserNotFoundError:
        user = firebase_auth.create_user(
            email=email, password=password, email_verified=True, display_name="Demo Admin"
        )
        uid = user.uid
        print(f"Created demo admin: {email} (uid={uid})")

    firebase_auth.set_custom_user_claims(uid, {"admin": True})
    print("Admin claim granted. The user must sign in again for it to take effect.")
    print()
    print("Share with the interviewer:")
    print(f"  Email:    {email}")
    print(f"  Password: {password}")
    print("  Sign in at the workspace login screen (one click fills these).")


if __name__ == "__main__":
    main()

import os

SECRET_KEY = os.environ.get("APP_SECRET", "change-this-secret")
ADMIN_PASSWORD = os.environ.get("APP_PASSWORD", "change-this-password")

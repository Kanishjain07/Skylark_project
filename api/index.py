"""Vercel serverless entrypoint for the FastAPI backend.

Vercel routes every /api/* request here (see rewrites in vercel.json). The real
app lives in backend/app/main.py with routes at /chat, /health, etc., so we
mount it under /api to match the frontend's same-origin `/api` base URL.
"""
import os
import sys

# Make the backend package importable ("from app.main import app").
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from fastapi import FastAPI

from app.main import app as inner_app

app = FastAPI()
app.mount("/api", inner_app)

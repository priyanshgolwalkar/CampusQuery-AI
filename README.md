# CampusQuery AI

An AI-powered Text-to-SQL application that converts natural language questions into SQLite queries using Google Gemini.

## Features
- Natural language to SQL conversion
- Gemini primary and fallback models
- SQL query validation
- Read-only SQLite execution
- Interactive Gradio interface
- CSV export

## Tech Stack
- Python
- Google Gemini API
- SQLite
- Gradio
- Pandas
- SQLGlot

## Setup

Install dependencies:

pip install -r requirements.txt

Set your Gemini API key:

export GEMINI_API_KEY="YOUR_API_KEY"

Run:

python app.py

## Security
The Gemini API key must be stored as an environment variable. Never commit API keys to GitHub.

The application only permits SELECT queries and uses SQLite read-only connections.

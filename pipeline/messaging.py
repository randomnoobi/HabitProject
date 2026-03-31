"""
pipeline/messaging.py — Ollama message generation + Server notification.

Chart stages:
  DANGEROUS → "send to Ollama" → "Ollama generates message" → "send to Server"
  SAFE      → "server is informed of safe condition"

Uses the OpenAI-compatible API to talk to Ollama locally.
"""

import json
import time
import requests
from pipeline.config import OLLAMA_URL, OLLAMA_MODEL, SERVER_URL

# Try to import the OpenAI SDK (used for Ollama's compatible endpoint)
try:
    from openai import OpenAI
    _client = OpenAI(api_key='ollama', base_url=OLLAMA_URL)
    HAS_CLIENT = True
    print(f'  [messaging] Ollama client ready: {OLLAMA_URL} ({OLLAMA_MODEL})')
except ImportError:
    _client = None
    HAS_CLIENT = False
    print('  [messaging] OpenAI SDK not installed — using template fallback')


def generate_danger_message(distance_summary, danger_pairs):
    """
    Send a danger report to Ollama and get a safety alert message back.

    Chart: "every 1 minute update and send to Ollama → Ollama generates message"

    Args:
        distance_summary: human-readable summary from distance.summarize()
        danger_pairs: list of dangerous pair dicts from distance.compute_distances()

    Returns:
        str — the generated safety alert message
    """
    # Build a concise description of what's happening
    pair_descriptions = []
    for p in danger_pairs:
        if p['dangerous']:
            pair_descriptions.append(
                f'{p["pair"][0]} and {p["pair"][1]} are only {p["distance_px"]}px apart '
                f'(danger threshold: {p["threshold_px"]}px)'
            )

    situation = '; '.join(pair_descriptions) or 'Objects are dangerously close.'

    if HAS_CLIENT:
        return _call_ollama(situation, distance_summary)
    else:
        return _template_fallback(situation)


def _call_ollama(situation, distance_summary):
    """Generate a message using Ollama via the OpenAI-compatible API."""
    system = """You are a desk safety monitoring system. Your job is to generate clear, 
concise safety alerts when objects on a desk are too close together and could cause damage.

Rules:
- 1-2 sentences MAX.
- Be specific: name the objects and the risk.
- Be direct: tell the user exactly what to move.
- Example: "Warning: your phone is dangerously close to your laptop. Move the phone to avoid accidental damage or spills."
"""

    user = f"""CURRENT SITUATION: {situation}

FULL DISTANCE REPORT:
{distance_summary}

Generate ONE clear safety alert message. Just the text."""

    try:
        resp = _client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            max_tokens=100,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        print(f'  [messaging] Ollama error: {exc}')
        return _template_fallback(situation)


def _template_fallback(situation):
    """Simple template when Ollama is not available."""
    return f'⚠️ Safety Alert: {situation} Please separate the objects.'


def notify_server_danger(message, danger_pairs):
    """
    Send the danger alert to the server.

    Chart: "send to Server"

    Args:
        message: str — the generated alert message
        danger_pairs: list of pair dicts with distance info
    """
    payload = {
        'type': 'danger_alert',
        'message': message,
        'timestamp': time.time(),
        'pairs': [
            {
                'objects': list(p['pair']),
                'distance_px': p['distance_px'],
                'threshold_px': p['threshold_px'],
            }
            for p in danger_pairs if p['dangerous']
        ],
    }
    _send_to_server(payload)


def notify_server_safe():
    """
    Inform the server that all distances are safe.

    Chart: "server is informed of safe condition"
    Chart note: "if Ollama does not receive after 1 minute, is safe"
    """
    payload = {
        'type': 'safe_status',
        'message': 'All monitored object distances are within safe range.',
        'timestamp': time.time(),
    }
    _send_to_server(payload)


def _send_to_server(payload):
    """POST a JSON payload to the server endpoint."""
    url = f'{SERVER_URL}/api/safety'
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.ok:
            print(f'  [messaging] → Server: {payload["type"]}')
        else:
            print(f'  [messaging] Server responded {resp.status_code}')
    except requests.ConnectionError:
        # Server might not be running — that's OK for standalone pipeline use
        print(f'  [messaging] Server not reachable at {url} (running standalone)')
    except Exception as exc:
        print(f'  [messaging] Server error: {exc}')

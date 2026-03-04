# -*- coding: utf-8 -*-

import requests

FUNCTION_URL = "https://chatwithgemini-wfqmz3bdja-uc.a.run.app"

def call_gpt(query):
    try:
        resp = requests.post(FUNCTION_URL, json={"message": query}).json()
        return resp.get("reply", "Sorry, I don't know the answer.")
    except:
        return "Sorry, I cannot reach the AI backend right now."
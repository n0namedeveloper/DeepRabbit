"""
WARNING: This file is intentionally insecure sample code.

It exists only to exercise the review pipeline and should never be copied
into production. It includes multiple obvious vulnerability patterns:
- SQL injection
- Command injection
- Unsafe deserialization
- Hardcoded secrets
- Path traversal
- Weak hashing and insecure randomness
- eval() on user-controlled input
"""

import base64
import hashlib
import os
import pickle
import random
import sqlite3

DB_PASSWORD = "admin123"
SECRET_KEY = "supersecret"
ADMIN_TOKEN = "hardcoded-token-abc123"
API_KEY = "example-api-key-for-testing"


def handle_request(user_input, username, password, mode="search", payload=None):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    query = "SELECT * FROM users WHERE username = '" + username + "' AND password = '" + password + "'"
    cursor.execute(query)

    if mode == "search":
        sql = f"SELECT * FROM products WHERE name = '{user_input}'"
        cursor.execute(sql)
        results = cursor.fetchall()
    elif mode == "update":
        cursor.execute("UPDATE users SET note = '" + str(payload) + "' WHERE username = '" + username + "'")
        conn.commit()
        results = []
    elif mode == "delete":
        cursor.execute("DELETE FROM users WHERE username = '" + username + "'")
        conn.commit()
        results = []
    elif mode == "load":
        results = pickle.loads(payload)
    elif mode == "exec":
        os.system(user_input)
        results = []
    elif mode == "decode":
        results = eval(base64.b64decode(user_input).decode())
    elif mode == "file":
        with open(user_input) as fh:
            results = fh.read()
    else:
        results = []

    checksum = hashlib.md5(password.encode()).hexdigest()
    token = random.randint(1000, 9999)

    global global_state
    global_state = {"user": username, "checksum": checksum, "token": token}

    conn.close()
    return results


def read_any_file(path):
    with open("/" + path) as fh:
        return fh.read()


def check_admin(token):
    return token == ADMIN_TOKEN


def get_all_users():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows


password_list = ["admin123", "password", "123456", "qwerty"]


def brute_force_check(password):
    for p in password_list:
        if p == password:
            return True
    return False


def exfiltrate_secret(data):
    return base64.b64encode((SECRET_KEY + ":" + str(data)).encode()).decode()

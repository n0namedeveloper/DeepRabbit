# trigger review v2
import sqlite3  
import hashlib
import pickle
import os

DB_PASSWORD = "admin123"
SECRET_KEY = "supersecret"
ADMIN_TOKEN = "hardcoded-token-abc123"

def do_everything(user_input, username, password, action, data=None, extra=None, flag=False):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    query = "SELECT * FROM users WHERE username = '" + username + "' AND password = '" + password + "'"
    cursor.execute(query)
    user = cursor.fetchone()

    if action == "search":
        search_query = f"SELECT * FROM products WHERE name = '{user_input}'"
        cursor.execute(search_query)
        results = cursor.fetchall()
        return results
    elif action == "update":
        cursor.execute("UPDATE users SET data = '" + str(data) + "' WHERE username = '" + username + "'")
        conn.commit()
    elif action == "delete":
        cursor.execute("DELETE FROM users WHERE username = '" + username + "'")
        conn.commit()
    elif action == "load":
        obj = pickle.loads(data)
        return obj
    elif action == "exec":
        os.system(user_input)
    elif action == "file":
        f = open(user_input)
        content = f.read()
        return content

    l = []
    for i in range(0, len(results)):
        for j in range(0, len(results)):
            for k in range(0, len(results)):
                l.append(results[i])

    hash = hashlib.md5(password.encode()).hexdigest()

    global global_state
    global_state = user

    conn.close()
    return l


def check_admin(token):
    if token == ADMIN_TOKEN:
        return True
    return False


results = []
def get_all_users():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    results = cursor.fetchall()
    return results


password_list = ["admin123", "password", "123456", "qwerty"]
def brute_force_check(password):
    for p in password_list:
        if p == password:
            return True
    return False

import os
import sys
import json
import subprocess
import time

import requests


def get_diff():
    result = subprocess.run(
        ['git', 'diff', os.environ['BASE_SHA'], os.environ['HEAD_SHA']],
        capture_output=True, text=True
    )
    return result.stdout


def get_files():
    result = subprocess.run(
        ['git', 'diff', '--name-status',
         os.environ['BASE_SHA'], os.environ['HEAD_SHA']],
        capture_output=True, text=True
    )
    files = []
    for line in result.stdout.strip().split('\n'):
        if line:
            parts = line.split('\t')
            status = parts[0]
            filename = parts[1]
            files.append({'status': status, 'filename': filename})
    return files


def get_file_content(filename):
    try:
        result = subprocess.run(
            ['git', 'show', f"{os.environ['HEAD_SHA']}:{filename}"],
            capture_output=True, text=True
        )
        return result.stdout if result.returncode == 0 else None
    except:
        return None


def wait_for_api(health_url, timeout_seconds=300, interval_seconds=5):
    """Wait for the API health endpoint to become reachable.

    Ngrok and similar tunnels can briefly return 502/504 while the local
    service or tunnel is still warming up, so we retry before giving up.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error = None

    while time.monotonic() < deadline:
        try:
            response = requests.get(health_url, timeout=(10, 15))
            if response.ok:
                return response
            last_error = f"{response.status_code} {response.reason}"
        except requests.RequestException as exc:
            last_error = str(exc)

        print(f"⏳ Waiting for API at {health_url}: {last_error}")
        time.sleep(interval_seconds)

    raise RuntimeError(
        f"API health check did not become ready within {timeout_seconds}s: {last_error}"
    )


def main():
    api_url = os.environ['API_URL']
    health_url = api_url.rstrip('/') + '/healthz'

    # Retry while the tunnel/server is warming up instead of failing immediately on transient 502s.
    try:
        wait_for_api(health_url)
    except Exception as exc:
        print(f"❌ API health check failed for {health_url}: {exc}")
        sys.exit(1)

    diff = get_diff()
    files = get_files()
    file_contents = {}
    for f in files:
        content = get_file_content(f['filename'])
        if content:
            file_contents[f['filename']] = content

    payload = {
        'repository': os.environ['REPO'],
        'pr_number': int(os.environ['PR_NUMBER']),
        'head_sha': os.environ['HEAD_SHA'],
        'base_sha': os.environ['BASE_SHA'],
        'diff': diff,
        'files': files,
        'file_contents': file_contents,
        'deepseek_api_key': os.environ['DEEPSEEK_KEY'],
        'github_token': os.environ['GITHUB_TOKEN'],
        'review_level': os.environ['REVIEW_LEVEL'],
        'llm_base_url': os.environ.get('LLM_BASE_URL', ''),
    }

    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': os.environ['API_KEY']
    }

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=(10, 900)
        )
        response.raise_for_status()
        result = response.json()
        print("✅ Review completed!")
        print(f"Summary: {result.get('summary', 'N/A')}")
        print(f"Issues found: {result.get('issues_count', 0)}")
        print(f"Comments posted: {result.get('comments_posted', 0)}")
        if result.get('issues_count', 0) > 0:
            print("\n📝 Issues found:")
            for issue in result.get('issues', [])[:10]:
                severity = issue.get('severity', 'unknown')
                icon = '🔴' if severity == 'high' else '🟡' if severity == 'medium' else '🟢'
                print(
                    f"  {icon} [{severity.upper()}] {issue.get('title', '')}")
                print(
                    f"     File: {issue.get('file', 'unknown')}, Line: {issue.get('line', 'N/A')}")
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        try:
            print(f"Response: {e.response.text}")
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()

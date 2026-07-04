import os
import sys
import json
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit

import requests

# ---------------------------------------------------------------------------
# Binary / non-text file extensions that send_review should skip (#3)
# ---------------------------------------------------------------------------
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp', '.bmp', '.tiff',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.jar', '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.exe', '.dll', '.so', '.dylib', '.o', '.a', '.lib',
    '.pyc', '.pyo', '.pyd',
    '.whl', '.egg', '.deb', '.rpm',
    '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac',
    '.min.js', '.min.css',
}

MAX_FILES_PER_REVIEW = int(os.environ.get('MAX_FILES_PER_REVIEW', '20'))
MAX_FILE_SIZE_MB = 2


def _is_binary(filename: str) -> bool:
    """Check if a file extension should be excluded from review."""
    name = filename.lower()
    return any(name.endswith(ext) for ext in BINARY_EXTENSIONS)


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
            # Skip deleted and binary files (#3)
            if status == 'D' or _is_binary(filename):
                print(f"⏭️  Skipping binary/deleted file: {filename}")
                continue
            files.append({'status': status, 'filename': filename})
    return files


def get_file_content(filename):
    """Fetch file content with size limit enforced."""
    try:
        result = subprocess.run(
            ['git', 'show', f"{os.environ['HEAD_SHA']}:{filename}"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None
        content = result.stdout
        # Skip files over size limit
        if len(content.encode('utf-8')) > MAX_FILE_SIZE_MB * 1024 * 1024:
            print(
                f"⏭️  Skipping large file: {filename} ({len(content)} bytes)")
            return None
        return content
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


def build_endpoint_urls(api_url):
    """Derive the review and health endpoints from a configured API URL.

    The action supports passing either the server root (e.g. https://host)
    or the review endpoint itself (e.g. https://host/review).
    """
    parsed = urlsplit(api_url.rstrip('/'))
    path = parsed.path or ''

    if path.endswith('/review'):
        review_path = path
        health_path = path[:-len('/review')] + '/healthz' or '/healthz'
    elif path.endswith('/healthz'):
        review_path = path[:-len('/healthz')] + '/review' or '/review'
        health_path = path
    else:
        review_path = (path + '/review') if path else '/review'
        health_path = (path + '/healthz') if path else '/healthz'

    review_url = urlunsplit(
        (parsed.scheme, parsed.netloc, review_path, parsed.query, parsed.fragment))
    health_url = urlunsplit(
        (parsed.scheme, parsed.netloc, health_path, '', ''))
    return review_url, health_url


def main():
    api_url = os.environ['API_URL']
    review_url, health_url = build_endpoint_urls(api_url)

    # Retry while the tunnel/server is warming up instead of failing immediately on transient 502s.
    try:
        wait_for_api(health_url)
    except Exception as exc:
        print(f"❌ API health check failed for {health_url}: {exc}")
        sys.exit(1)

    # Issue #11: Support server_side_fetch option
    server_side_fetch = os.environ.get('SERVER_SIDE_FETCH', 'false').lower() in ('true', '1', 'yes')

    if server_side_fetch:
        print("ℹ️ Server-side fetch enabled. Server will retrieve git diff and contents.")
        diff = ""
        files = []
        file_contents = {}
    else:
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
        'server_side_fetch': server_side_fetch,  # tell server to fetch internally if true
    }

    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': os.environ['API_KEY']
    }

    try:
        response = requests.post(
            review_url,
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

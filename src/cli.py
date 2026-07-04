import sys
import os
import subprocess
import argparse
import requests
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(
        description="DeepRabbit CLI - Autonomous code review tool"
    )
    parser.add_argument(
        "--diff",
        help="Git reference to diff against (e.g., HEAD~1)",
        default="HEAD~1"
    )
    parser.add_argument(
        "--api-url",
        help="DeepRabbit server URL",
        default=os.environ.get("API_URL", "http://localhost:8000")
    )
    parser.add_argument(
        "--api-key",
        help="DeepRabbit API key",
        default=os.environ.get("API_KEY", "")
    )
    parser.add_argument(
        "--repo",
        help="Repository name (org/repo)",
        default=os.environ.get("REPO", "local/repo")
    )
    parser.add_argument(
        "--pr-number",
        type=int,
        help="PR number (for posting back to GitHub)",
        default=int(os.environ.get("PR_NUMBER", "0"))
    )

    args = parser.parse_args()

    # Get diff
    try:
        diff_res = subprocess.run(
            ["git", "diff", args.diff],
            capture_output=True,
            text=True,
            check=True
        )
        diff_text = diff_res.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to get git diff: {e}")
        sys.exit(1)

    if not diff_text.strip():
        print("✅ No changes found in diff. Nothing to review.")
        return

    print(f"🔍 Sending diff ({len(diff_text)} chars) to DeepRabbit at {args.api_url}...")
    
    # Basic payload structure similar to send_review
    payload = {
        "repository": args.repo,
        "pr_number": args.pr_number,
        "head_sha": "HEAD",
        "base_sha": args.diff,
        "diff": diff_text,
        "files": [],
        "file_contents": {},
        "deepseek_api_key": os.environ.get("DEEPSEEK_KEY", ""),
        "github_token": os.environ.get("GITHUB_TOKEN", ""),
        "review_level": "normal"
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": args.api_key
    }

    try:
        res = requests.post(f"{args.api_url}/review", json=payload, headers=headers)
        res.raise_for_status()
        result = res.json()
        print("✅ Review complete!")
        print(f"Summary: {result.get('summary', {}).get('summary', 'N/A')}")
        print(f"Rating: {result.get('summary', {}).get('rating', 'N/A')}")
        print(f"Issues count: {result.get('issues_count', 0)}")
    except Exception as e:
        print(f"❌ Review request failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

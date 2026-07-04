import sys; sys.path.insert(0, '.')
from src.security_scanner import SECRET_PATTERNS, SecurityScanner

code = '''import pickle
API_KEY = "sk-1234567890abcdef1234567890abcdef12345678"
'''

for p, title, sev in SECRET_PATTERNS:
    m = p.search(code)
    print(title, bool(m), p.pattern[:50])

scanner = SecurityScanner()
issues = scanner._scan_secrets("test.py", code)
print(f"secret_leak issues: {len(issues)}")
for i in issues:
    print(f"  {i.title}: {i.category}")

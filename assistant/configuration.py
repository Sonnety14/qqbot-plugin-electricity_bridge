"""Operator-supplied local configuration; tickets never choose upload destinations."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def load_upload_url(path=None):
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    data=json.loads(Path(path or root/'config.json').read_text(encoding='utf8'))
    value=data.get('website_origin','')
    u=urlsplit(value)
    if (u.scheme!='https' or not u.hostname or u.hostname.endswith('.invalid')
        or u.username or u.password or u.path not in ('','/') or u.query or u.fragment
        or any(ord(c)<33 or ord(c)>126 for c in value)):
        raise ValueError('A configured HTTPS website origin is required')
    return value.rstrip('/')+'/tools/campus/electric/upload'

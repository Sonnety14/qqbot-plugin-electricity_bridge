"""Operator-supplied local configuration; tickets never choose upload destinations."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def config_path():
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    return root/'config.json'


def normalize_origin(value):
    value=value.strip()
    u=urlsplit(value)
    if (u.scheme!='https' or not u.hostname or u.hostname.endswith('.invalid')
        or u.username or u.password or u.path not in ('','/') or u.query or u.fragment
        or any(ord(c)<33 or ord(c)>126 for c in value)):
        raise ValueError('A configured HTTPS website origin is required')
    u.port  # Validate malformed and out-of-range ports before accepting configuration.
    return value.rstrip('/')


def save_origin(value,path=None):
    origin=normalize_origin(value)
    Path(path or config_path()).write_text(json.dumps({'website_origin':origin},indent=2)+'\n',encoding='utf8')
    return origin


def load_upload_url(path=None):
    data=json.loads(Path(path or config_path()).read_text(encoding='utf8'))
    return normalize_origin(data.get('website_origin',''))+'/tools/campus/electric/upload'

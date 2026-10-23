"""Manual diagnostics: leave all TLS connections encrypted and untouched."""
def tls_clienthello(data):
    data.ignore_connection=True

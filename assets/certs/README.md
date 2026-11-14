# CA bundle provenance

Unmodified Mozilla/certifi public root CA data, packaged as plugin data only.
No certifi Python package or OS certificate installation is needed.

Source repository: https://github.com/certifi/python-certifi
Pinned commit: ca446ca404ff3b962a0193f36e03d1eabb231968
Source path: certifi/cacert.pem
SHA256: 2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b
Certificates: 118
Upstream license notice: licenses/certifi-MPL-2.0.txt (Mozilla Public License 2.0)

engine/tls.py supplements Python's default/system CA discovery with this file.
Certificate and hostname validation remain enabled. Never place private keys or
user-generated interception certificates in this resource.

# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/Jolly-Panda-Works/DeskPresence/security/advisories/new)
instead. You will get an answer within a few days.

Areas that deserve particular care:

- the desktop ↔ laptop network link (`deskpresence/network.py`)
- anything that handles webcam frames (`deskpresence/vision.py`)

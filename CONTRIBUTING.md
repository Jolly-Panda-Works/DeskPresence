# Contributing

Thanks for helping! Issues and pull requests in English or Persian are both welcome.

## Getting started

```bash
pip install -r requirements-dev.txt
```
```bash
python scripts/download_model.py
```
```bash
python run.py
```

## Before you open a pull request

- Run `python -m pytest`. CI runs the same tests before every build.
- Every user-facing text goes into `deskpresence/i18n.py` with **both** `fa` and `en`. A test checks this.
- Keep the colours in the shared palette (`deskpresence/ui.py`). It is the same palette as Image Format Converter and SnapshotAll.
- Webcam frames must never be saved or sent anywhere (see [PRIVACY.md](PRIVACY.md)).
- Don't edit version numbers by hand. CI sets them. Only change [`VERSION`](VERSION) for a new MAJOR.MINOR.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE) and that you follow the [Code of Conduct](CODE_OF_CONDUCT.md).

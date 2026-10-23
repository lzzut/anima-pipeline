# Security Policy

## Scope

This repository contains the image-generation pipeline code and two small sample images.

It does **not** include:

- model weights (`.safetensors`, `.ckpt`, `.pt`)
- generated image libraries
- personal data, login material, or credentials
- local runtime caches

## Credentials

No API keys, access tokens, passwords, or login material are stored in this repository.

Configuration is read from environment variables:

```text
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL   (optional)
DEEPSEEK_MODEL      (optional)
COMFY_URL           (optional)
COMFY_DIR
COMFY_PYTHON
```

Example:

```powershell
$env:DEEPSEEK_API_KEY = "..."
$env:COMFY_DIR = "C:\path\to\ComfyUI"
$env:COMFY_PYTHON = "C:\path\to\ComfyUI\venv\Scripts\python.exe"
python pipeline_character.py
```

Do not commit a `.env` file or shell history containing real values.

## Local paths

No machine-specific absolute paths are committed.

If you find one, open an issue with the path redacted rather than committing a replacement containing another personal path.

## Data

The `data/` directory contains only:

- a Danbooru tag/count index
- artist combination identifiers
- character debut years

Sources are documented in the README. These values are approximate and may become outdated.

## External requests

The pipeline calls:

- a local ComfyUI server;
- the DeepSeek API for character selection, prompt generation, and optional body-type review;
- public image/tag sources for character reference and tag counts.

Image or text data sent to an external API leaves your machine. Review the provider's terms before use.

## Reporting

If you find a credential, personal path, or private information in the repository, open an issue with the value redacted, or contact the maintainer privately. Do not reproduce the value in a public issue.

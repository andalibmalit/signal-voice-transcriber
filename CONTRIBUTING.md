# Contributing

Thanks for your interest in contributing to Signal Voice Transcriber!

## Development setup

```bash
# Clone the repo
git clone https://github.com/andalibmalit/signal-voice-transcriber.git
cd signal-voice-transcriber

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Running tests

```bash
pytest
```

## Submitting changes

1. Fork the repo and create a feature branch from `main`
2. Make your changes and add tests if applicable
3. Run `pytest` and make sure all tests pass
4. Open a pull request with a clear description of what you changed and why

## Code style

- Python 3.11+ with type hints on all functions
- Async throughout (aiohttp, not requests)
- Keep modules small and focused
- No linter is enforced yet — just keep it readable

## Reporting issues

Open a GitHub issue with steps to reproduce. Include your Python version, Docker version, and any relevant logs.

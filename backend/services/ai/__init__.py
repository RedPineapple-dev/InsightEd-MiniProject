"""AI subsystem — provider-specific clients and key management.

Currently only Gemini is wired up, but the package is structured so that
additional providers (OpenAI, Anthropic, local Ollama) can drop in
without touching the rest of the codebase.
"""

from .key_manager import GeminiKeyManager, KeyState

__all__ = ["GeminiKeyManager", "KeyState"]

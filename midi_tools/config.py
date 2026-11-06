"""User configuration.

DEFAULT_PORT is used by every command when --port is not given. It is matched
like --port (index, exact name or case-insensitive substring) against both the
input and the output port lists. Override with the PYMIDI_PORT environment variable.
"""
import os

DEFAULT_PORT = os.environ.get("PYMIDI_PORT", "Clarett")

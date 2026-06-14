"""Voice agent: the LLM 'brain' (prompt + tools) and, later, the Pipecat audio pipeline.

The prompt and tool bridge here are framework-agnostic and fully testable without any API keys.
The Pipecat pipeline (STT/LLM/TTS wiring) and the Exotel transport are added in M2/M3 once vendor
keys are available; they will register these same tools and use this same system prompt.
"""

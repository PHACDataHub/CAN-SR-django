from decouple import Csv, config

LLM_MODE = config("LLM_MODE", default="local")

# Only local Ollama is supported in normal runtime today.
LLM_OLLAMA_URL = config("OLLAMA_URL", default="http://localhost:11434")
LLM_OLLAMA_MODELS = config("OLLAMA_MODELS", cast=Csv())
LLM_OLLAMA_MODEL = LLM_OLLAMA_MODELS[0]
LLM_OLLAMA_TIMEOUT = config("LLM_OLLAMA_TIMEOUT", default=60, cast=int)

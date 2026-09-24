from app.providers.openai_compatible import OpenAICompatibleProvider
p=OpenAICompatibleProvider()
def get_provider(provider_id):
 if provider_id not in {'lmstudio','ollama-openai','openai-compatible'}:raise ValueError('Unsupported provider: '+provider_id)
 return p

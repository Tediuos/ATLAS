"""Premier test : on parle au LLM."""
from atlas.llm import get_llm_client

client, model = get_llm_client()

response = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": "Tu es un assistant utile. Réponds en français."},
        {"role": "user", "content": "Dis-moi bonjour en une phrase et précise quel modèle tu es."},
    ],
)

print(f"Modèle utilisé : {model}")
print(f"Réponse : {response.choices[0].message.content}")
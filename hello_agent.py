"""Premier agent avec tool calling - 2 outils factices pour valider la boucle."""
import json
from datetime import datetime
from atlas.llm import get_llm_client


# 1. DÉCLARATION des outils au modèle (JSON Schema standard OpenAI)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Retourne la date et l'heure actuelles au format ISO 8601.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Additionne deux nombres et retourne le résultat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Premier nombre"},
                    "b": {"type": "number", "description": "Deuxième nombre"},
                },
                "required": ["a", "b"],
            },
        },
    },
]


# 2. IMPLÉMENTATION Python des outils
def get_current_time():
    return {"now": datetime.now().isoformat()}


def add_numbers(a, b):
    return {"result": a + b}


TOOL_FUNCTIONS = {
    "get_current_time": get_current_time,
    "add_numbers": add_numbers,
}


def execute_tool(name, arguments):
    """Lance l'outil demandé par le modèle."""
    if arguments is None:
        arguments = {}
    return TOOL_FUNCTIONS[name](**arguments)


# 3. BOUCLE AGENT (le cœur du système)
def run_agent(user_message, max_iterations=10):
    client, model = get_llm_client()
    messages = [
        {
            "role": "system",
            "content": "Tu es un assistant qui peut appeler des outils quand c'est utile. Réponds en français.",
        },
        {"role": "user", "content": user_message},
    ]

    for i in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        # Le modèle n'a plus besoin d'outils -> réponse finale
        if not message.tool_calls:
            return message.content

        # Le modèle veut appeler des outils -> on les exécute
        print(f"\n[Itération {i+1}] Le modèle appelle {len(message.tool_calls)} outil(s) :")
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"   -> {name}({args})")

            result = execute_tool(name, args)
            print(f"   <- {result}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })

    return "Limite d'itérations atteinte sans réponse finale"


# 4. TESTS
if __name__ == "__main__":
    print("=" * 60)
    print("TEST 1 : question simple (le modèle n'a pas besoin d'outil)")
    print("=" * 60)
    print(run_agent("Quelle est la capitale de la France ?"))

    print("\n" + "=" * 60)
    print("TEST 2 : nécessite get_current_time")
    print("=" * 60)
    print(run_agent("Quelle heure est-il exactement ?"))

    print("\n" + "=" * 60)
    print("TEST 3 : nécessite add_numbers")
    print("=" * 60)
    print(run_agent("Combien font 1247 + 5832 ?"))
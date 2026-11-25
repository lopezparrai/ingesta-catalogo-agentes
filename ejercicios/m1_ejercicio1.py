from dotenv import load_dotenv
load_dotenv()
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(
 model="claude-haiku-4-5",
 max_tokens=256,
 messages=[{"role": "user", "content": "Decime hola en 5 idiomas distintos."}]
)
print(response.content[0].text)
print(f"\nTokens usados: {response.usage.input_tokens} input {response.usage.output_tokens} output")
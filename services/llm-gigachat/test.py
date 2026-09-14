import os
from dotenv import load_dotenv
from gigachat import GigaChat

load_dotenv()

key = os.getenv("GIGA_PASSWORD")
print(f"Длина ключа: {len(key) if key else 0}")
print(f"Первые 20 символов: {key[:20] if key else 'НЕТ'}")
print(f"Последние 10 символов: {key[-10:] if key else 'НЕТ'}")

client = GigaChat(
    base_url="https://api.giga.chat/v1",
    credentials=key,
    scope="GIGACHAT_API_PERS",
    ca_bundle_file="russian_trusted_root_ca_pem.crt",
    model="GigaChat-3-Ultra",
    verify_ssl_certs=False,
)

try:
    models = client.get_models()
    print("✅ Ключ работает. Доступные модели:")
    for m in models.data:
        print(f"  - {m.id}")
except Exception as e:
    print(f"❌ Ошибка: {e}")
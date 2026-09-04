# CodeGuard 🛡️

Bot de revisión de código con IA para Pull Requests, integrado directamente
en GitHub Actions. En cada PR, un modelo de lenguaje analiza el diff y
publica un comentario automático con un resumen del cambio, posibles bugs
y sugerencias de estilo — sin depender de ningún servicio de pago.

## ¿Por qué este proyecto?

Es un ejemplo de integración real de IA en un flujo de CI/CD: nada de
"wrapper de un prompt", sino un pipeline completo (GitHub Actions → diff →
LLM → comentario en la PR) usando únicamente herramientas gratuitas
(GitHub Actions incluido en repos públicos + [Groq](https://groq.com) como
proveedor de inferencia gratuita).

## Cómo funciona

1. Al abrir o actualizar una Pull Request, se dispara el workflow
   [`.github/workflows/pr-review.yml`](.github/workflows/pr-review.yml).
2. El workflow instala las dependencias de Python y ejecuta
   [`scripts/review_pr.py`](scripts/review_pr.py).
3. El script:
   - Obtiene el diff de la PR mediante la API REST de GitHub
     (`GET /repos/{owner}/{repo}/pulls/{pr_number}` con
     `Accept: application/vnd.github.v3.diff`).
   - Si el diff está vacío, publica un aviso y termina sin llamar al modelo.
   - Si el diff es muy largo, lo trunca antes de enviarlo (por defecto,
     12000 caracteres) para no exceder los límites del modelo.
   - Envía el diff a la API de Groq (`openai/gpt-oss-120b`, endpoint
     compatible con OpenAI) pidiendo un resumen, posibles bugs y
     sugerencias de estilo.
   - Publica la respuesta como comentario en la PR usando
     `POST /repos/{owner}/{repo}/issues/{pr_number}/comments`, autenticado
     con el `GITHUB_TOKEN` que GitHub Actions provee automáticamente (no
     hace falta ningún token adicional).

Si hay un error de red, de la API de Groq o de la API de GitHub, el script
lo reporta como error de Actions (`::error::...`) y termina con código de
salida 1, sin dejar el job en un estado ambiguo.

## Configuración

1. **Consigue una API key gratuita de Groq**: crea una cuenta en
   [console.groq.com](https://console.groq.com/keys) y genera una key.
2. **Añádela como secreto del repositorio**: en GitHub, ve a
   `Settings → Secrets and variables → Actions → New repository secret` y
   crea un secreto llamado `GROQ_API_KEY` con el valor de tu key.
3. Listo. El workflow ya usa el `GITHUB_TOKEN` automático de Actions
   (con permiso `pull-requests: write`, ya configurado en el workflow) para
   publicar comentarios, así que no necesitas crear ningún otro secreto.
4. Abre una Pull Request en el repo y espera el comentario del bot.

## Estructura del proyecto

```
.
├── .github/workflows/pr-review.yml   # Workflow que dispara la revisión en cada PR
├── scripts/review_pr.py              # Lógica: obtener diff, llamar a Groq, comentar en la PR
├── tests/test_review_pr.py           # Tests locales (mockean las llamadas HTTP)
├── requirements.txt                  # Única dependencia: requests
└── .gitignore
```

## Probar en local

El script se puede probar sin necesidad de una PR real ni de gastar
llamadas a la API, usando los tests incluidos (mockean `requests.get` y
`requests.post`):

```bash
pip install -r requirements.txt
python -m unittest tests/test_review_pr.py -v
```

Para probarlo end-to-end contra la API de Groq real (sin GitHub), puedes
simular las variables de entorno y llamar directamente a las funciones del
script desde una consola de Python:

```bash
export GROQ_API_KEY="tu-api-key-de-groq"
python - <<'EOF'
import sys
sys.path.insert(0, "scripts")
from review_pr import call_groq

diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
-def add(a, b):
-    return a + b
+def add(a, b):
+    return a - b  # bug: debería sumar, no restar
"""

print(call_groq(diff, was_truncated=False, api_key="$GROQ_API_KEY"))
EOF
```

## Limitaciones conocidas

- El modelo gratuito de Groq tiene límites de tasa (rate limits); en repos
  con mucha actividad de PRs podría no ser suficiente sin un plan de pago.
- El diff se trunca por longitud, no de forma "inteligente" (no prioriza
  archivos concretos), así que en PRs enormes la revisión puede quedar
  incompleta.
- Es un asistente, no un sustituto de la revisión humana: puede pasar por
  alto problemas o, más raramente, señalar falsos positivos.

## Stack

- **Python** + [`requests`](https://pypi.org/project/requests/) como única
  dependencia externa.
- **GitHub Actions** para la orquestación (disparo en `pull_request`).
- **[Groq](https://groq.com)** como proveedor de inferencia gratuita,
  vía API compatible con OpenAI (`openai/gpt-oss-120b`).
- **API REST de GitHub** para leer el diff y publicar el comentario.

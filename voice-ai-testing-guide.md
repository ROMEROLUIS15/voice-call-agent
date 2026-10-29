# Guía Maestra de Pruebas: Carga, Estrés, Concurrencia y Alucinaciones para Agentes de Voz (Voice AI)

> **Sistema Auditado:** Voice Call Agent (Twilio Media Streams / WebRTC + Pipecat + Deepgram Flux STT + LLM OpenRouter/Groq + Deepgram Aura-2 TTS)  
> **Destino:** Integración SaaS Cronix / Call Center Concurrente  
> **Objetivo:** Detección de fallos de infraestructura, alucinaciones de citas y límites de concurrencia bajo llamadas telefónicas simultáneas  
> **Fecha:** Octubre 2026  
> **Documento PDF relacionado:** [`GUIA_PRUEBAS_VOICE_AI.pdf`](./GUIA_PRUEBAS_VOICE_AI.pdf)

---

## 1. El Reto Técnico: ¿Por qué Voice AI no se prueba como una API tradicional?

En una API REST o GraphQL tradicional, herramientas como **k6**, **JMeter** o **Postman** disparan miles de peticiones HTTP (GET/POST) y miden el tiempo de respuesta y los códigos de error (200 OK vs 500 Server Error).

Un **Agente de Voz en Tiempo Real** para un call center opera con un paradigma completamente distinto:

1. **Streaming Bidireccional Continuo en Tiempo Real:**  
   No son peticiones aisladas. La central telefónica (Twilio Media Streams o enlaces WebRTC) mantiene un socket dúplex abierto transmitiendo paquetes de audio (**G.711 &mu;-law a 8kHz** o **PCM a 16kHz/24kHz**) cada **20 milisegundos** de forma ininterrumpida.
2. **Pipeline en Cascada Multi-Proveedor:**  
   Cada turno de conversación involucra una cadena crítica:
   $$\text{VAD Local (Silero)} \longrightarrow \text{STT (Deepgram Flux)} \longrightarrow \text{LLM / Pipecat Flows} \longrightarrow \text{TTS (Deepgram Aura-2)} \longrightarrow \text{Telefonía}$$
   Un cuello de botella o jitter en cualquiera de los eslabones destruye la experiencia acústica o cuelga la llamada.
3. **La Doble Dimensión del Fallo en Producción:**
   * **Fallo de Infraestructura (Estrés de Red y Cómputo):**  
     Saturación del Event Loop de Python (`asyncio` / FastAPI) por el procesamiento simultáneo de tramas de audio, fugas de memoria por búferes no drenados y errores `429 Too Many Requests` en los proveedores de STT o LLM.
   * **Fallo Cognitivo (Alucinaciones y Máquina de Estados):**  
     Bajo carga alta o con clientes que hablan con pausas, tosen o interrumpen (*barge-in*), el LLM puede tardar segundos de más, saltarse herramientas, inventar horarios que no existen en Cronix o confirmar citas falsas.

---

## 2. Catálogo de Herramientas, Funcionalidad y Costos

### 1. Hamming AI (`hamming.ai`)
* **Categoría:** Plataforma Especializada en Voice AI & Call Centers (SaaS).
* **Propósito:** Pruebas E2E de estrés y regresión automatizada llamando a números telefónicos reales o simulados.
* **Cómo funciona:** Despliega "llamantes sintéticos" impulsados por IA que marcan a tu línea telefónica (vía PSTN/SIP o WebRTC). Estos bots hablan con voz natural, dudan, cambian de opinión, introducen ruido de fondo e interrumpen al agente para evaluar si el sistema resiste.
* **Qué fallos detecta:**
  * Alucinaciones de agendamiento y violación de reglas de negocio.
  * Métricas de latencia TTFA (*Time to First Audio*) en percentiles $P_{50}$, $P_{95}$ y $P_{99}$.
  * *Task Success Rate* (TSR): Porcentaje de llamadas que lograron agendar exitosamente frente a las que fallaron.
* **Costos y Planes:**
  * **Prueba Gratuita:** Sí (créditos de bienvenida de 100 a 250 minutos de llamadas simuladas al registrarse).
  * **Starter / Growth:** Entre **$200 y $500 USD/mes** (incluye 1,000 a 2,500 minutos de simulación).
  * **Enterprise / Call Center:** **$0.10 a $0.20 USD por minuto simulado**. Permite conectar tu propia cuenta de Twilio (*Bring Your Own Cloud / BYOC*) para no pagar comisiones telefónicas extra.

---

### 2. Coval (`coval.dev`)
* **Categoría:** Simulación Adversarial & Regresión de Flujos de Diálogo (SaaS).
* **Propósito:** Evaluación profunda de máquinas de estados complejas y diálogos con clientes difíciles. Creada por ex-líderes del equipo de simulación de vehículos autónomos de Waymo.
* **Cómo funciona:** Se integra de manera nativa con el stack de **Pipecat**, Deepgram y OpenAI/OpenRouter. Ejecuta cientos de conversaciones paralelas creando personas con comportamientos adversariales (clientes enfadados, que no cooperan o cambian de idea bruscamente).
* **Qué fallos detecta:**
  * Errores de transición de nodos en Pipecat Flows (como bloqueos de estado por interrupciones).
  * Argumentos malformados en llamadas a herramientas (e.g. `service_id` inexistentes).
  * Desvíos de contexto y reintentos fallidos en reservas.
* **Costos y Planes:**
  * **Developer Sandbox:** **Gratuito** (hasta 50-100 conversaciones de prueba por mes).
  * **Team Tier:** Desde **$250 a $499 USD/mes** con integración en pipelines de CI/CD.
  * **Enterprise:** Cotización anual para call centers con más de 10,000 simulaciones mensuales.

---

### 3. Locust con Client WebSocket de Audio (`locust.io`)
* **Categoría:** Open-Source / Carga y Estrés de Concurrencia de Red.
* **Propósito:** El verdadero sustituto open-source de k6 para streaming de voz.
* **Cómo funciona:** Se programa un usuario virtual en Python que establece conexiones WebSocket con tu endpoint `/twilio/stream`, envía el evento inicial `start` de Twilio y bombea paquetes de audio G.711 $\mu$-law cada 20 ms de forma sostenida, simulando 20, 50, 100 o 300 llamadas concurrentes contra tu servidor.
* **Qué fallos detecta:**
  * Saturación del Event Loop de FastAPI (determina el límite de llamadas antes de que la latencia se vuelva inaceptable).
  * Fugas de memoria RAM causadas por acumulación de búferes de audio.
  * Límites de descriptores de archivos y sockets del sistema operativo (`ulimit -n`).
* **Costos:**
  * **Licencia:** **100% GRATIS** (Open-Source bajo Licencia MIT).
  * **Infraestructura:** $0 en tu máquina local. Para generar cientos de conexiones distribuidas en la nube, entre **$15 y $40 USD** en un droplet de DigitalOcean o instancia AWS EC2.

---

### 4. SIPp (`sipp.sourceforge.net`)
* **Categoría:** Open-Source / Carga Telefónica SIP Tradicional.
* **Propósito:** El estándar de la industria de telecomunicaciones para saturar enlaces SIP Trunk y gateways de call center.
* **Cómo funciona:** Genera tráfico SIP nativo y flujos de medios RTP con audio codificado directamente contra los servidores telefónicos de Twilio o la PBX del call center.
* **Qué fallos detecta:** Pérdida de paquetes UDP de telefonía, jitter acústico, agotamiento de troncales SIP y límites de concurrencia de la compañía telefónica.
* **Costos:**
  * **Licencia:** **100% GRATIS** (Open-Source bajo Licencia GPL).
  * **Consumo:** Solo los costos de tu carrier si las llamadas salen a la red telefónica pública.

---

### 5. DeepEval (`deepeval.com` / Confident AI)
* **Categoría:** Open-Source / Evaluación Analítica de Transcripciones.
* **Propósito:** Calificación automatizada de calidad semántica mediante *LLM-as-a-Judge* (ya implementado en este repositorio en `evals/`).
* **Cómo funciona:** Tras finalizar las llamadas, un modelo juez (Gemini Flash o GPT-4o) analiza la transcripción completa y califica métricas como `invents-nothing`, `natural-spanish`, `brief-replies` y exactitud de herramientas.
* **Costos:**
  * **Librería Python:** **100% GRATIS** (Apache 2.0).
  * **Costo de Inferencia:** Solo los tokens de la API del juez (usando Gemini Flash directo con `GEMINI_API_KEY` son apenas centavos o gratis en el tier libre).
  * **Dashboard en la nube (Confident AI):** Opcional, capa gratuita para desarrolladores individuales; planes de equipo desde **$49 USD/mes**.

---

## 3. Matriz Comparativa de Capacidades y Costos

| Herramienta | Tipo de Prueba | Costo de Entrada | Detección de Alucinaciones | Simulación de Clientes Reales | Estrés de Concurrencia (WebSockets) |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Hamming AI** | E2E Telefónico + QA | $200 - $500/mes *(Free Trial)* | **Excelente (Automático)** | **Sí (Voces humanas sintéticas)** | Alta (Cientos de llamadas) |
| **Coval** | Simulación Diálogo Voice AI | $250 - $499/mes *(Free Tier)* | **Excelente (Adversarial)** | **Sí (Personas de prueba)** | Media / Alta |
| **Locust (Audio WS)** | Carga y Estrés de Servidor | **$0 (Open Source)** | No *(Solo métricas de red/CPU)* | No *(Inyección de audio)* | **Muy Alta (Miles de streams)** |
| **SIPp** | Carga Telefónica SIP | **$0 (Open Source)** | No *(Solo paquetes RTP)* | No *(Audio pregrabado)* | **Masiva (Troncales completas)** |
| **DeepEval** | LLM-as-a-Judge (Transcripción) | **$0 (Open Source)** | **Excelente (Semántico)** | No *(Post-llamada)* | No *(Evaluación analítica)* |

---

## 4. ¿En qué etapas del proyecto usar cada herramienta?

### Fase 1: Desarrollo Activo y CI/CD (Fase Actual)
* **Objetivo:** Asegurar que ningún cambio de código o prompt rompa la máquina de estados sin gastar presupuesto en telefonía.
* **Herramientas:** **Golden Dataset + DeepEval** (ambas ya configuradas en el repositorio).
* **Acción:**
  * Correr las pruebas conversacionales en loopback local (`uv run pytest tests/evals tests/snapshots`).
  * Utilizar el flag `--only-if-changed` en el CI de GitHub Actions para evaluar únicamente cuando la huella de comportamiento (*fingerprint*) haya cambiado.
* **Costo estimado:** **$0 USD** (o fracciones de centavo en tokens del juez).

---

### Fase 2: Conexión con Cronix SaaS & Staging (Pre-Producción)
* **Objetivo:** Validar la resiliencia del servidor bajo concurrencia media y verificar que las citas se guarden efectivamente en la base de datos de Cronix.
* **Herramientas:** **Locust (Script de Audio) + Coval (Developer Sandbox)**.
* **Acción:**
  1. Ejecutar una prueba con **Locust** simulando de 20 a 50 conexiones simultáneas a `/twilio/stream` para calibrar el parámetro `MAX_CONCURRENT_CALLS` del `CallSupervisor`.
  2. Lanzar 50 simulaciones en **Coval** para verificar que tras decir "Sí/Correcto", la cita se inserte atómicamente en la base de datos de Cronix sin falsos positivos (`outcome: booked`).
* **Costo estimado:** **$0 a $50 USD** (usando tiers gratuitos y un VPS de prueba).

---

### Fase 3: Producción & Call Center a Gran Escala (Operación Comercial)
* **Objetivo:** Garantizar que cuando decenas de clientes reales llamen a la vez en hora pico, la calidad acústica no se degrade y ninguna cita se pierda.
* **Herramientas:** **Hamming AI + Monitoreo Sentry/Call Traces**.
* **Acción:**
  1. Programar campañas de estrés semanales en **Hamming AI** donde agentes sintéticos llamen concurrentemente a las líneas telefónicas reales de Cronix.
  2. Monitorear que el percentil $P_{95}$ de latencia se mantenga bajo los 1,800 ms y la tasa de resolución supere el 95%.
  3. Cada vez que una llamada en producción falle, exportar la transcripción y convertirla inmediatamente en un caso del Golden Dataset (`evals/golden_dataset/*.yaml`) para evitar regresiones.
* **Costo estimado:** **$250 a $500 USD/mes** (justificado como seguro de calidad para la operación comercial del call center).

---

## 5. Script Base de Locust para Twilio Media Streams

Para implementar la prueba de estrés de infraestructura en Fase 2 sin costo, utiliza el siguiente script base en Python (`locustfile.py`):

```python
import base64
import json
import time
import uuid
from locust import User, events, task
import websocket

# Chunk de 20ms de audio G.711 mu-law (8kHz * 0.02s = 160 bytes de silencio/tono)
SAMPLE_AUDIO_CHUNK = base64.b64encode(b"\xff" * 160).decode("utf-8")

class TwilioMediaStreamUser(User):
    def on_start(self):
        ws_url = self.host or "ws://localhost:8000/twilio/stream"
        start_time = time.time()
        try:
            self.ws = websocket.create_connection(ws_url)
            events.request.fire(
                request_type="WebSocket",
                name="Handshake",
                response_time=(time.time() - start_time) * 1000,
                response_length=0,
                exception=None,
            )
        except Exception as e:
            events.request.fire(
                request_type="WebSocket",
                name="Handshake",
                response_time=0,
                response_length=0,
                exception=e,
            )
            self.ws = None

    def on_stop(self):
        if self.ws:
            self.ws.close()

    @task
    def simulate_voice_call(self):
        if not self.ws:
            return

        call_sid = f"CA{uuid.uuid4().hex[:32]}"
        stream_sid = f"MZ{uuid.uuid4().hex[:32]}"

        # 1. Enviar evento de inicio (Start Event de Twilio)
        start_event = {
            "event": "start",
            "sequenceNumber": "1",
            "start": {
                "streamSid": stream_sid,
                "callSid": call_sid,
                "tracks": ["inbound"],
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "channels": 1
                },
                "customParameters": {"from": "+584120000000", "to": "+13050000000"}
            },
            "streamSid": stream_sid
        }
        self.ws.send(json.dumps(start_event))

        # 2. Transmitir paquetes de audio cada 20 ms (500 paquetes = 10 segundos)
        for seq in range(2, 502):
            media_event = {
                "event": "media",
                "sequenceNumber": str(seq),
                "media": {
                    "track": "inbound",
                    "chunk": str(seq - 1),
                    "payload": SAMPLE_AUDIO_CHUNK
                },
                "streamSid": stream_sid
            }
            self.ws.send(json.dumps(media_event))
            time.sleep(0.020)  # Pacing idéntico a telefonía real

        # 3. Finalizar la llamada (Stop Event)
        stop_event = {
            "event": "stop",
            "sequenceNumber": "503",
            "streamSid": stream_sid,
            "stop": {"callSid": call_sid}
        }
        self.ws.send(json.dumps(stop_event))
        self.interrupt()
```

Ejecutar localmente:
```bash
pip install locust websocket-client
locust -f locustfile.py --host=ws://localhost:8000
```

---

## 6. Checklist de Arquitectura para el Call Center
* [ ] **Workers Múltiples:** Uvicorn en un solo proceso no soporta más de 20-30 llamadas concurrentes de audio continuo en Python. Desplegar múltiples workers o contenedores Docker balanceados con Nginx o Traefik.
* [ ] **Almacén de Rate Limiting Compartido:** Configurar `RATE_LIMIT_STORAGE_URI` apuntando a Redis para que el control de concurrencia sea global entre todos los workers.
* [ ] **Límite Concurrente Calibrado:** Ajustar `MAX_CONCURRENT_CALLS` en `CallSupervisor` al 80% de la capacidad probada con Locust para rechazar con tono de ocupado antes de que el servidor degrade el audio.
* [ ] **Alertas de Latencia P95:** Configurar alertas en Sentry cuando la latencia por turno supere los 2,000 ms en `var/call_traces.jsonl`.


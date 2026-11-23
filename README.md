# BIST Agentic Financial Analytics Harness

CSE-481 Mühendislik Ekonomisi dönem projesi. Türkçe sorulan BIST sorularını yerel bir LLM (`bist-analist`,
Qwen3.5-4B QLoRA) ve deterministik Python araçlarıyla, tarih kilitli (point-in-time) veriden cevaplar; her sayı
kanıtlı, yatırım tavsiyesi yok. Ayrıntılı tasarım ve kurallar: [CLAUDE.md](CLAUDE.md).

## Docker ile çalıştırma (önerilen)

Gerekenler: Docker Desktop (WSL2) + NVIDIA GPU sürücüsü (≥ 6 GB VRAM önerilir; GPU yoksa CPU'da yavaş çalışır).

Git'e girmeyen iki dosyayı yerleştirin (indirme bağlantıları ayrıca paylaşılır):

```
data/db/bist.sqlite            # fiyat, KAP bilançoları, makro, haber metadatası (~74 MB)
models/bist-4b-q8_0.gguf       # ince ayarlı model (~4,5 GB)
```

Sonra:

```
docker compose up --build
```

İlk açılışta `model-init` modeli Ollama'ya `bist-analist` adıyla kaydeder. Arayüz: <http://localhost:8501>.
Analiz kayıtları `data/db/episodic.sqlite` dosyasına yazılır.

GPU'suz makinede `docker-compose.yml` içindeki `deploy:` bloğunu silin.

## Yerel geliştirme

```
uv sync --extra dev --extra llm --extra ui --extra mcp
uv run pytest -q
uv run streamlit run src/bistharness/ui/app.py
```

Değerlendirme komutları ve veri ingest adımları: CLAUDE.md §12.

# BIST Agentic Financial Analytics Harness

CSE-481 Mühendislik Ekonomisi dönem projesi. Türkçe sorulan BIST sorularını yerel bir LLM (`bist-analist`,
Qwen3.5-4B QLoRA) ve deterministik Python araçlarıyla, tarih kilitli (point-in-time) veriden cevaplar; her sayı
kanıtlı, yatırım tavsiyesi yok. Ayrıntılı tasarım ve kurallar: [CLAUDE.md](CLAUDE.md).

## Docker ile çalıştırma (önerilen)

Gerekenler: Docker Desktop (WSL2) + NVIDIA GPU sürücüsü (≥ 6 GB VRAM önerilir; GPU yoksa CPU'da yavaş çalışır).

Git'e girmeyen iki dosya deponun gizli GitHub Release'inde (`assets-2026-11-20`); betik indirir, sha256'yı
doğrular ve yerine koyar (`gh auth login` gerekir):

```
powershell -ExecutionPolicy Bypass -File setup\get_assets.ps1
# -> data/db/bist.sqlite (fiyat, KAP, makro, haber metadatası, ~74 MB) + models/bist-4b-q8_0.gguf (~4,5 GB)
```

Video katmanı üzerinde çalışacaklar için devir rehberi: [docs/VIDEO_KATMANI_REHBERI.md](docs/VIDEO_KATMANI_REHBERI.md).

Sonra:

```
docker compose up --build
```

İlk açılışta `model-init` modeli Ollama'ya `bist-analist` adıyla kaydeder. Arayüz (FinTreX Analyst): <http://localhost:8501>.
Analiz kayıtları `data/db/episodic.sqlite` dosyasına yazılır.

GPU'suz makinede `docker-compose.yml` içindeki `deploy:` bloğunu silin.

## Yerel geliştirme

```
uv sync --extra dev --extra llm --extra ui --extra mcp
uv run pytest -q
uv run python -m bistharness.ui.web     # FinTreX Analyst -> http://127.0.0.1:8501 (tarayıcıyı açar)
```

Değerlendirme komutları ve veri ingest adımları: CLAUDE.md §12.

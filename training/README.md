# Fine-tuning (QLoRA) — çalıştırma notları

Veri seti proje ortamında üretilir (GPU gerekmez):

```
uv run python -m training.generate_dataset --n-explain 3500 --n-intent-extra 500 --workers 8
```

Eğitim GPU kütüphaneleri ister (torch + CUDA, unsloth, trl, peft, bitsandbytes); bunlar proje `uv` ortamında
**değildir**. Ayrı bir ortam kurulur:

```
python -m venv .venv-train
.venv-train\Scripts\activate          # Linux/WSL: source .venv-train/bin/activate
pip install -r training/requirements.txt
```

1. Süre ölçümü (yaklaşık 10 dakika): `python training/train_qlora.py --base unsloth/Qwen3.5-4B --pilot-steps 20`
2. Tam eğitim ve Ollama dosyası:
   `python training/train_qlora.py --base <taban> --epochs 2 --gguf q4_k_m --out training/output/<ad>`
3. Ollama'ya ekleme: `ollama create bist-analist -f training/output/<ad>/Modelfile`
4. Karşılaştırma: `uv run python -m eval.bakeoff --models <taban>,bist-analist`

Kiralık GPU'da (RunPod / Thunder Compute) aynı komutlar çalışır: proje klasörü (yalnız `training/` ve `training/data/`)
yüklenir, eğitim yapılır, `training/output/<ad>/gguf/*.gguf` ve `Modelfile` geri indirilir. Bulutta yalnızca eğitim
yapılır; çıkarım her zaman bu bilgisayarda, çevrimdışı çalışır (CLAUDE.md §1.1).

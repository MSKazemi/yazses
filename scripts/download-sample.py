import urllib.request
from pathlib import Path


def main():
    target_dir = Path("data/librispeech-sample")
    target_dir.mkdir(parents=True, exist_ok=True)
    
    samples = [
        {
            "url": "https://raw.githubusercontent.com/ggerganov/whisper.cpp/master/samples/jfk.wav",
            "filename": "jfk.wav",
            "text": "And so my fellow Americans ask not what your country can do for you ask what you can do for your country."
        }
    ]
    
    for sample in samples:
        wav_path = target_dir / sample["filename"]
        txt_path = target_dir / f"{wav_path.stem}.txt"
        
        if not wav_path.exists():
            print(f"Downloading {sample['filename']}...")
            urllib.request.urlretrieve(sample["url"], wav_path)
            
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(sample["text"])
            
    print(f"Sample dataset ready in {target_dir}")
    print("Run benchmark with:")
    print(f"uv run python scripts/bench-stt.py {target_dir} --engine faster-whisper --model base.en")

if __name__ == "__main__":
    main()

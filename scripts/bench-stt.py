"""STT Benchmark Harness.

Measures WER (Word Error Rate), RTF (Real Time Factor), and peak RSS.
Usage:
    uv run python scripts/bench-stt.py data/librispeech-sample --engine faster-whisper --model base.en
"""
import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Ensure yazses is in pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import jiwer
except ImportError:
    print("Error: jiwer is not installed. Run: uv pip install jiwer")
    sys.exit(1)

def get_peak_rss_mb() -> float:
    try:
        import psutil
        process = psutil.Process(os.getpid())
        if hasattr(process.memory_info(), 'peak_wset'):
            return process.memory_info().peak_wset / (1024 * 1024)
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        try:
            import resource
            # ru_maxrss is kilobytes on Linux and *bytes* on macOS/BSD. This number
            # goes into a published comparison table, so getting the unit wrong would
            # not look like a bug — it would look like a Mac using 1/1024th the memory.
            divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor
        except ImportError:
            return 0.0

@dataclass
class MockConfig:
    engine: str
    model: str
    language: str
    device: str
    compute_type: str

def main():
    parser = argparse.ArgumentParser(description="Run STT Benchmark on a directory of WAV and TXT files.")
    parser.add_argument("dataset", type=Path, help="Directory containing .wav and .txt reference files")
    parser.add_argument("--engine", type=str, default="faster-whisper", help="Engine to use (faster-whisper, parakeet)")
    parser.add_argument("--model", type=str, default="base.en", help="Model name (e.g., base.en, tiny.en)")
    parser.add_argument("--device", type=str, default="cpu", help="Device (cpu, cuda, auto)")
    parser.add_argument("--compute-type", type=str, default="int8", help="Compute type (int8, float16)")
    args = parser.parse_args()

    if not args.dataset.exists() or not args.dataset.is_dir():
        print(f"Error: Dataset directory {args.dataset} not found.")
        sys.exit(1)

    print(f"Loading engine: {args.engine} (model: {args.model})...")
    from yazses.recimport.audio_io import load_audio
    from yazses.stt.factory import build_engine
    
    stt_config = MockConfig(
        engine=args.engine,
        model=args.model,
        language="en",
        device=args.device,
        compute_type=args.compute_type
    )
    
    engine = build_engine(stt_config)
    
    # Warmup
    print("Warming up engine...")
    dummy_audio = np.zeros(16000, dtype=np.float32)
    engine.transcribe(dummy_audio, 16000)
    
    wav_files = list(args.dataset.glob("*.wav"))
    if not wav_files:
        print(f"No .wav files found in {args.dataset}")
        sys.exit(1)
        
    total_audio_duration = 0.0
    total_decode_time = 0.0
    references = []
    hypotheses = []
    
    print(f"Found {len(wav_files)} files. Starting benchmark...")
    
    for wav_path in wav_files:
        txt_path = wav_path.with_suffix(".txt")
        if not txt_path.exists():
            print(f"Warning: Missing reference text for {wav_path.name}, skipping.")
            continue
            
        with open(txt_path, "r", encoding="utf-8") as f:
            reference = f.read().strip()
            
        # The project already has a decoder that returns mono float32 at a requested
        # rate, via PyAV with an ffmpeg fallback and no dependency beyond the base
        # install (`recimport/audio_io.py`). Reading with `soundfile` instead would add
        # an install step for a dev script and, because it does not resample, made the
        # harness silently *skip* every dataset that is not already 16 kHz — which is
        # most of them, LibriSpeech included.
        try:
            audio, sr = load_audio(wav_path, 16000)
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"Warning: could not decode {wav_path.name}: {exc}")
            continue

        duration = len(audio) / sr
        if duration <= 0:
            print(f"Warning: {wav_path.name} decoded to no audio, skipping.")
            continue

        start_time = time.perf_counter()
        hypothesis = engine.transcribe(audio, 16000)
        decode_time = time.perf_counter() - start_time
        
        total_audio_duration += duration
        total_decode_time += decode_time
        
        references.append(reference.lower())
        hypotheses.append(hypothesis.lower().strip())
        
        print(f"[{wav_path.name}] duration={duration:.2f}s decode={decode_time:.2f}s RTF={decode_time/duration:.3f}")
        
    if not references:
        print("No valid file pairs found.")
        sys.exit(1)
        
    wer = jiwer.wer(references, hypotheses)
    rtf = total_decode_time / total_audio_duration
    peak_rss = get_peak_rss_mb()
    
    print("\n--- Benchmark Results ---")
    print(f"Dataset Size : {len(references)} files ({total_audio_duration:.2f}s total audio)")
    print(f"Engine       : {args.engine}")
    print(f"Model        : {args.model}")
    print(f"WER          : {wer * 100:.2f}%")
    print(f"Overall RTF  : {rtf:.3f}x")
    if peak_rss > 0:
        print(f"Peak RSS     : {peak_rss:.1f} MB")
    else:
        print("Peak RSS     : N/A (psutil or resource not available)")
        
    print("\nMarkdown Table Row:")
    rss_str = f"{peak_rss:.1f} MB" if peak_rss > 0 else "N/A"
    print(f"| CPU/GPU | `{args.engine}` (`{args.model}`) | {wer * 100:.1f}% | {rtf:.2f}x | {rss_str} |")

if __name__ == "__main__":
    main()

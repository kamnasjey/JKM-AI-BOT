#!/usr/bin/env python3
"""
Deduplicate signals.jsonl by removing duplicate entries with same
symbol + tf + direction + entry + sl + tp combination.
Keeps only the first occurrence of each unique signal.
"""
import json
import sys
from pathlib import Path

def dedupe_signals(input_path: str, output_path: str) -> dict:
    """Remove duplicate signals and write to output file."""
    seen = set()
    duplicates = 0
    kept = 0
    
    with open(input_path, 'r', encoding='utf-8') as f_in:
        with open(output_path, 'w', encoding='utf-8') as f_out:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue
                try:
                    sig = json.loads(line)
                    # Create unique key from symbol, tf, direction, entry, sl, tp
                    key = (
                        sig.get('symbol', ''),
                        sig.get('tf', ''),
                        sig.get('direction', ''),
                        round(float(sig.get('entry', 0)), 5),
                        round(float(sig.get('sl', 0)), 5),
                        round(float(sig.get('tp', 0)), 5),
                    )
                    if key in seen:
                        duplicates += 1
                        continue
                    seen.add(key)
                    f_out.write(line + '\n')
                    kept += 1
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    print(f"Skipping malformed line: {e}", file=sys.stderr)
    
    return {'kept': kept, 'duplicates': duplicates}

if __name__ == '__main__':
    for filename in ['signals.jsonl', 'signals_v1.jsonl']:
        input_file = f'/opt/JKM-AI-BOT/state/{filename}'
        output_file = f'/opt/JKM-AI-BOT/state/{filename}.deduped'
        
        if not Path(input_file).exists():
            print(f"File not found: {input_file}")
            continue
            
        result = dedupe_signals(input_file, output_file)
        print(f"{filename}: kept={result['kept']}, removed={result['duplicates']}")
        
        # Replace original with deduped version
        Path(output_file).replace(input_file)
        print(f"  -> Replaced {filename} with deduped version")

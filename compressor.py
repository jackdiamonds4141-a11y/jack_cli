import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: google-genai library is not installed in the current environment.")
    sys.exit(1)

COMPRESSION_PROMPT = """You are a Tactical Search Heuristic Extractor.
Task: Convert the provided raw text chunk into a highly compressed, telegraphic, machine-readable JSON search heuristic.

Strict Rules:
1. Strip all human grammar, academic hedging, introductory framing, and conversational filler.
2. Output ONLY a raw JSON object matching the schema.
3. Keep all text in the fields extremely telegraphic (e.g., "Verify EXIF" instead of "It is important to verify the EXIF data").
4. The output JSON must match exactly this schema:
{{
  "query_rules": [
    {{
      "pattern": "Syntactic query pattern, e.g., site:archive.org '{{query}}'",
      "engine": "searxng or google or specific platform",
      "example": "Concrete example query matching the pattern"
    }}
  ],
  "source_targets": [
    "Target sources/platforms to search, e.g., r/leaks, archive.org"
  ],
  "anti_hallucination_gates": [
    {{
      "check": "Specific verification/validation check rule"
    }}
  ]
}}

Input Chunk:
Source ID: {source_id}
Domain: {domain}
Metadata: {structural_meta}
Content:
{content}
"""

def _load_env_var(var_name: str) -> Optional[str]:
    """Load environmental variable from OS or local .env file."""
    if var_name in os.environ:
        return os.environ[var_name]
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key.strip() == var_name:
                    return val.strip().strip('"').strip("'")
    return None


class APIKeyManager:
    """Hot-Standby Key Manager specifically for compression task rotation."""
    def __init__(self):
        self.keys = []
        self.clients = {}
        for env_name in ["GEMINI_API_KEY", "API_KEY_FALLBACK_1", "API_KEY_FALLBACK_2"]:
            val = _load_env_var(env_name)
            if val:
                self.keys.append({
                    "env_name": env_name,
                    "key": val,
                    "is_cooling": False,
                    "cooldown_until": 0.0
                })
                self.clients[val] = genai.Client(api_key=val)
                
        if not self.keys:
            print("[APIKeyManager] CRITICAL: No API keys loaded! Check your .env file.")
            sys.exit(1)
            
    def get_client(self) -> tuple:
        now = time.time()
        for i, entry in enumerate(self.keys):
            if entry["is_cooling"] and now >= entry["cooldown_until"]:
                entry["is_cooling"] = False
                
        for i, entry in enumerate(self.keys):
            if not entry["is_cooling"]:
                return self.clients[entry["key"]], i
                
        # All cooling - pick the one with shortest remaining wait
        soonest = min(self.keys, key=lambda e: e["cooldown_until"])
        wait_time = soonest["cooldown_until"] - now
        if wait_time > 0:
            print(f"[APIKeyManager] All keys cooling. Waiting {wait_time:.1f}s for {soonest['env_name']}...")
            time.sleep(wait_time)
        soonest["is_cooling"] = False
        return self.clients[soonest["key"]], self.keys.index(soonest)
        
    def report_rate_limited(self, idx: int):
        entry = self.keys[idx]
        entry["is_cooling"] = True
        entry["cooldown_until"] = time.time() + 60.0
        print(f"[APIKeyManager] Key {entry['env_name']} rate limited. Cooling for 60s.")


class TacticalCompressor:
    def __init__(self, chunks_path: Path, output_path: Path, model_name: str = "gemini-2.5-flash"):
        self.chunks_path = Path(chunks_path)
        self.output_path = Path(output_path)
        self.model_name = model_name
        self.key_manager = APIKeyManager()
        
    def compress_chunk(self, chunk: Dict[str, Any]) -> Dict[str, Any]:
        content = chunk.get("content", "")
        # Truncate content to 4000 characters to prevent context overflow
        if len(content) > 4000:
            content = content[:4000]
            
        prompt = COMPRESSION_PROMPT.format(
            source_id=chunk.get("source_id", "unknown"),
            domain=chunk.get("domain", "unknown"),
            structural_meta=json.dumps(chunk.get("structural_meta", {})),
            content=content
        )
        
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0
        )
        
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            client, key_idx = self.key_manager.get_client()
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config
                )
                
                response_text = response.text.strip() if response.text else ""
                if not response_text:
                    raise ValueError("Empty response received from Gemini API.")
                
                # Parse JSON output
                heuristic = json.loads(response_text)
                
                # Verify required structure keys
                for k in ["query_rules", "source_targets", "anti_hallucination_gates"]:
                    if k not in heuristic:
                        heuristic[k] = []
                return heuristic
                
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    self.key_manager.report_rate_limited(key_idx)
                    continue
                else:
                    print(f"Error compressing chunk (Attempt {attempt}/{max_retries}): {e}")
                    if attempt == max_retries:
                        raise e
                    time.sleep(2.0)
                    
        raise RuntimeError("Failed to compress chunk after all retries.")

    def process_batches(self, limit: int = None) -> List[Dict[str, Any]]:
        if not self.chunks_path.exists():
            print(f"Error: {self.chunks_path} not found!")
            sys.exit(1)
            
        with open(self.chunks_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
            
        if limit:
            chunks = chunks[:limit]
            print(f"Running compression pipeline on first {limit} chunks using Google Gemini API...")
            
        compressed_results = []
        for i, chunk in enumerate(chunks):
            print(f"Compressing chunk {i+1}/{len(chunks)} ({chunk.get('source_id')})...")
            # Compress chunk content using Gemini API
            compressed_heuristics = self.compress_chunk(chunk)
            
            # Build and append the final object with immutable provenance tags
            final_obj = {
                "source_id": chunk.get("source_id"),
                "domain": chunk.get("domain"),
                "structural_meta": chunk.get("structural_meta"),
                "query_rules": compressed_heuristics.get("query_rules", []),
                "source_targets": compressed_heuristics.get("source_targets", []),
                "anti_hallucination_gates": compressed_heuristics.get("anti_hallucination_gates", [])
            }
            compressed_results.append(final_obj)
            
        # Ensure output directory exists and write results
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(compressed_results, f, indent=2, ensure_ascii=False)
            
        print(f"\n[TacticalCompressor] Successfully wrote {len(compressed_results)} REAL compressed heuristics to {self.output_path}\n")
        return compressed_results


if __name__ == "__main__":
    base_dir = Path(__file__).parent
    chunks_json = base_dir / "Reasoning sources" / "ingested" / "chunks.json"
    output_json = base_dir / "wiki" / "raw_compressed_heuristics.json"
    
    # Instantiates the pipeline
    compressor = TacticalCompressor(chunks_json, output_json, model_name="gemini-2.5-flash")
    
    # Execute test run on the first 10 chunks to overwrite placeholder data
    compressor.process_batches(limit=10)

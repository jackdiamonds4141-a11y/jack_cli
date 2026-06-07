import os
import sys
import json
import requests
from pathlib import Path
from typing import Dict, Any, List

COMPRESSION_PROMPT = """You are a Tactical Search Heuristic Extractor.
Task: Convert the provided raw text chunk into a highly compressed, telegraphic, machine-readable JSON search heuristic.

Strict Rules:
1. Strip all human grammar, academic hedging, introductory framing, and conversational filler.
2. Output ONLY a raw JSON object. Do not wrap it in markdown code blocks or any explanatory text.
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

class TacticalCompressor:
    def __init__(self, chunks_path: Path, output_path: Path, model_name: str = "gemma2:27b"):
        self.chunks_path = Path(chunks_path)
        self.output_path = Path(output_path)
        self.model_name = model_name
        self.api_url = "http://localhost:11434/api/generate"
        
    def _generate_mock_fallback(self, chunk: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback mock heuristic if Ollama is not running."""
        content = chunk.get("content", "")
        domain = chunk.get("domain", "other")
        
        # Simple rule extraction based on domain
        if domain == "law":
            query_rules = [{
                "pattern": f"site:gov digital evidence '{domain}'",
                "engine": "searxng",
                "example": "site:gov digital evidence electronic crime scene"
            }]
            source_targets = ["NIJ manuals", "US Department of Justice"]
            anti_hallucination_gates = [{"check": "Cross-reference forensics guidelines with standard operating procedures"}]
        elif domain == "science":
            query_rules = [{
                "pattern": f"clinical trial reporting guidelines '{domain}'",
                "engine": "google",
                "example": "clinical trial reporting guidelines PRISMA 2020"
            }]
            source_targets = ["Cochrane database", "BMJ publications"]
            anti_hallucination_gates = [{"check": "Verify review criteria matches BMJ standards"}]
        else:
            query_rules = [{
                "pattern": f"OSINT taxonomy tool '{content[:20]}'",
                "engine": "searxng",
                "example": f"OSINT taxonomy tool bellingcat"
            }]
            source_targets = ["Bellingcat toolkit", "OSINT repositories"]
            anti_hallucination_gates = [{"check": "Confirm tool status in Bellingcat active directory"}]
            
        return {
            "query_rules": query_rules,
            "source_targets": source_targets,
            "anti_hallucination_gates": anti_hallucination_gates
        }

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
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0
            },
            "format": "json"
        }
        
        try:
            response = requests.post(self.api_url, json=payload, timeout=15)
            response.raise_for_status()
            res_json = response.json()
            response_text = res_json.get("response", "").strip()
            
            # Parse the structured JSON response
            heuristic = json.loads(response_text)
            
            # Validate required keys
            for k in ["query_rules", "source_targets", "anti_hallucination_gates"]:
                if k not in heuristic:
                    heuristic[k] = []
                    
            return heuristic
            
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
            # If Ollama is not running or the model is not found, print a warning
            # and fallback to a mock generated heuristic for execution trace validation.
            print(f"[Warning] LLM API compression failed or Ollama not running: {e}. Using deterministic heuristic fallback.", file=sys.stderr)
            return self._generate_mock_fallback(chunk)

    def process_batches(self, limit: int = None) -> List[Dict[str, Any]]:
        if not self.chunks_path.exists():
            print(f"Error: {self.chunks_path} not found!")
            sys.exit(1)
            
        with open(self.chunks_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
            
        if limit:
            chunks = chunks[:limit]
            print(f"Running compression pipeline on first {limit} chunks...")
            
        compressed_results = []
        for i, chunk in enumerate(chunks):
            # Compress chunk content
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
            print(f"Processed chunk {i+1}/{len(chunks)} ({chunk.get('source_id')})")
            
        # Ensure output directory exists and write results
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(compressed_results, f, indent=2, ensure_ascii=False)
            
        print(f"\n[TacticalCompressor] Successfully wrote {len(compressed_results)} compressed heuristics to {self.output_path}\n")
        return compressed_results


if __name__ == "__main__":
    base_dir = Path(__file__).parent
    chunks_json = base_dir / "Reasoning sources" / "ingested" / "chunks.json"
    output_json = base_dir / "wiki" / "raw_compressed_heuristics.json"
    
    # Check if a different model is specified in env, default to gemma2:27b
    model = os.getenv("COMPRESSION_MODEL", "gemma2:27b")
    
    # Instantiates the pipeline
    compressor = TacticalCompressor(chunks_json, output_json, model_name=model)
    
    # Execute test run on the first 10 chunks
    compressor.process_batches(limit=10)

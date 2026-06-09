"""
Layer 0 Recon Router — Epistemic Query Interface
=================================================
Loads the compiled wiki/index.json routing table and domain-specific
heuristic databases. Routes a user's task description to the most
relevant domain files using O(1) hash lookup + Jaccard keyword
similarity, then instantiates up to 5 targeted SearxNG search queries.

This module does NOT use any LLM calls. All routing is done via
local Python dictionary lookups and set operations for <200ms latency.
"""

import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple


class ReconRouter:
    def __init__(self, wiki_dir: Path = None):
        if wiki_dir is None:
            wiki_dir = Path(__file__).parent / "wiki"
        self.wiki_dir = Path(wiki_dir)
        self.index: Dict[str, Any] = {}
        self.db_cache: Dict[str, Dict[str, Any]] = {}  # path -> loaded JSON
        self._load_index()
        
    def _load_index(self):
        """Load the master routing index into memory."""
        index_path = self.wiki_dir / "index.json"
        if not index_path.exists():
            raise FileNotFoundError(f"Master index not found at {index_path}. Run database_builder.py first.")
        with open(index_path, "r", encoding="utf-8") as f:
            self.index = json.load(f)
            
    def _load_db_file(self, relative_path: str) -> Dict[str, Any]:
        """Load and cache a domain database file."""
        if relative_path in self.db_cache:
            return self.db_cache[relative_path]
        # relative_path is like "wiki/law/evidence_aquisition.json"
        # Resolve it relative to the parent of wiki_dir
        abs_path = self.wiki_dir.parent / relative_path
        if not abs_path.exists():
            return {}
        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.db_cache[relative_path] = data
        return data
        
    def _tokenize(self, text: str) -> Set[str]:
        """Extract lowercase keyword tokens from text."""
        # Strip punctuation, split on whitespace, filter short tokens
        words = re.findall(r'[a-zA-Z0-9]+', text.lower())
        return {w for w in words if len(w) > 2}
        
    def _jaccard_similarity(self, set_a: Set[str], set_b: Set[str]) -> float:
        """Compute Jaccard similarity between two token sets."""
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)
        
    def _extract_nouns(self, text: str) -> List[str]:
        """Extract likely noun phrases from the task description.
        Uses heuristics: ALL-CAPS words (KFC, FBI), capitalized words,
        quoted phrases, and words >2 chars that aren't common stop words.
        Preserves possessives (KFC's -> KFC).
        """
        stop_words = {
            "find", "search", "look", "help", "want", "need", "about",
            "what", "where", "when", "which", "that", "this", "with",
            "from", "have", "been", "were", "their", "they", "them",
            "will", "would", "could", "should", "there", "here", "some",
            "into", "also", "just", "than", "then", "very", "much",
            "make", "like", "does", "doing", "done", "being", "because",
            "through", "between", "after", "before", "during", "without",
        }
        
        # Extract quoted phrases first
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", text)
        
        # Clean possessives (KFC's -> KFC)
        cleaned = re.sub(r"'s\b", "", text)
        
        # Extract remaining significant words
        words = re.findall(r'[a-zA-Z0-9]+', cleaned)
        nouns = []
        for w in words:
            # Always keep ALL-CAPS words (proper nouns/acronyms: KFC, FBI, CIA)
            if w.isupper() and len(w) >= 2:
                nouns.append(w)
            elif w.lower() not in stop_words and len(w) > 2:
                nouns.append(w)
                
        # Quoted phrases take priority
        return quoted + nouns
        
    def _resolve_domain_files(self, prompt_tokens: Set[str]) -> List[Tuple[str, float]]:
        """
        Two-stage domain file resolution:
        Stage 1: O(1) hash lookup in quick_lookup for exact keyword matches.
        Stage 2: Jaccard similarity against all domain keywords for fuzzy matching.
        Returns a ranked list of (file_path, score) tuples.
        """
        quick_lookup = self.index.get("quick_lookup", {})
        domains = self.index.get("domains", {})
        
        scored_files: Dict[str, float] = {}
        
        # Stage 1: O(1) direct keyword hits
        for token in prompt_tokens:
            if token in quick_lookup:
                for file_path in quick_lookup[token]:
                    scored_files[file_path] = scored_files.get(file_path, 0) + 2.0  # High weight for direct hit
                    
        # Stage 2: Jaccard similarity across all domain keywords
        all_keywords = set(quick_lookup.keys())
        if all_keywords:
            jaccard = self._jaccard_similarity(prompt_tokens, all_keywords)
            if jaccard > 0:
                # Boost all files proportionally
                for domain, files in domains.items():
                    domain_tokens = {token for token in all_keywords 
                                    if any(fp in quick_lookup.get(token, []) for fp in files)}
                    domain_jaccard = self._jaccard_similarity(prompt_tokens, domain_tokens)
                    for fp in files:
                        scored_files[fp] = scored_files.get(fp, 0) + domain_jaccard
                        
        # If nothing matched, load ALL domain files as fallback
        if not scored_files:
            for domain, files in domains.items():
                for fp in files:
                    scored_files[fp] = 0.1  # Low default score
                    
        # Sort by score descending
        ranked = sorted(scored_files.items(), key=lambda x: x[1], reverse=True)
        return ranked
        
    def _instantiate_queries(self, query_rules: List[Dict], source_targets: List[str],
                             gates: List[Dict], nouns: List[str], limit: int = 5) -> List[str]:
        """
        Generate concrete SearxNG search queries by instantiating templates.
        Uses query_rules templates if available, otherwise synthesizes
        tactical queries from source_targets and anti_hallucination_gates.
        """
        queries = []
        
        # Primary path: Instantiate query_rule templates with extracted nouns
        if query_rules:
            primary_noun = nouns[0] if nouns else "target"
            secondary_noun = nouns[1] if len(nouns) > 1 else primary_noun
            
            for rule in query_rules:
                pattern = rule.get("pattern", "")
                # Replace template variables with actual nouns
                instantiated = pattern
                instantiated = re.sub(r'\{query\}', primary_noun, instantiated)
                instantiated = re.sub(r'\{target_name\}', primary_noun, instantiated)
                instantiated = re.sub(r'\{suspect\}', primary_noun, instantiated)
                instantiated = re.sub(r'\{domain\}', secondary_noun, instantiated)
                instantiated = re.sub(r'\{subreddit\}', secondary_noun, instantiated)
                instantiated = re.sub(r'\{pop_syn1\}', primary_noun, instantiated)
                instantiated = re.sub(r'\{pop_syn2\}', secondary_noun, instantiated)
                instantiated = re.sub(r'\{int_syn1\}', secondary_noun, instantiated)
                queries.append(instantiated)
                if len(queries) >= limit:
                    break
                    
        # Fallback path: Synthesize tactical queries from source_targets + nouns
        if len(queries) < limit and nouns:
            noun_phrase = " ".join(nouns[:3])
            
            secondary_noun = nouns[1] if len(nouns) > 1 else ""
            # Generate diverse search vectors from available data
            tactical_templates = [
                f'{noun_phrase} Wikipedia',
                f'{nouns[0]} official specifications',
                f'{nouns[0]} {secondary_noun} history timeline'.strip(),
                f'"{noun_phrase}" leak OR leaked OR exposed OR internal',
                f'"{nouns[0]}" filetype:pdf OR filetype:xls confidential',
                f'site:reddit.com "{nouns[0]}" employee OR former OR insider',
                f'"{nouns[0]}" site:archive.org',
                f'"{nouns[0]}" trade secret OR proprietary OR classified',
                f'"{nouns[0]}" court filing OR lawsuit OR deposition',
                f'"{nouns[0]}" whistleblower OR disclosure',
            ]
            
            # Integrate source_targets into queries if available
            for target in source_targets[:2]:
                tactical_templates.append(f'"{nouns[0]}" "{target}"')
                
            for template in tactical_templates:
                if template not in queries:
                    queries.append(template)
                if len(queries) >= limit:
                    break
                    
        return queries[:limit]
    
    def query(self, task_description: str) -> Dict[str, Any]:
        """
        Main entry point. Routes a task description through the compiled
        knowledge base and returns up to 5 hyper-specific SearxNG queries.
        
        Returns:
            {
                "matched_domains": [...],
                "matched_files": [...],
                "queries": [...],
                "gates": [...],
                "latency_ms": float
            }
        """
        t0 = time.perf_counter()
        
        # Tokenize input
        prompt_tokens = self._tokenize(task_description)
        nouns = self._extract_nouns(task_description)
        
        # Resolve domain files
        ranked_files = self._resolve_domain_files(prompt_tokens)
        
        # Load matched database files and collect all rules
        all_query_rules = []
        all_source_targets = []
        all_gates = []
        matched_domains = set()
        matched_files = []
        
        for file_path, score in ranked_files:
            db = self._load_db_file(file_path)
            if db:
                matched_files.append(file_path)
                matched_domains.add(db.get("domain", "unknown"))
                all_query_rules.extend(db.get("query_rules", []))
                all_source_targets.extend(db.get("source_targets", []))
                all_gates.extend(db.get("anti_hallucination_gates", []))
                
        # Instantiate concrete search queries
        queries = self._instantiate_queries(
            all_query_rules, all_source_targets, all_gates, nouns, limit=5
        )
        
        latency = (time.perf_counter() - t0) * 1000  # ms
        
        return {
            "matched_domains": sorted(list(matched_domains)),
            "matched_files": matched_files,
            "queries": queries,
            "gates": [g.get("check", "") for g in all_gates[:5]],
            "latency_ms": round(latency, 2)
        }


if __name__ == "__main__":
    router = ReconRouter()
    
    test_prompt = "Find KFC's proprietary fried chicken recipe leaks by ex-employees"
    print(f"Task: {test_prompt}")
    print("=" * 70)
    
    result = router.query(test_prompt)
    
    print(f"\nMatched Domains: {result['matched_domains']}")
    print(f"Matched Files:   {result['matched_files']}")
    print(f"Latency:         {result['latency_ms']}ms")
    print(f"\n--- Generated SearxNG Query Vectors ---")
    for i, q in enumerate(result["queries"], 1):
        print(f"  [{i}] {q}")
    print(f"\n--- Anti-Hallucination Gates ---")
    for i, g in enumerate(result["gates"], 1):
        print(f"  [{i}] {g}")

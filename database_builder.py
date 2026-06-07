import os
import sys
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List

# Source ID mapping to (domain, target_name)
SOURCE_MAP = {
    "electronic_crime_scene_investigation": ("law", "evidence_aquisition"),
    "crime_classification_manual": ("law", "evidence_aquisition"),
    "berkeley_protocol": ("law", "evidence_aquisition"),
    "psychology_of_intelligence_analysis": ("intel", "ach_matrix"),
    "bellingcat_toolkit": ("intel", "osint_tree"),
    "cochrane_handbook": ("science", "pico_boolean"),
    "prisma_2020": ("science", "pico_boolean"),
    "verification_handbook": ("journalism", "verification_triad"),
    "information_disorder": ("journalism", "verification_triad")
}

# Keywords to target_name mappings for quick lookup routing
KEYWORD_TO_TARGET = {
    "forensics": "evidence_aquisition",
    "berkeley": "evidence_aquisition",
    "evidence": "evidence_aquisition",
    "electronic": "evidence_aquisition",
    
    "osint": "osint_tree",
    "bellingcat": "osint_tree",
    "toolkit": "osint_tree",
    
    "ach": "ach_matrix",
    "matrix": "ach_matrix",
    "intelligence": "ach_matrix",
    "analysis": "ach_matrix",
    
    "cochrane": "pico_boolean",
    "prisma": "pico_boolean",
    "pico": "pico_boolean",
    "boolean": "pico_boolean",
    "medical": "pico_boolean",
    
    "verification": "verification_triad",
    "silverman": "verification_triad",
    "disinformation": "verification_triad",
    "triad": "verification_triad"
}

def deduplicate_list(lst: List[Any]) -> List[Any]:
    """Helper to deduplicate a list of items (handles Dicts by serializing to JSON)."""
    seen = set()
    result = []
    for item in lst:
        if isinstance(item, dict):
            serialized = json.dumps(item, sort_keys=True)
            if serialized not in seen:
                seen.add(serialized)
                result.append(item)
        else:
            if item not in seen:
                seen.add(item)
                result.append(item)
    return result


class DatabaseBuilder:
    def __init__(self, wiki_dir: Path):
        self.wiki_dir = Path(wiki_dir)
        self.raw_heuristics_path = self.wiki_dir / "raw_compressed_heuristics.json"
        
    def build_database(self):
        if not self.raw_heuristics_path.exists():
            print(f"Error: {self.raw_heuristics_path} does not exist. Run compressor.py first.")
            sys.exit(1)
            
        with open(self.raw_heuristics_path, "r", encoding="utf-8") as f:
            heuristics = json.load(f)
            
        print(f"Loaded {len(heuristics)} raw compressed heuristics.")
        
        # Group by target name and domain
        grouped_heuristics = defaultdict(list)
        for h in heuristics:
            source_id = h.get("source_id")
            mapping = SOURCE_MAP.get(source_id)
            if mapping:
                domain, target_name = mapping
                grouped_heuristics[(domain, target_name)].append(h)
            else:
                domain = h.get("domain", "other")
                grouped_heuristics[(domain, "generic_heuristics")].append(h)
                
        # Subdirectory routing & split details tracking
        generated_files = defaultdict(list)
        target_to_files = defaultdict(list)
        
        # Build individual JSON databases
        for (domain, target_name), h_list in grouped_heuristics.items():
            domain_dir = self.wiki_dir / domain
            domain_dir.mkdir(parents=True, exist_ok=True)
            
            # Merge all components
            merged_query_rules = []
            merged_source_targets = []
            merged_gates = []
            source_ids = set()
            
            for h in h_list:
                merged_query_rules.extend(h.get("query_rules", []))
                merged_source_targets.extend(h.get("source_targets", []))
                merged_gates.extend(h.get("anti_hallucination_gates", []))
                source_ids.add(h.get("source_id"))
                
            # Deduplicate
            deduped_query_rules = deduplicate_list(merged_query_rules)
            deduped_source_targets = deduplicate_list(merged_source_targets)
            deduped_gates = deduplicate_list(merged_gates)
            
            # Chunking size limit of 50
            chunk_size = 50
            num_chunks = max(
                (len(deduped_query_rules) + chunk_size - 1) // chunk_size,
                (len(deduped_source_targets) + chunk_size - 1) // chunk_size,
                (len(deduped_gates) + chunk_size - 1) // chunk_size,
                1
            )
            
            # If multiple chunks, split into _a, _b, etc.
            for i in range(num_chunks):
                part_query_rules = deduped_query_rules[i * chunk_size : (i + 1) * chunk_size]
                part_source_targets = deduped_source_targets[i * chunk_size : (i + 1) * chunk_size]
                part_gates = deduped_gates[i * chunk_size : (i + 1) * chunk_size]
                
                # Suffix determination
                if num_chunks > 1:
                    suffix = f"_{chr(97 + i)}"  # a, b, c, etc.
                else:
                    suffix = ""
                    
                filename = f"{target_name}{suffix}.json"
                relative_path = f"wiki/{domain}/{filename}"
                absolute_path = domain_dir / filename
                
                # Write individual database part file
                db_object = {
                    "source_ids": sorted(list(source_ids)),
                    "domain": domain,
                    "query_rules": part_query_rules,
                    "source_targets": part_source_targets,
                    "anti_hallucination_gates": part_gates
                }
                
                with open(absolute_path, "w", encoding="utf-8") as f_out:
                    json.dump(db_object, f_out, indent=2, ensure_ascii=False)
                    
                generated_files[domain].append(relative_path)
                target_to_files[target_name].append(relative_path)
                print(f"Wrote file: {relative_path} (Rules: {len(part_query_rules)}, Targets: {len(part_source_targets)}, Gates: {len(part_gates)})")
                
        # Build quick lookup routing mapping
        quick_lookup = {}
        for keyword, target in KEYWORD_TO_TARGET.items():
            if target in target_to_files:
                quick_lookup[keyword] = target_to_files[target]
                
        # Build Master index.json routing table
        master_index = {
            "domains": {domain: sorted(files) for domain, files in generated_files.items()},
            "quick_lookup": quick_lookup
        }
        
        index_path = self.wiki_dir / "index.json"
        with open(index_path, "w", encoding="utf-8") as f_index:
            json.dump(master_index, f_index, indent=2, ensure_ascii=False)
            
        print(f"\n[DatabaseBuilder] Master routing index successfully written to {index_path}\n")


if __name__ == "__main__":
    base_dir = Path(__file__).parent
    wiki_path = base_dir / "wiki"
    
    builder = DatabaseBuilder(wiki_path)
    builder.build_database()

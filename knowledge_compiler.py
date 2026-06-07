import os
import re
import sys
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Generator

@dataclass(frozen=True)
class RawChunk:
    source_id: str
    domain: str
    file_type: str
    content: str
    structural_meta: Dict[str, Any]

def detect_table(text: str) -> bool:
    """Heuristic to detect if a page/section contains a table based on layout indicators."""
    if not text:
        return False
    lines = text.split("\n")
    # A table is suspected if multiple lines have vertical pipes or tabs separating words
    table_lines = sum(1 for line in lines if line.count("\t") >= 2 or line.count("|") >= 2)
    return table_lines >= 2

def create_overlapping_chunks(text: str, header_positions: List[tuple]) -> List[tuple]:
    """Helper to split text by header positions with a 200-character overlap window."""
    if not header_positions:
        return [(text, "None")]
        
    chunks = []
    for i in range(len(header_positions)):
        start_idx, header_text = header_positions[i]
        end_idx = header_positions[i+1][0] if i + 1 < len(header_positions) else len(text)
        
        chunk_content = text[start_idx:end_idx].strip()
        
        # Prepend overlap from the previous chunk
        if i > 0:
            prev_start, _ = header_positions[i-1]
            prev_end = start_idx
            prev_content = text[prev_start:prev_end].strip()
            overlap = prev_content[-200:] if len(prev_content) > 200 else prev_content
            chunk_content = f"{overlap}\n\n{chunk_content}"
            
        chunks.append((chunk_content, header_text))
    return chunks

def html_to_clean_markdown(soup) -> str:
    """Transforms a BeautifulSoup HTML DOM into clean Markdown while keeping headers and tables."""
    # Strip noise tags
    for tag in soup(["nav", "header", "footer", "aside", "script", "style"]):
        tag.decompose()
        
    markdown_lines = []
    
    def process_node(node):
        if node.name is None:  # Text node
            text = node.string
            if text and text.strip():
                markdown_lines.append(text)
            return
            
        name = node.name.lower()
        if name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            level = int(name[1])
            markdown_lines.append(f"\n\n{'#' * level} {node.get_text().strip()}\n")
        elif name == "p":
            markdown_lines.append(f"\n\n{node.get_text().strip()}\n")
        elif name == "li":
            markdown_lines.append(f"\n* {node.get_text().strip()}")
        elif name == "tr":
            cells = [td.get_text().strip() for td in node.find_all(["td", "th"])]
            if cells:
                markdown_lines.append("\n| " + " | ".join(cells) + " |")
        elif name == "br":
            markdown_lines.append("\n")
        else:
            for child in node.children:
                process_node(child)
                
    process_node(soup.body if soup.body else soup)
    return "".join(markdown_lines)

def parse_markdown_stream(filepath: Path) -> List[tuple]:
    """Reads Markdown natively and splits on ## or ### headers without loading all at once."""
    chunks = []
    current_header = "Introduction"
    current_lines = []
    
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("## ") or line.startswith("### "):
                if current_lines:
                    content = "".join(current_lines).strip()
                    if content:
                        chunks.append((content, current_header))
                
                # Get the 200-character overlap
                overlap = ""
                if current_lines:
                    full_prev = "".join(current_lines)
                    overlap = full_prev[-200:] if len(full_prev) > 200 else full_prev
                
                current_header = line.strip()
                current_lines = [overlap + "\n\n" if overlap else "", line]
            else:
                current_lines.append(line)
                
        # Append final chunk
        if current_lines:
            content = "".join(current_lines).strip()
            if content:
                chunks.append((content, current_header))
                
    return chunks


class IngestionPipeline:
    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)
        self.output_dir = self.root_dir / "ingested"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def _map_file_metadata(self, filepath: Path) -> tuple:
        """Assigns source_id and domain based on filename hierarchy."""
        name = filepath.name.lower()
        path_str = str(filepath).lower()
        
        if "bellingcat toolkit" in path_str:
            return "bellingcat_toolkit", "intel"
            
        if "219941.pdf" in name:
            return "electronic_crime_scene_investigation", "law"
        elif "classific.pdf" in name:
            return "crime_classification_manual", "law"
        elif "berkeleyprotocol" in name:
            return "berkeley_protocol", "law"
        elif "psychology_of_intelligence_analysis" in name:
            return "psychology_of_intelligence_analysis", "intel"
        elif "cochrane" in name:
            return "cochrane_handbook", "science"
        elif "prisma" in name:
            return "prisma_2020", "science"
        elif "verification.handbook" in name:
            return "verification_handbook", "journalism"
        elif "disorder" in name:
            return "information_disorder", "journalism"
        else:
            if name.endswith(".md"):
                return "bellingcat_toolkit", "intel"
            return "unknown_source", "other"

    def parse_pdf(self, filepath: Path, source_id: str, domain: str) -> List[RawChunk]:
        import fitz  # PyMuPDF
        chunks = []
        doc = fitz.open(filepath)
        last_page_overlap = ""
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            has_table = detect_table(text)
            page_text = text.strip()
            
            if not page_text:
                continue
                
            if last_page_overlap:
                page_text = f"{last_page_overlap}\n\n{page_text}"
                
            # Scan for headings on the page to divide them
            header_positions = []
            lines = page_text.split("\n")
            current_idx = 0
            
            header_pattern = re.compile(r'^(?:[0-9\.]+\s+[A-Z][A-Za-z\s]{3,}|[A-Z\s]{4,20}:?)$')
            
            for line in lines:
                line_len = len(line.strip())
                if 4 <= line_len <= 100 and header_pattern.match(line.strip()):
                    pos = page_text.find(line, current_idx)
                    if pos != -1:
                        header_positions.append((pos, line.strip()))
                        current_idx = pos + line_len
                        
            if header_positions:
                pdf_chunks = create_overlapping_chunks(page_text, header_positions)
                for content, header in pdf_chunks:
                    chunks.append(
                        RawChunk(
                            source_id=source_id,
                            domain=domain,
                            file_type="pdf",
                            content=content,
                            structural_meta={
                                "page": page_num + 1,
                                "section": header,
                                "has_table": has_table
                            }
                        )
                    )
            else:
                chunks.append(
                    RawChunk(
                        source_id=source_id,
                        domain=domain,
                        file_type="pdf",
                        content=page_text,
                        structural_meta={
                            "page": page_num + 1,
                            "section": "None",
                            "has_table": has_table
                        }
                    )
                )
                
            last_page_overlap = page_text[-200:] if len(page_text) > 200 else page_text
            
        return chunks

    def parse_html(self, filepath: Path, source_id: str, domain: str) -> List[RawChunk]:
        from bs4 import BeautifulSoup
        with open(filepath, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            
        markdown_text = html_to_clean_markdown(soup)
        lines = markdown_text.split("\n")
        header_positions = []
        current_idx = 0
        
        for line in lines:
            if line.strip().startswith("#"):
                pos = markdown_text.find(line, current_idx)
                if pos != -1:
                    header_positions.append((pos, line.strip()))
                    current_idx = pos + len(line)
                    
        chunks = []
        if header_positions:
            html_chunks = create_overlapping_chunks(markdown_text, header_positions)
            for content, header in html_chunks:
                chunks.append(
                    RawChunk(
                        source_id=source_id,
                        domain=domain,
                        file_type="html",
                        content=content,
                        structural_meta={
                            "section": header,
                            "file_path": filepath.name
                        }
                    )
                )
        else:
            chunks.append(
                RawChunk(
                    source_id=source_id,
                    domain=domain,
                    file_type="html",
                    content=markdown_text.strip(),
                    structural_meta={
                        "section": "None",
                        "file_path": filepath.name
                    }
                )
            )
        return chunks

    def parse_markdown(self, filepath: Path, source_id: str, domain: str) -> List[RawChunk]:
        raw_chunks = parse_markdown_stream(filepath)
        chunks = []
        for content, header in raw_chunks:
            chunks.append(
                RawChunk(
                    source_id=source_id,
                    domain=domain,
                    file_type="markdown",
                    content=content,
                    structural_meta={
                        "section": header,
                        "file_path": filepath.name
                    }
                )
            )
        return chunks

    def ingest_all(self) -> Dict[str, int]:
        """Scans the directory using rglob, processes files, and stores raw chunks."""
        summary = {}
        all_chunks = []
        
        # Grab all files using flat rglob
        for filepath in self.root_dir.rglob("*"):
            if not filepath.is_file() or filepath.suffix.lower() not in [".pdf", ".html", ".htm", ".md"]:
                continue
                
            # Skip plan.md or other files in output directory itself
            if filepath.name == "plan.md" or "ingested" in filepath.parts:
                continue
                
            source_id, domain = self._map_file_metadata(filepath)
            suffix = filepath.suffix.lower()
            
            try:
                if suffix == ".pdf":
                    file_chunks = self.parse_pdf(filepath, source_id, domain)
                elif suffix in [".html", ".htm"]:
                    file_chunks = self.parse_html(filepath, source_id, domain)
                elif suffix == ".md":
                    file_chunks = self.parse_markdown(filepath, source_id, domain)
                else:
                    continue
                    
                all_chunks.extend(file_chunks)
                summary[filepath.name] = len(file_chunks)
                
            except Exception as e:
                print(f"Error parsing file {filepath.name}: {e}", file=sys.stderr)
                summary[filepath.name] = 0

        # Save all chunks to the ingested/ directory
        output_file = self.output_dir / "chunks.json"
        serialized_chunks = [asdict(c) for c in all_chunks]
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(serialized_chunks, f, indent=2, ensure_ascii=False)
            
        print(f"\n[IngestionPipeline] Successfully wrote {len(all_chunks)} chunks to {output_file}\n")
        return summary


if __name__ == "__main__":
    # Point root_dir directly to 'Reasoning sources'
    root_path = Path(__file__).parent / "Reasoning sources"
    if not root_path.exists():
        print(f"Error: Reasoning sources path {root_path} does not exist!")
        sys.exit(1)
        
    pipeline = IngestionPipeline(root_path)
    summary_report = pipeline.ingest_all()
    
    print("==================================================")
    print("         Phase 1 Ingestion Pipeline Summary       ")
    print("==================================================")
    for filename, count in summary_report.items():
        print(f"File: {filename:<60} Chunks: {count}")
    print("==================================================")

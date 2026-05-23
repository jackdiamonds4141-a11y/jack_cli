import re
import logging

logger = logging.getLogger("JackCLI.Parser")

def extract_tag(tag: str, text: str, default=None) -> str:
    match = re.search(f"<{tag}>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else default

def extract_list_tags(tag: str, text: str) -> list:
    matches = re.findall(f"<{tag}>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)
    return [m.strip() for m in matches if m.strip()]

def parse_output(content_str: str, idea_id: str = "test_task", idea: dict = None) -> dict:
    """
    Robust XML/Markdown tag-based extraction parser.
    Bypasses fragile monolithic JSON serialization.
    """
    if idea is None:
        idea = {}
    
    output = {}
    
    # Check if the model ignored tags and generated raw json
    if content_str.strip().startswith("{") and content_str.strip().endswith("}"):
        try:
            import json
            output = json.loads(content_str)
            if "content" in output:
                return output
        except:
            pass

    # XML Tag Extraction
    output["meme_type"] = extract_tag("meme_type", content_str, "PROPOSAL")
    output["content"] = extract_tag("content", content_str)
    
    claims_block = extract_tag("claims", content_str, "")
    output["claims"] = extract_list_tags("claim", claims_block)
    
    queries_block = extract_tag("search_queries", content_str, "")
    output["search_queries"] = extract_list_tags("query", queries_block)
    
    tb_val = extract_tag("target_branch_id", content_str)
    if tb_val and tb_val.lower() == "null":
        tb_val = None
    output["target_branch_id"] = tb_val
    output["reasoning_trace"] = extract_tag("reasoning_trace", content_str)
    
    if not output["content"]:
        # Fallback 1: Extract anything between ``` ... ``` or general text fallback
        if len(content_str) > 100:
            logger.info("Content tag missing. Falling back to raw text extraction.")
            output["content"] = content_str.replace("```xml", "").replace("```markdown", "").replace("```", "").strip()
        else:
            return None # Triggers failure handling in worker
            
    if not output["claims"]:
        output["claims"] = [f"Auto-extracted from task {idea_id}"]
        
    return output

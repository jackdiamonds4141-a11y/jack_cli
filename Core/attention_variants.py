# Core/attention_variants.py
import json

class CompressedSemanticPool:
    def __init__(self, max_digest_len: int = 80):
        self.max_digest_len = max_digest_len
        self.pool = {"epoch_watermark": 0, "claims": {}, "epoch_macros": {}}

    def compress_claims(self, raw_claims: list, current_epoch: int, frozen_anchor_claims: list):
        self.pool["epoch_watermark"] = current_epoch
        for c in raw_claims:
            # The c_kv latent equivalent: compress narrative to pure essence
            digest = getattr(c, 'text', '')[:self.max_digest_len].replace("\n", " ").strip()
            if len(getattr(c, 'text', '')) > self.max_digest_len:
                digest = digest[:self.max_digest_len - 3] + "..."
            
            # Anchor-touch immunity flag
            anchor_touch = any(a in frozen_anchor_claims for a in getattr(c, 'anchor_links', []))

            self.pool["claims"][c.claim_id] = {
                "digest": digest,
                "status": getattr(c, 'status', 'PENDING'),
                "epoch_born": getattr(c, 'epoch_born', current_epoch),
                "anchor_touch": anchor_touch
            }

class DecoupledPositionTagger:
    def __init__(self):
        self.seq_counters = {}

    def tag(self, epoch: int, worker_id: str) -> str:
        # Generates $q_{rope}$ analog: E{epoch}W{worker}S{seq}
        key = f"E{epoch}W{worker_id[-2:]}"
        self.seq_counters[key] = self.seq_counters.get(key, 0) + 1
        return f"{key}S{self.seq_counters[key]:03d}"

    def build_flat_xml_node(self, claim_id: str, pos_tag: str, digest: str, status: str) -> str:
        # Prevents FlashAttention Bypass: No nested elements, flat attributes only
        return f'<CLAIM id="{claim_id}" pos="{pos_tag}" status="{status}">{digest}</CLAIM>'

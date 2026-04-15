import hashlib
import json
import os
import re
import time

import numpy as np
from sentence_transformers import SentenceTransformer, util


def get_cache_paths(db_file, model_name):
    db_name = os.path.splitext(os.path.basename(db_file))[0]
    db_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', db_name)
    db_hash = hashlib.sha1(os.path.abspath(db_file).encode('utf-8')).hexdigest()[:8]
    model_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', model_name)
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(db_file)), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"cache_{db_safe}_{db_hash}_{model_safe}.npy")
    meta_file = os.path.join(cache_dir, f"cache_{db_safe}_{db_hash}_{model_safe}.meta.json")
    return cache_file, meta_file


class PaperSearcher:
    def __init__(self, db_file, model_name='BAAI/bge-large-en-v1.5', api_key=""):
        self.jp = db_file
        self.mn = model_name
        self.ak = api_key
        self.mt = 'v' if 'voyage' in self.mn else ('o' if 'text-embedding' in self.mn else 'l')
        self.dt = self._load_db()
        self.cf, self.mf = get_cache_paths(self.jp, self.mn)

        print(f"[search] init model={self.mn} mode={self.mt} cache={self.cf}")
        self.md = self._init_model()
        self.eb = self._load_cache()

    def _init_model(self):
        if self.mt == 'v':
            import voyageai
            return voyageai.Client(api_key=self.ak)
        if self.mt == 'o':
            from openai import OpenAI
            return OpenAI(api_key=self.ak)
        return SentenceTransformer(self.mn)

    def _load_db(self):
        with open(self.jp, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _paper_text(self, paper):
        return f"{paper.get('title', '')} {paper.get('abstract', '')}".strip()

    def _dataset_fingerprints(self):
        return [
            hashlib.sha1(self._paper_text(paper).encode('utf-8')).hexdigest()
            for paper in self.dt
        ]

    def _load_meta(self):
        if not os.path.exists(self.mf):
            return None
        try:
            with open(self.mf, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            print(f"[search] failed to load meta {self.mf}: {exc}")
            return None

    def _save_meta(self, fingerprints):
        payload = {
            "db_file": os.path.abspath(self.jp),
            "model_name": self.mn,
            "fingerprints": fingerprints,
        }
        with open(self.mf, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def _embed(self, texts):
        if self.mt == 'l':
            return self.md.encode(texts, convert_to_numpy=True, show_progress_bar=True)

        rows = []
        batch_size = 100 if self.mt == 'v' else 400
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            if self.mt == 'v':
                result = self.md.embed(batch, model=self.mn).embeddings
            else:
                result = [x.embedding for x in self.md.embeddings.create(input=batch, model=self.mn).data]
            rows.extend(result)
            time.sleep(0.6)
        return np.array(rows, dtype=np.float32)

    def _load_cache(self):
        current_fingerprints = self._dataset_fingerprints()
        texts = [self._paper_text(paper) for paper in self.dt]

        if os.path.exists(self.cf):
            try:
                embeddings = np.load(self.cf)
                meta = self._load_meta() or {}
                old_fingerprints = meta.get("fingerprints", [])

                if embeddings.shape[0] == len(current_fingerprints) and old_fingerprints == current_fingerprints:
                    print(f"[search] cache hit {self.cf}")
                    return embeddings

                if (
                    embeddings.shape[0] == len(old_fingerprints)
                    and len(old_fingerprints) < len(current_fingerprints)
                    and current_fingerprints[:len(old_fingerprints)] == old_fingerprints
                ):
                    print(f"[search] append-only update {len(old_fingerprints)} -> {len(current_fingerprints)}")
                    new_embeddings = self._embed(texts[len(old_fingerprints):])
                    embeddings = np.vstack((embeddings, new_embeddings))
                    np.save(self.cf, embeddings)
                    self._save_meta(current_fingerprints)
                    return embeddings

                print("[search] cache invalidated because paper order/content changed")
            except Exception as exc:
                print(f"[search] failed to load cache {self.cf}: {exc}")

        embeddings = self._embed(texts)
        np.save(self.cf, embeddings)
        self._save_meta(current_fingerprints)
        return embeddings

    def search(self, query, top_k=50):
        qe = self._embed([query]) if self.mt != 'l' else self.md.encode(query, convert_to_numpy=True)
        if self.mt != 'l':
            qe = np.array(qe).reshape(1, -1)
        hits = util.semantic_search(qe, self.eb, top_k=top_k)[0]
        return [{"similarity": x['score'], "paper": self.dt[x['corpus_id']]} for x in hits]

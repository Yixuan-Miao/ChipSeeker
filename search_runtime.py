import hashlib
import json
import os
import re
import shutil
import time

import numpy as np
from sentence_transformers import SentenceTransformer, util
from chipseeker.cloud_access import cloud_embed, is_cloud_token


def _log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [search] {message}", flush=True)


def _format_eta(seconds):
    if seconds <= 0:
        return "0s"
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def get_cache_paths(db_file, model_name, scope_key="all"):
    db_name = os.path.splitext(os.path.basename(db_file))[0]
    db_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', db_name)
    model_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', model_name)
    scope_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', scope_key or "all")
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(db_file)), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"cache_{db_safe}_{model_safe}_{scope_safe}.npy")
    meta_file = os.path.join(cache_dir, f"cache_{db_safe}_{model_safe}_{scope_safe}.meta.json")
    return cache_file, meta_file


def _legacy_cache_candidates(db_file, model_name, scope_key="all"):
    db_name = os.path.splitext(os.path.basename(db_file))[0]
    db_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', db_name)
    model_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', model_name)
    scope_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', scope_key or "all")
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(db_file)), "cache")
    if not os.path.isdir(cache_dir):
        return []
    prefix = f"cache_{db_safe}_"
    suffix = f"_{model_safe}_{scope_safe}.npy"
    candidates = []
    for name in os.listdir(cache_dir):
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        middle = name[len(prefix):-len(suffix)]
        if re.fullmatch(r"[0-9a-f]{8}", middle):
            cache_file = os.path.join(cache_dir, name)
            meta_file = cache_file[:-4] + ".meta.json"
            candidates.append((cache_file, meta_file))
    return sorted(candidates)


def _load_meta_file(meta_file):
    if not os.path.exists(meta_file):
        return {}
    with open(meta_file, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def _cache_matches_fingerprints(cache_file, meta_file, fingerprints):
    try:
        embeddings = np.load(cache_file, mmap_mode="r")
        meta = _load_meta_file(meta_file)
        old_fingerprints = meta.get("fingerprints", [])
        if embeddings.shape[0] == len(fingerprints) and old_fingerprints == fingerprints:
            return "exact", embeddings.shape[0]
        if (
            embeddings.shape[0] == len(old_fingerprints)
            and len(old_fingerprints) < len(fingerprints)
            and fingerprints[:len(old_fingerprints)] == old_fingerprints
        ):
            return "append_only", len(old_fingerprints)
    except Exception:
        return "", 0
    return "", 0


def _migrate_cache_if_needed(source_cache, source_meta, target_cache, target_meta):
    if os.path.abspath(source_cache) == os.path.abspath(target_cache):
        return source_cache, source_meta
    shutil.copy2(source_cache, target_cache)
    if os.path.exists(source_meta):
        shutil.copy2(source_meta, target_meta)
    return target_cache, target_meta


def resolve_portable_cache(db_file, model_name, scope_key, fingerprints):
    primary_cache, primary_meta = get_cache_paths(db_file, model_name, scope_key)
    state, cached_count = _cache_matches_fingerprints(primary_cache, primary_meta, fingerprints) if os.path.exists(primary_cache) else ("", 0)
    if state:
        return primary_cache, primary_meta, state, cached_count
    for candidate_cache, candidate_meta in _legacy_cache_candidates(db_file, model_name, scope_key):
        state, cached_count = _cache_matches_fingerprints(candidate_cache, candidate_meta, fingerprints)
        if state:
            cache_file, meta_file = _migrate_cache_if_needed(candidate_cache, candidate_meta, primary_cache, primary_meta)
            return cache_file, meta_file, state, cached_count
    return primary_cache, primary_meta, "", 0


def _paper_text(paper):
    return f"{paper.get('title', '')} {paper.get('abstract', '')}".strip()


def _dataset_fingerprints(papers):
    return [hashlib.sha1(_paper_text(paper).encode('utf-8')).hexdigest() for paper in papers]


def describe_cache_status(db_file, model_name, scope_key="all", papers_override=None):
    papers = papers_override
    if papers is None:
        with open(db_file, 'r', encoding='utf-8') as f:
            papers = json.load(f)
    cache_file, meta_file = get_cache_paths(db_file, model_name, scope_key)
    fingerprints = _dataset_fingerprints(papers)
    resolved_cache, resolved_meta, cache_state, cached_count = resolve_portable_cache(
        db_file, model_name, scope_key, fingerprints
    )
    status = {
        "cache_file": resolved_cache or cache_file,
        "meta_file": resolved_meta or meta_file,
        "total_papers": len(papers),
        "cached_papers": 0,
        "has_cache": bool(cache_state),
        "up_to_date": False,
        "needs_build": not bool(cache_state),
        "append_only": False,
        "new_papers": len(papers),
    }
    if cache_state == "exact":
        status["cached_papers"] = cached_count
        status["up_to_date"] = True
        status["needs_build"] = False
        status["new_papers"] = 0
        return status
    if cache_state == "append_only":
        status["append_only"] = True
        status["cached_papers"] = cached_count
        status["new_papers"] = max(0, len(fingerprints) - cached_count)
        return status
    return status


class PaperSearcher:
    def __init__(self, db_file, model_name='BAAI/bge-large-en-v1.5', api_key="", papers_override=None, scope_key="all", progress_callback=None, log_callback=None):
        self.jp = db_file
        self.mn = model_name
        self.ak = api_key
        self.scope_key = scope_key or "all"
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.mt = 'c' if is_cloud_token(self.ak) else ('v' if 'voyage' in self.mn else ('o' if 'text-embedding' in self.mn else 'l'))
        self.dt = papers_override if papers_override is not None else self._load_db()
        self.cf, self.mf = get_cache_paths(self.jp, self.mn, self.scope_key)

        self._log(f"init model={self.mn} mode={self.mt} scope={self.scope_key} cache={self.cf}")
        self.md = self._init_model()
        self.eb = self._load_cache()

    def _init_model(self):
        if self.mt == 'c':
            return {"cloud_access": True}
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
        return _paper_text(paper)

    def _dataset_fingerprints(self):
        return _dataset_fingerprints(self.dt)

    def _load_meta(self):
        if not os.path.exists(self.mf):
            return None
        try:
            with open(self.mf, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            self._log(f"failed to load meta {self.mf}: {exc}")
            return None

    def _save_meta(self, fingerprints):
        payload = {
            "cache_schema": 2,
            "db_name": os.path.basename(self.jp),
            "model_name": self.mn,
            "scope_key": self.scope_key,
            "fingerprints": fingerprints,
        }
        with open(self.mf, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def _emit_progress(self, done, total, message):
        if self.progress_callback:
            self.progress_callback(done, total, message)

    def _log(self, message):
        _log(message)
        if self.log_callback:
            self.log_callback(message)

    def _remote_embed_batch(self, batch, batch_index, total_batches, stage_message, start_idx, total):
        batch_label = f"batch {batch_index}/{total_batches}"
        batch_range = f"{start_idx + 1}-{start_idx + len(batch)}/{total}"
        for attempt in range(1, 4):
            batch_start = time.perf_counter()
            self._log(f"{stage_message}: starting {batch_label} items {batch_range} attempt {attempt}")
            try:
                if self.mt == 'c':
                    result = cloud_embed(self.ak, self.mn, batch)
                elif self.mt == 'v':
                    result = self.md.embed(batch, model=self.mn).embeddings
                else:
                    result = [x.embedding for x in self.md.embeddings.create(input=batch, model=self.mn).data]
            except Exception as exc:
                elapsed = time.perf_counter() - batch_start
                self._log(f"{stage_message}: failed {batch_label} attempt {attempt} after {elapsed:.1f}s error={exc}")
                if attempt >= 3:
                    raise
                sleep_s = min(6.0, 1.5 * attempt)
                self._log(f"{stage_message}: retrying {batch_label} after {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue
            elapsed = time.perf_counter() - batch_start
            self._log(f"{stage_message}: finished {batch_label} items {batch_range} in {elapsed:.1f}s")
            return result
        raise RuntimeError(f"Unreachable retry state for {batch_label}")

    def _embed(self, texts, stage_message="Embedding papers"):
        total = max(1, len(texts))
        overall_start = time.perf_counter()
        self._log(f"{stage_message}: total_items={len(texts)} scope={self.scope_key} model={self.mn}")
        if self.mt == 'l':
            rows = []
            batch_size = 64
            total_batches = max(1, (len(texts) + batch_size - 1) // batch_size)
            for batch_index, i in enumerate(range(0, len(texts), batch_size), start=1):
                batch = texts[i:i + batch_size]
                batch_start = time.perf_counter()
                self._log(f"{stage_message}: starting batch {batch_index}/{total_batches} items {i + 1}-{i + len(batch)}/{total}")
                result = self.md.encode(batch, convert_to_numpy=True, show_progress_bar=False)
                rows.extend(result)
                done = min(i + len(batch), total)
                elapsed = time.perf_counter() - batch_start
                total_elapsed = time.perf_counter() - overall_start
                eta_seconds = (total_elapsed / done) * max(0, total - done) if done else 0.0
                eta_text = _format_eta(eta_seconds)
                self._log(f"{stage_message}: finished batch {batch_index}/{total_batches} in {elapsed:.1f}s cumulative={done}/{total} elapsed={total_elapsed:.1f}s eta={eta_text}")
                self._emit_progress(done, total, f"{stage_message}: batch {batch_index}/{total_batches} ({done}/{total}) elapsed {total_elapsed:.1f}s | ETA {eta_text}")
            self._log(f"{stage_message}: completed {total}/{total} in {time.perf_counter() - overall_start:.1f}s")
            return np.array(rows, dtype=np.float32)

        rows = []
        batch_size = 100 if self.mt == 'v' else 400
        total_batches = max(1, (len(texts) + batch_size - 1) // batch_size)
        for batch_index, i in enumerate(range(0, len(texts), batch_size), start=1):
            batch = texts[i:i + batch_size]
            result = self._remote_embed_batch(batch, batch_index, total_batches, stage_message, i, total)
            rows.extend(result)
            done = min(i + len(batch), total)
            total_elapsed = time.perf_counter() - overall_start
            eta_seconds = (total_elapsed / done) * max(0, total - done) if done else 0.0
            eta_text = _format_eta(eta_seconds)
            self._log(f"{stage_message}: progress batch {batch_index}/{total_batches} cumulative={done}/{total} elapsed={total_elapsed:.1f}s eta={eta_text}")
            self._emit_progress(done, total, f"{stage_message}: batch {batch_index}/{total_batches} ({done}/{total}) elapsed {total_elapsed:.1f}s | ETA {eta_text}")
            time.sleep(0.6)
        self._log(f"{stage_message}: completed {total}/{total} in {time.perf_counter() - overall_start:.1f}s")
        return np.array(rows, dtype=np.float32)

    def _load_cache(self):
        current_fingerprints = self._dataset_fingerprints()
        texts = [self._paper_text(paper) for paper in self.dt]
        resolved_cache, resolved_meta, cache_state, cached_count = resolve_portable_cache(
            self.jp, self.mn, self.scope_key, current_fingerprints
        )
        self.cf, self.mf = resolved_cache, resolved_meta

        if cache_state:
            try:
                embeddings = np.load(self.cf)

                if cache_state == "exact":
                    self._log(f"cache hit {self.cf}")
                    return embeddings

                if cache_state == "append_only":
                    self._log(f"append-only update {cached_count} -> {len(current_fingerprints)}")
                    new_embeddings = self._embed(texts[cached_count:], stage_message="Appending embeddings")
                    embeddings = np.vstack((embeddings, new_embeddings))
                    np.save(self.cf, embeddings)
                    self._save_meta(current_fingerprints)
                    return embeddings
            except Exception as exc:
                self._log(f"failed to load cache {self.cf}: {exc}")
        elif os.path.exists(self.cf):
            self._log("cache invalidated because paper order/content changed")

        embeddings = self._embed(texts)
        np.save(self.cf, embeddings)
        self._save_meta(current_fingerprints)
        return embeddings

    def search(self, query, top_k=50):
        qe = self._embed([query], stage_message="Embedding query") if self.mt != 'l' else self.md.encode(query, convert_to_numpy=True)
        if self.mt != 'l':
            qe = np.array(qe).reshape(1, -1)
        hits = util.semantic_search(qe, self.eb, top_k=top_k)[0]
        return [{"similarity": x['score'], "paper": self.dt[x['corpus_id']]} for x in hits]

# ==============================================================================
# Copyright (c) 2026 Miao Yixuan. All rights reserved.
# Author: Miao Yixuan
# Contact: guangeofaisa@gmail.com
#
# PROPRIETARY AND CONFIDENTIAL.
# Unauthorized copying, distribution, modification, or use of this file, 
# via any medium, is strictly prohibited without prior written permission.
# ==============================================================================

import json, os, time
import numpy as np
from sentence_transformers import SentenceTransformer, util

class PaperSearcher:
    # 恢复了对外的标准接口名称 (db_file, model_name, api_key)，保障 app.py 正常调用
    def __init__(self, db_file, model_name='BAAI/bge-large-en-v1.5', api_key=""):
        self.jp = db_file
        self.mn = model_name
        self.ak = api_key
        self.mt = 'v' if 'voyage' in self.mn else ('o' if 'text-embedding' in self.mn else 'l')
        self.cf = f"cache_{self.mn.replace('/', '_')}.npy"
        self.dt = self._l_d()
        print(f"⚡ [系统日志] 内核初始化完毕 | 引擎拓扑: {self.mt.upper()} | 挂载预训练矩阵: {self.mn}")
        self.md = self._i_m()
        self.eb = self._l_c()

    def _i_m(self):
        if self.mt == 'v':
            import voyageai; return voyageai.Client(api_key=self.ak)
        elif self.mt == 'o':
            from openai import OpenAI; return OpenAI(api_key=self.ak)
        return SentenceTransformer(self.mn)

    def _l_d(self):
        with open(self.jp, 'r', encoding='utf-8') as f: return json.load(f)

    def _e_b(self, tx):
        if self.mt == 'l': return self.md.encode(tx, convert_to_numpy=True, show_progress_bar=True)
        rs = []
        bs = 100 if self.mt == 'v' else 400
        print(f"🚀 [系统日志] 启动远端云算力集群推理，分片维度: {bs}")
        for i in range(0, len(tx), bs):
            b = tx[i:i+bs]
            try:
                if self.mt == 'v': r = self.md.embed(b, model=self.mn).embeddings
                else: r = [x.embedding for x in self.md.embeddings.create(input=b, model=self.mn).data]
                rs.extend(r)
                print(f"⏳ [系统日志] 高维向量映射流转状态: {min(i+bs, len(tx))}/{len(tx)}")
                time.sleep(0.6)
            except Exception as e:
                print(f"❌ [系统日志] API 通信链路阻断 / 鉴权失败: {e}"); raise
        return np.array(rs, dtype=np.float32)

    def _l_c(self):
        if os.path.exists(self.cf):
            print(f"⚡ [系统日志] I/O 快速命中 | 提取预编译高维张量缓存: {self.cf}")
            return np.load(self.cf)
        print(f"🚀 [系统日志] 本地矩阵空缺 | 触发 {self.mn} 全局张量重构协议 (警告: 若挂载云端模型将产生 Token 计费)")
        t = [(p.get('title', '') + " " + p.get('abstract', '')) for p in self.dt]
        e = self._e_b(t)
        np.save(self.cf, e)
        print(f"✅ [系统日志] 全局矩阵编译封卷 | 拓扑固化至目标路径: {self.cf}")
        return e

    # 🐛 FIX: 恢复了对外的标准参数名 query，完美适配 app.py 的调用
    def search(self, query, top_k=50):
        print(f"🔎 [系统日志] 捕获检索特征: '{query}' | 下潜深度: {top_k}")
        qe = self._e_b([query]) if self.mt != 'l' else self.md.encode(query, convert_to_numpy=True)
        if self.mt != 'l': qe = np.array(qe).reshape(1, -1)
        ht = util.semantic_search(qe, self.eb, top_k=top_k)[0]
        print(f"🎯 [系统日志] 张量空间欧氏碰撞完成，返回 top-{top_k} 匹配簇。")
        return [{"similarity": x['score'], "paper": self.dt[x['corpus_id']]} for x in ht]
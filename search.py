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
            try:
                # 尝试加载旧的矩阵
                e = np.load(self.cf)
                
                # 1. 如果长度一致，说明没有新文章，直接返回
                if e.shape[0] == len(self.dt):
                    return e
                
                # 2. 如果旧矩阵长度 < JSON论文库长度，说明有新文章加入了！触发【增量更新】
                elif e.shape[0] < len(self.dt):
                    print(f"📈 [系统日志] 触发【增量编译】! 现有缓存: {e.shape[0]}，目标总数: {len(self.dt)}")
                    # 切片提取出新增的文章
                    new_papers = self.dt[e.shape[0]:]
                    t = [(p.get('title', '') + " " + p.get('abstract', '')) for p in new_papers]
                    
                    # 只对新文章跑 Embedding
                    new_e = self._e_b(t)
                    
                    # 将新矩阵拼接到旧矩阵的末尾
                    e = np.vstack((e, new_e))
                    
                    # 保存拼接后的新矩阵覆盖旧文件
                    np.save(self.cf, e)
                    print(f"✅ [系统日志] 矩阵无缝拼接完成 | 增量固化至: {self.cf}")
                    return e
                
                # 3. 如果旧矩阵长度 > JSON库，或者发生了错位，说明文件体系损坏
                else:
                    print(f"⚠️ [系统日志] 数据库索引发生错乱 (NPY大于JSON)。疑似受到损坏，启动安全协议：强制全局重构...")
            
            except Exception as ex:
                print(f"⚠️ [系统日志] 缓存文件底层损坏无法读取 ({ex})。启动安全协议：强制全局重构...")

        # 4. 如果没有 .npy 文件，或者上面触发了重构机制，则全量重跑
        print(f"🚀 [系统日志] 本地矩阵空缺或已损坏 | 触发 {self.mn} 全局张量重构协议 (警告: 挂载云端模型将产生 Token 计费)")
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

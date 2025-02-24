from elasticsearch import Elasticsearch
import re
from sentence_transformers import SentenceTransformer
import fitz  # PyMuPDF
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt

class TreasuryProfiler:
    def __init__(self, es_host="http://localhost:9200"):
        self.es = Elasticsearch(es_host)
        self.index = "treasury_profiles"
        self.tx_index = "transactions"
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        
        # Ensure indices exist
        if not self.es.indices.exists(index=self.index):
            self.create_index()
        if not self.es.indices.exists(index=self.tx_index):
            self.create_transaction_index()
    
    def create_index(self):
        mapping = {
            "mappings": {
                "properties": {
                    "uscc": {"type": "keyword"},
                    "tin": {"type": "keyword"},
                    "corp_reg": {"type": "keyword"},
                    "name": {"type": "text"},
                    "industry": {"type": "text"},
                    "location": {"type": "text"},
                    "financials": {"type": "object"},
                    "documents": {"type": "text"},
                    "embeddings": {"type": "dense_vector", "dims": 768}
                }
            }
        }
        self.es.indices.create(index=self.index, body=mapping)
    
    def create_transaction_index(self):
        mapping = {
            "mappings": {
                "properties": {
                    "transaction_id": {"type": "keyword"},
                    "from_uscc": {"type": "keyword"},
                    "to_uscc": {"type": "keyword"},
                    "amount": {"type": "double"},
                    "currency": {"type": "keyword"},
                    "timestamp": {"type": "date"},
                    "description": {"type": "text"},
                    "embeddings": {"type": "dense_vector", "dims": 768}
                }
            }
        }
        self.es.indices.create(index=self.tx_index, body=mapping)
    
    def validate_uscc(self, uscc):
        return bool(re.match(r'^[0-9A-Z]{18}$', uscc))
    
    def generate_embedding(self, text):
        return self.model.encode(text).tolist()
    
    def add_profile(self, uscc, tin, corp_reg, name, industry, location, financials, documents=""):
        if not self.validate_uscc(uscc):
            raise ValueError("Invalid USCC format")
        
        embeddings = self.generate_embedding(documents) if documents else np.zeros(768).tolist()
        
        doc = {
            "uscc": uscc,
            "tin": tin,
            "corp_reg": corp_reg,
            "name": name,
            "industry": industry,
            "location": location,
            "financials": financials,
            "documents": documents,
            "embeddings": embeddings
        }
        res = self.es.index(index=self.index, document=doc)
        return res["_id"]
    
    def add_transaction(self, transaction_id, from_uscc, to_uscc, amount, currency, timestamp, description):
        if not self.validate_uscc(from_uscc) or not self.validate_uscc(to_uscc):
            raise ValueError("Invalid USCC format")
        
        embeddings = self.generate_embedding(description) if description else np.zeros(768).tolist()
        
        doc = {
            "transaction_id": transaction_id,
            "from_uscc": from_uscc,
            "to_uscc": to_uscc,
            "amount": amount,
            "currency": currency,
            "timestamp": timestamp,
            "description": description,
            "embeddings": embeddings
        }
        res = self.es.index(index=self.tx_index, document=doc)
        return res["_id"]
    
    def search_transactions(self, uscc, top_k=10):
        query = {
            "size": top_k,
            "query": {
                "bool": {
                    "should": [
                        {"match": {"from_uscc": uscc}},
                        {"match": {"to_uscc": uscc}}
                    ]
                }
            }
        }
        return self.es.search(index=self.tx_index, body=query)
    
    def map_transactions(self, uscc):
        transactions = self.search_transactions(uscc, top_k=100)["hits"]["hits"]
        G = nx.DiGraph()
        
        for tx in transactions:
            tx_data = tx["_source"]
            G.add_edge(tx_data["from_uscc"], tx_data["to_uscc"], weight=tx_data["amount"], label=tx_data["transaction_id"])
        
        plt.figure(figsize=(10, 6))
        pos = nx.spring_layout(G)
        nx.draw(G, pos, with_labels=True, node_color="lightblue", edge_color="gray", node_size=3000, font_size=10)
        edge_labels = {(u, v): d['label'] for u, v, d in G.edges(data=True)}
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=8)
        plt.title(f"Transaction Map for {uscc}")
        plt.show()
        
    def hybrid_transaction_search(self, query_text, uscc=None, top_k=5):
        query_vector = self.generate_embedding(query_text)
        query = {
            "size": top_k,
            "query": {
                "bool": {
                    "should": [
                        {"script_score": {
                            "query": {"match_all": {}},
                            "script": {
                                "source": "cosineSimilarity(params.query_vector, 'embeddings') + 1.0",
                                "params": {"query_vector": query_vector}
                            }
                        }}
                    ]
                }
            }
        }
        
        if uscc:
            query["query"]["bool"]["should"].extend([
                {"match": {"from_uscc": uscc}},
                {"match": {"to_uscc": uscc}}
            ])
        
        return self.es.search(index=self.tx_index, body=query)

if __name__ == "__main__":
    profiler = TreasuryProfiler()
    profiler.map_transactions("91500000747150402Q")

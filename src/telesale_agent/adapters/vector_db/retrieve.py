import logging
from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from telesale_agent.core.interfaces import Retriever
from telesale_agent.core.models import RetrievedContext, TurnContext

logger = logging.getLogger(__name__)

class VectorDBRetriever(Retriever):
    """
    RAG Retriever using ChromaDB and HuggingFace Embeddings.
    Queries the database using the raw transcript when a policy intent is detected.
    """
    
    def __init__(self, db_dir: str | Path | None = None):
        if db_dir is None:
            # Default to the dataset/chroma_db folder created by ingest script
            project_root = Path(__file__).resolve().parents[4]
            db_dir = project_root / "dataset" / "chroma_db"
            
        self.db_dir = str(db_dir)
        
        try:
            logger.info("Initializing VectorDB Retriever (loading Embeddings & Chroma)...")
            self.embeddings = HuggingFaceEmbeddings(model_name="keepitreal/vietnamese-sbert")
            self.vector_store = Chroma(
                persist_directory=self.db_dir, 
                embedding_function=self.embeddings
            )
            logger.info("VectorDB Retriever initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to load VectorDB: {e}")
            self.vector_store = None

    async def retrieve(self, context: TurnContext) -> RetrievedContext:
        knowledge = []
        
        if not self.vector_store or not context.perception:
            return RetrievedContext(knowledge=knowledge)
            
        intents = context.perception.intents or [context.perception.intent]
        transcript = context.perception.transcript.lower()
        
        # 1. Perform semantic search for policy-related intents
        if any(intent in intents for intent in ["ask_policy", "price_objection", "complain"]):
            
            results = self.vector_store.similarity_search(transcript, k=3)  
            for doc in results:
                # Format chunk as dict for backward compatibility
                knowledge.append({
                    "policy_chunk": doc.page_content,
                    "source_file": doc.metadata.get("source_file", "unknown"),
                    "section": doc.metadata.get("Header 2", "") or doc.metadata.get("Header 1", "")
                })
                
        # 2. Handle Product retrieval using Supabase Database (db_client)
        if "ask_product" in intents:
            from telesale_agent.adapters.db.client import db_client
            
            product_found = False
            entities = context.perception.entities or {}
            
            # Quét các thực thể (product_name) để search DB
            for val in entities.values():
                if isinstance(val, str):
                    query = val.lower()
                    # Bỏ qua các entity không phải là sản phẩm (ví dụ '25 mét vuông')
                    # Tốt nhất là check key: if key == 'product_name' nhưng do entities dict động nên ta search thử
                    try:
                        db_result = db_client.search_products(query=query)
                        if db_result and db_result.get("items"):
                            knowledge.extend(db_result["items"])
                            product_found = True
                    except Exception as e:
                        logger.error(f"Lỗi khi search DB: {e}")
            
            if not product_found:
                # Fallback: Quét thẳng transcript nếu LLM không bóc được entities
                try:
                    # Gửi vài từ khóa chính hoặc search rỗng để lấy list ngắn
                    db_result = db_client.search_products(query=transcript[:30]) # Lấy 1 phần transcript
                    if db_result and db_result.get("items"):
                        knowledge.extend(db_result["items"])
                        product_found = True
                except Exception:
                    pass

        return RetrievedContext(knowledge=knowledge)

import os
from pathlib import Path
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# Paths
ROOT_DIR = Path(__file__).resolve().parents[1]
POLICY_DIR = ROOT_DIR / "dataset" / "BTC-Data-Vong1-TEAMS" / "policy"
CHROMA_DB_DIR = ROOT_DIR / "data" / "chroma_db"

# Exclude trap files (Internal, Expired)
EXCLUDED_FILES = [
    "chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md",
    "ghi-chu-nhap-hang-NOI-BO.md",
]

def ingest_policies():
    print(f"Loading policies from {POLICY_DIR}...")
    
    docs = []
    for filename in os.listdir(POLICY_DIR):
        if not filename.endswith(".md"):
            continue
            
        if filename in EXCLUDED_FILES:
            print(f" ⚠️ Skipping trap file: {filename}")
            continue
            
        file_path = POLICY_DIR / filename
        loader = TextLoader(file_path, encoding='utf-8')
        raw_docs = loader.load()
        
        # Thêm metadata để sau này biết chunk này thuộc file nào
        for d in raw_docs:
            d.metadata["source_file"] = filename
            
        docs.extend(raw_docs)
        print(f" ✅ Loaded: {filename}")

    # 1. Chunking: Split by Markdown Headings first to preserve semantic blocks
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    
    md_splits = []
    for doc in docs:
        splits = markdown_splitter.split_text(doc.page_content)
        for split in splits:
            # Preserve original metadata
            split.metadata.update(doc.metadata)
        md_splits.extend(splits)

    # 2. Chunking: Secondary split by character count if some sections are still too long
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, 
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    final_chunks = text_splitter.split_documents(md_splits)
    
    print(f"\nCreated {len(final_chunks)} chunks from valid policy files.")

    # 3. Embedding Model (Vietnamese optimized or Multilingual)
    print("Loading HuggingFace Embeddings model (this may take a moment on first run)...")
    # BAAI/bge-m3 is excellent for Vietnamese, but heavier. 
    # keepitreal/vietnamese-sbert is lighter and fast. We use keepitreal for speed.
    embeddings = HuggingFaceEmbeddings(model_name="keepitreal/vietnamese-sbert")

    # 4. Save to ChromaDB
    print(f"Saving to ChromaDB at {CHROMA_DB_DIR}...")
    Chroma.from_documents(
        documents=final_chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DB_DIR)
    )
    
    print("✅ Ingestion complete! Database is ready to use.")

if __name__ == "__main__":
    ingest_policies()

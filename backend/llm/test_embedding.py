from sentence_transformers import SentenceTransformer
from llm.schemas import CONCERT_SINGER_SCHEMA

# Load the embedding model
model = SentenceTransformer("all-MiniLM-L6-v2")

# Convert our schema text into a vector
embedding = model.encode(CONCERT_SINGER_SCHEMA)

print("Schema embedded successfully")
print("Vector size:", len(embedding))
print("First 5 values:", embedding[:5])

from sentence_transformers import SentenceTransformer
from llm.schemas import CONCERT_SINGER_SCHEMA
from db import get_connection

# Load embedding model
model = SentenceTransformer("all-MiniLM-L6-v2")

# Generate embedding for the schema
embedding = model.encode(CONCERT_SINGER_SCHEMA).tolist()

# Connect to PostgreSQL
conn = get_connection()
cursor = conn.cursor()

# Store the schema and its embedding
cursor.execute(
    """
    INSERT INTO schema_embeddings
        (database_name, schema_text, embedding)
    VALUES (%s, %s, %s)
    """,
    (
        "concert_singer",
        CONCERT_SINGER_SCHEMA,
        embedding,
    ),
)

conn.commit()

cursor.close()
conn.close()

print("Schema embedding stored successfully")

# QueryPilot

QueryPilot is an AI-powered Text-to-SQL system that allows users to ask questions in natural language and automatically generates and executes PostgreSQL queries.

## Current Features

- Natural-language to PostgreSQL SQL generation
- Automatic database routing
- Schema-aware SQL generation
- RAG using semantically similar Spider examples
- PostgreSQL + pgvector integration
- SQL safety checks for read-only execution
- PostgreSQL identifier validation and repair
- Strict and semantic execution-based evaluation
- Tie-aware evaluation

## Current Pipeline

User Question  
↓  
Database Routing  
↓  
Schema Retrieval  
↓  
Top-5 RAG Example Retrieval  
↓  
LLM SQL Generation  
↓  
SQL Validation / Preparation  
↓  
PostgreSQL Execution  
↓  
Result

## Tech Stack

- Python
- FastAPI
- PostgreSQL
- pgvector
- Docker
- Sentence Transformers
- Groq LLM API
- Spider Text-to-SQL Dataset

## Evaluation Results

### DEV Set

- Database Routing Accuracy: 100%
- Strict Execution Accuracy: 93.33%
- Semantic Execution Accuracy: 100%
- Execution Errors: 0

### Holdout Set

- Strict Accuracy: 100%
- Semantic Accuracy: 100%
- Execution Errors: 0

> Note: The current holdout set contains 5 questions, so these results represent the current project benchmark and should not be interpreted as universal Text-to-SQL accuracy.

## Project Structure

```text
querypilot/
├── backend/
│   ├── eval/
│   ├── llm/
│   ├── db.py
│   ├── main.py
│   └── requirements.txt
├── docker-compose.yml
├── load_spider_sample.py
├── .env.example
├── .gitignore
└── README.md

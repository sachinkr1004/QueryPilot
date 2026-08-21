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
- Automatic SQL self-correction using PostgreSQL execution errors

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
If Execution Fails
↓
LLM Self-Correction using PostgreSQL Error
↓
Retry Corrected SQL (Max 1 Retry)
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

### Phase 6 Self-Correction

- DEV Strict Accuracy: 93.33%
- DEV Semantic Accuracy: 100%
- DEV Execution Success Rate: 100%
- HOLDOUT Strict Accuracy: 100%
- HOLDOUT Semantic Accuracy: 100%
- HOLDOUT Execution Success Rate: 100%
- Self-correction retry limit: 1

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

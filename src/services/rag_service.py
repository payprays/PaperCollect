import os
import json
import glob
import yaml
import numpy as np
from typing import List, Dict, Any
from openai import OpenAI
from tqdm import tqdm
import pickle

class RAGService:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.api_key = self.config.get("openai_api_key")
        if not self.api_key:
            raise ValueError("openai_api_key not found in config.yaml")
            
        self.client = OpenAI(api_key=self.api_key)
        self.model = self.config.get("openai_model", "gpt-4o")
        self.embedding_model = self.config.get("embedding_model", "text-embedding-3-small")
        
        self.data_dir = "data"
        self.embeddings_file = os.path.join(self.data_dir, "embeddings.pkl")
        
        self.papers = []
        self.embeddings = None
        
        self._load_data()

    def _load_data(self):
        """Load papers and embeddings with incremental updates."""
        print("Loading papers...")
        json_files = glob.glob(os.path.join(self.data_dir, "*.json"))
        self.papers = []
        
        # Map title -> paper object for quick lookup
        self.paper_map = {}
        
        for f in json_files:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    for p in data:
                        p['source_file'] = os.path.basename(f)
                        # Use title as unique key (simple approach)
                        title = p.get('title', '')
                        if title:
                            self.papers.append(p)
                            self.paper_map[title] = p
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON: {f}")
                
        print(f"Loaded {len(self.papers)} papers.")
        
        cached_embeddings = {}
        if os.path.exists(self.embeddings_file):
            print("Loading cached embeddings...")
            try:
                with open(self.embeddings_file, 'rb') as f:
                    data = pickle.load(f)
                    # Convert list/array back to dict for easy lookup
                    # data['ids'] is list of titles, data['embeddings'] is numpy array
                    ids = data.get('ids', [])
                    embs = data.get('embeddings', [])
                    if len(ids) == len(embs):
                        for i, title in enumerate(ids):
                            cached_embeddings[title] = embs[i]
            except Exception as e:
                print(f"Error loading cache: {e}. Will recompute all.")
        
        # Identify missing embeddings
        missing_titles = []
        for p in self.papers:
            title = p.get('title', '')
            if title not in cached_embeddings:
                missing_titles.append(title)
                
        if missing_titles:
            print(f"Found {len(missing_titles)} new papers without embeddings. Computing...")
            new_embeddings_dict = self._compute_embeddings_for_titles(missing_titles)
            cached_embeddings.update(new_embeddings_dict)
            
            # Save updated cache
            print("Updating cache...")
            self._save_cache(cached_embeddings)
        else:
            print("All papers have cached embeddings.")
            
        # Reconstruct the aligned embedding matrix matching self.papers order
        # This is crucial for the search index to match the papers list
        matrix = []
        valid_papers = []
        
        for p in self.papers:
            title = p.get('title', '')
            if title in cached_embeddings:
                matrix.append(cached_embeddings[title])
                valid_papers.append(p)
            else:
                # Should not happen if compute succeeded
                pass
                
        self.embeddings = np.array(matrix)
        self.papers = valid_papers # Update papers list to match embeddings exactly

    def _compute_embeddings_for_titles(self, titles: List[str]) -> Dict[str, np.ndarray]:
        """Compute embeddings for a specific list of titles."""
        texts = []
        for title in titles:
            p = self.paper_map.get(title)
            if not p:
                continue
            abstract = p.get('abstract') or ""
            text = f"Title: {title}\nAbstract: {abstract}"
            texts.append(text)
            
        batch_size = 100
        new_embeddings_map = {}
        
        print(f"Generating embeddings for {len(texts)} items...")
        for i in tqdm(range(0, len(texts), batch_size)):
            batch_texts = texts[i:i+batch_size]
            batch_titles = titles[i:i+batch_size]
            try:
                response = self.client.embeddings.create(
                    input=batch_texts,
                    model=self.embedding_model
                )
                for j, item in enumerate(response.data):
                    new_embeddings_map[batch_titles[j]] = np.array(item.embedding)
            except Exception as e:
                print(f"Error generating embeddings for batch {i}: {e}")
                
        return new_embeddings_map

    def _save_cache(self, embeddings_map: Dict[str, np.ndarray]):
        """Save embeddings map to disk."""
        titles = list(embeddings_map.keys())
        embs = list(embeddings_map.values())
        with open(self.embeddings_file, 'wb') as f:
            pickle.dump({
                'ids': titles,
                'embeddings': np.array(embs)
            }, f)

    # Deprecated: _compute_embeddings removed in favor of incremental approach

    def search(self, query: str, top_k: int = 10, year: int | None = None, venue: str | None = None) -> List[Dict[str, Any]]:
        """
        Search for relevant papers with optional filtering.
        """
        if self.embeddings is None:
            return []

        # Embed query
        response = self.client.embeddings.create(
            input=query,
            model=self.embedding_model
        )
        query_embedding = np.array(response.data[0].embedding)
        
        # Cosine similarity
        norm_query = np.linalg.norm(query_embedding)
        norm_embeddings = np.linalg.norm(self.embeddings, axis=1)
        norm_embeddings[norm_embeddings == 0] = 1e-10
        
        similarities = np.dot(self.embeddings, query_embedding) / (norm_embeddings * norm_query)
        
        # Get indices sorted by similarity
        sorted_indices = np.argsort(similarities)[::-1]
        
        results = []
        for idx in sorted_indices:
            paper = self.papers[idx]
            
            # Apply filters
            if year and paper.get('year') != year:
                continue
            if venue and venue.lower() not in paper.get('venue', '').lower():
                continue
                
            paper['score'] = float(similarities[idx])
            results.append(paper)
            
            if len(results) >= top_k:
                break
            
        return results

    def ask(self, query: str, top_k: int = 20, year: int | None = None, venue: str | None = None) -> str:
        """Ask a question using RAG with optional filters."""
        filters = []
        if year: filters.append(f"Year: {year}")
        if venue: filters.append(f"Venue: {venue}")
        filter_str = f" ({', '.join(filters)})" if filters else ""
        
        print(f"Searching for: {query}{filter_str}")
        
        relevant_papers = self.search(query, top_k=top_k, year=year, venue=venue)
        
        if not relevant_papers:
            return "No relevant papers found matching your criteria."

        context_parts = []
        for i, p in enumerate(relevant_papers):
            context_parts.append(f"Paper {i+1}:\nTitle: {p.get('title')}\nVenue: {p.get('venue')} ({p.get('year')})\nAbstract: {p.get('abstract')}\n")
            
        context = "\n---\n".join(context_parts)
        
        system_prompt = """You are an expert academic researcher assistant. 
You will be provided with a user question and a set of relevant paper abstracts.
Your task is to answer the user's question based PRIMARILY on the provided papers.
Synthesize the information, cite the papers (by Title or Author/Year) where appropriate.
If the papers do not contain the answer, state that the provided papers do not cover this topic, but you can provide general knowledge (but clearly distinguish it).
"""
        
        user_prompt = f"""Question: {query}

Filters applied: {filter_str}
Here are the most relevant papers found in the database:

{context}

Please answer the question based on these papers.
"""

        print("Querying GPT-4o...")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5
        )
        
        return response.choices[0].message.content or "No response generated."

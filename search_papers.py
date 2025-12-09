import argparse
from src.services.rag_service import RAGService

def main():
    parser = argparse.ArgumentParser(description="Search papers using RAG.")
    parser.add_argument("query", type=str, help="The search query or question.")
    parser.add_argument("--top_k", type=int, default=20, help="Number of papers to retrieve.")
    parser.add_argument("--mode", type=str, choices=["search", "ask"], default="ask", help="Mode: 'search' for raw results, 'ask' for LLM answer.")
    parser.add_argument("--year", type=int, help="Filter by year (e.g., 2024).")
    parser.add_argument("--venue", type=str, help="Filter by venue (e.g., 'ICSE').")
    
    args = parser.parse_args()
    
    try:
        service = RAGService()
        
        if args.mode == "search":
            results = service.search(args.query, top_k=args.top_k, year=args.year, venue=args.venue)
            
            # Translate results
            results = service.translate_papers(results)
            
            print(f"\nTop {len(results)} results for '{args.query}':\n")
            for i, p in enumerate(results):
                print(f"{i+1}. [{p['score']:.4f}] {p['title']} ({p['venue']} {p['year']})")
                if p.get('title_zh'):
                    print(f"    中文标题: {p.get('title_zh')}")
                
                # print(f"   Abstract: {p.get('abstract')[:200]}...")
                if p.get('abstract_zh'):
                    # Print abstract with some indentation
                    abs_zh = p.get('abstract_zh')
                    # Wrap text for better readability if needed, but simple print is fine for now
                    print(f"    中文摘要: {abs_zh}")
                print()
        else:
            answer = service.ask(args.query, top_k=args.top_k, year=args.year, venue=args.venue)
            print("\n" + "="*50)
            print("Answer:")
            print("="*50)
            print(answer)
            
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()

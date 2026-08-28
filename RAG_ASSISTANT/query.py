from vector_store import search_in_pinecone, hybrid_search_in_pinecone
from llm import query_llm_with_context


def process_user_query(query: str):
    semantic_matched_chunks = search_in_pinecone(query, namespace="__default__")
    hybrid_matched_chunks = hybrid_search_in_pinecone(query, namespace="__hybrid__")

    semantic_generated_response = query_llm_with_context(query, semantic_matched_chunks)
    hybrid_generated_response = query_llm_with_context(query, hybrid_matched_chunks)

    _print_comparison(
        query,
        semantic_generated_response,
        hybrid_generated_response,
        semantic_count=len(semantic_matched_chunks),
        hybrid_count=len(hybrid_matched_chunks),
    )


def _print_comparison(query, semantic_answer, hybrid_answer, semantic_count, hybrid_count):
    width = 72
    rule = "=" * width
    thin = "-" * width

    print()
    print(rule)
    print("RAG COMPARISON")
    print(rule)
    print(f"Question: {query}")
    print()

    print(thin)
    print("A. Character chunking  +  semantic search")
    print(f"   Namespace: __default__    Retrieved chunks: {semantic_count}")
    print(thin)
    print(semantic_answer.strip() if semantic_answer else "(no answer)")
    print()

    print(thin)
    print("B. Structure-aware chunking  +  hybrid search (semantic + BM25)")
    print(f"   Namespace: __hybrid__     Retrieved chunks: {hybrid_count}")
    print(thin)
    print(hybrid_answer.strip() if hybrid_answer else "(no answer)")
    print()
    print(rule)


if __name__ == "__main__":
    print("Welcome to the RAG demo!")
    # user_query = "What rows are eligible for migration?"
    # user_query = "What is OPENVIDU_PUBLICURL used for?"
    # user_query = "How is VONAGE_API_KEY used?"
    # user_query = "What happens to session when migrating from openvidu to vonage?"
    # user_query = "What is the migration workflow?"
    # user_query = "What does _contact_ids_for_client_emails do?"
    user_query = "How are client emails resolved?"
    # user_query = "What are the available migration options?"

    process_user_query(user_query)
